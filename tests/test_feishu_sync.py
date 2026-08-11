"""Mock-only FEISHU-003B synchronization tests."""

from __future__ import annotations

import calendar
import copy
import json
import os
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.analysis.trend_models import ThemeTrendScore
from src.cli import main
from src.config import AppConfig
from src.feishu.client import FeishuClient
from src.feishu.errors import (
    FeishuAPIError,
    FeishuDuplicateManagedKeyError,
    FeishuHTTPError,
    FeishuMalformedResponseError,
    FeishuManagedRecordIntegrityError,
    FeishuPartialSynchronizationError,
    FeishuRecordIntegrityError,
    FeishuRequestError,
    FeishuSourceValidationError,
    FeishuStaleManagedRecordError,
    FeishuTimeoutError,
)
from src.feishu.field_schema import desired_feishu_fields
from src.feishu.models import FeishuSyncRecord
from src.feishu.synchronization import (
    MANAGED_KEY_PATTERN,
    PRIMARY_FIELD_NAME,
    build_batch_create_payload,
    build_batch_update_fields,
    build_desired_trend_records,
    build_reconciliation_plan,
    managed_key_for_score,
    parse_sync_record_item,
    score_to_feishu_fields,
    sync_field_mappings,
    validate_authoritative_scores,
)
from src.storage import DuckDBRepository
from src.workflows import SyncFeishuTrendsRequest, sync_feishu_trends

APP_ID = "sync_test_app_id"
APP_SECRET = "sync_test_app_secret_do_not_log"
APP_TOKEN = "sync_test_app_token_1234"
TABLE_ID = "tbl_sync_test"
TENANT_TOKEN = "sync_tenant_token_do_not_log"
CALCULATED_AT = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def _config(database_path: Path) -> AppConfig:
    return AppConfig(
        database_path=database_path,
        feishu_app_id=APP_ID,
        feishu_app_secret=APP_SECRET,
        feishu_bitable_app_token=APP_TOKEN,
        feishu_bitable_table_id=TABLE_ID,
    )


def _score(
    theme: str,
    month: int,
    *,
    actionable: bool = True,
    rank: int | None = 1,
    calculated_at: datetime = CALCULATED_AT,
) -> ThemeTrendScore:
    period_start = date(2026, month, 1)
    period_end = date(2026, month, calendar.monthrange(2026, month)[1])
    window_month_index = period_start.year * 12 + period_start.month - 1 - 5
    window_year, window_month_zero_based = divmod(window_month_index, 12)
    window_start = date(window_year, window_month_zero_based + 1, 1)
    return ThemeTrendScore(
        scope_name="casual_puzzle_tabletop",
        cadence="monthly",
        period_start=period_start,
        period_end=period_end,
        game_theme=theme,
        window_start=window_start,
        window_month_count=6,
        active_months_6m=6 if actionable else 1,
        latest_product_count=5 if actionable else 2,
        is_actionable=actionable,
        exclusion_reason=None if actionable else "insufficient_latest_product_count",
        latest_product_share=0.0 if not actionable else 0.5,
        latest_units_absolute_share=0.0,
        latest_revenue_absolute_share=0.0,
        latest_new_entry_share=0.0 if actionable else None,
        latest_median_rank=50.0,
        latest_publisher_count=2,
        latest_top_publisher_product_share=0.0,
        product_share_gain_3m=0.0,
        units_absolute_share_gain_3m=0.0,
        revenue_absolute_share_gain_3m=0.0,
        product_share_acceleration=0.0,
        units_absolute_share_acceleration=0.0,
        revenue_absolute_share_acceleration=0.0,
        recent3_new_entry_share=0.0 if actionable else None,
        median_rank_improvement=0.0,
        publisher_count_gain_3m=0.0,
        units_absolute_overindex=0.0,
        revenue_absolute_overindex=0.0,
        recent3_units_coverage_ratio=0.0,
        recent3_revenue_coverage_ratio=0.0,
        latest_publisher_coverage_ratio=0.0,
        growth_score=0.0 if actionable else None,
        acceleration_score=0.0 if actionable else None,
        new_product_score=0.0 if actionable else None,
        concentration_penalty=0.0 if actionable else None,
        base_trend_score=0.0 if actionable else None,
        confidence_score=0.0,
        trend_score=0.0 if actionable else None,
        trend_rank=rank if actionable else None,
        calculated_at=calculated_at,
    )


def _repository_with_scores(path: Path, scores: list[ThemeTrendScore]) -> None:
    repository = DuckDBRepository(path)
    repository.open()
    repository.initialize_schema()
    repository.replace_theme_trend_score_range(scores)
    repository.close()


def _primary_field() -> dict[str, object]:
    return {
        "field_id": "fld_primary",
        "field_name": PRIMARY_FIELD_NAME,
        "type": 1,
        "ui_type": "Text",
        "is_primary": True,
    }


def _complete_fields() -> list[dict[str, object]]:
    fields: list[dict[str, object]] = [_primary_field()]
    for index, field in enumerate(desired_feishu_fields(), start=1):
        item: dict[str, object] = {
            "field_id": f"fld_managed_{index:02d}",
            "field_name": field.field_name,
            "type": field.verified_api_type,
            "ui_type": {
                1: "Text",
                2: "Number",
                5: "DateTime",
                7: "Checkbox",
            }[field.verified_api_type],
            "is_primary": False,
        }
        if field.property is not None:
            item["property"] = dict(field.property)
        fields.append(item)
    return fields


def _server(
    records: list[dict[str, object]],
    *,
    response_override: Any | None = None,
) -> tuple[httpx.MockTransport, list[httpx.Request], list[dict[str, object]]]:
    requests: list[httpx.Request] = []
    state = copy.deepcopy(records)
    next_record_number = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal next_record_number
        requests.append(request)

        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": TENANT_TOKEN, "expire": 7200},
            )
        if request.method == "GET" and request.url.path.endswith("/fields"):
            return httpx.Response(
                200,
                json={"code": 0, "data": {"items": _complete_fields(), "has_more": False}},
            )
        if request.method == "GET" and request.url.path.endswith("/records"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"items": copy.deepcopy(state), "has_more": False},
                },
            )
        if request.method == "POST" and request.url.path.endswith("/records/batch_create"):
            if response_override is not None:
                override_response = response_override(request)
                if override_response is not None:
                    return override_response
            body = json.loads(request.content.decode("utf-8"))
            response_records: list[dict[str, str]] = []
            for payload in body["records"]:
                next_record_number += 1
                record_id = f"rec_created_{next_record_number}"
                state.append({"record_id": record_id, "fields": payload["fields"]})
                response_records.append({"record_id": record_id})
            return httpx.Response(200, json={"code": 0, "data": {"records": response_records}})
        if request.method == "POST" and request.url.path.endswith("/records/batch_update"):
            if response_override is not None:
                override_response = response_override(request)
                if override_response is not None:
                    return override_response
            body = json.loads(request.content.decode("utf-8"))
            response_records = []
            for payload in body["records"]:
                match = next(
                    item for item in state if item["record_id"] == payload["record_id"]
                )
                fields = match["fields"]
                assert isinstance(fields, dict)
                fields.update(payload["fields"])
                response_records.append({"record_id": payload["record_id"]})
            return httpx.Response(200, json={"code": 0, "data": {"records": response_records}})
        return httpx.Response(404, json={"code": 404})

    return httpx.MockTransport(handler), requests, state


def _record_requests(requests: list[httpx.Request]) -> list[httpx.Request]:
    return [request for request in requests if "/records" in request.url.path]


def test_plan_only_bypasses_config_logging_duckdb_and_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in tuple(os.environ):
        if name.startswith("APP_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("sync plan-only crossed a disabled boundary")

    monkeypatch.setattr("src.cli.load_config", fail)
    monkeypatch.setattr("src.cli.configure_logging", fail)
    monkeypatch.setattr("src.storage.connection.open_duckdb_connection", fail)
    monkeypatch.setattr(httpx, "Client", fail)

    assert main(["sync-feishu-trends", "--plan-only"]) == 0
    output = capsys.readouterr().out
    assert "mode=plan-only" in output
    assert "configuration=disabled" in output
    assert "network=disabled" in output
    assert "database=disabled" in output
    assert "unmanaged_records=preserved" in output
    assert not (tmp_path / "data").exists()


def test_sync_invalid_mode_combination_fails_before_configuration() -> None:
    with pytest.raises(SystemExit) as error:
        main(["sync-feishu-trends", "--plan-only", "--apply"])
    assert error.value.code == 2


def test_managed_key_is_exact_deterministic_unicode_and_separator_safe() -> None:
    score = _score("动物/主题\n with spaces \x1f", 1)
    same = _score("动物/主题\n with spaces \x1f", 1)
    assert managed_key_for_score(score) == managed_key_for_score(same)
    assert MANAGED_KEY_PATTERN.fullmatch(managed_key_for_score(score)) is not None
    assert managed_key_for_score(score) != managed_key_for_score(_score("other", 1))
    assert managed_key_for_score(score) != managed_key_for_score(_score(score.game_theme, 2))
    assert managed_key_for_score(score) != managed_key_for_score(
        _score("动物/主题\n with spaces \x1e", 1)
    )


def test_all_21_fields_map_in_schema_order_and_convert_dates_without_rounding() -> None:
    calculated_at = datetime(2026, 8, 11, 20, 34, 56, 789654, tzinfo=timezone(timedelta(hours=8)))
    score = _score("Theme", 1, calculated_at=calculated_at)
    fields = score_to_feishu_fields(score, latest_period_start=score.period_start)
    mappings = sync_field_mappings()

    assert tuple(fields) == tuple(mapping.field_name for mapping in mappings)
    assert fields[mappings[0].field_name] == int(
        datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000
    )
    assert fields[mappings[-1].field_name] == int(calculated_at.timestamp() * 1000)
    assert fields[mappings[6].field_name] == 0.0
    assert fields[mappings[3].field_name] is True


def test_latest_month_flag_uses_the_maximum_period_across_the_source_set() -> None:
    records = build_desired_trend_records(
        [_score("Theme", 1), _score("Other", 2)],
        scope_name="casual_puzzle_tabletop",
    )
    mappings = sync_field_mappings()
    latest_field = mappings[2].field_name
    assert records[0].fields[latest_field] is False
    assert records[1].fields[latest_field] is True


def test_none_zero_and_false_are_distinct_in_create_and_update_payloads() -> None:
    older = build_desired_trend_records(
        [_score("Theme", 1), _score("Theme", 2)],
        scope_name="casual_puzzle_tabletop",
    )[0]
    payload = build_batch_create_payload(older)
    fields = payload["fields"]
    assert isinstance(fields, dict)
    latest_field = sync_field_mappings()[2].field_name
    optional_none_field = sync_field_mappings()[4].field_name
    zero_field = sync_field_mappings()[14].field_name
    assert fields[latest_field] is False
    assert fields[zero_field] == 0.0
    assert optional_none_field not in fields

    changed = build_batch_update_fields(
        older,
        {
            **dict(older.fields),
            zero_field: None,
            latest_field: True,
        },
    )
    assert changed[zero_field] == 0.0
    assert changed[latest_field] is False

    tolerant = build_batch_update_fields(
        older,
        {**dict(older.fields), sync_field_mappings()[6].field_name: 1e-10},
    )
    assert sync_field_mappings()[6].field_name not in tolerant


def test_unmanaged_rows_skip_unrelated_shapes_and_managed_rows_are_normalized() -> None:
    score = _score("Theme", 1)
    desired = build_desired_trend_records(
        [score],
        scope_name="casual_puzzle_tabletop",
    )[0]
    theme_field = sync_field_mappings()[1].field_name
    parsed = parse_sync_record_item(
        {
            "record_id": "rec_managed",
            "fields": {
                PRIMARY_FIELD_NAME: desired.managed_key,
                theme_field: [{"text": "Theme"}],
            },
        }
    )
    assert parsed.primary_value == desired.managed_key
    assert parsed.fields[theme_field] == "Theme"

    unmanaged = parse_sync_record_item(
        {
            "record_id": "rec_unmanaged",
            "fields": {
                PRIMARY_FIELD_NAME: "user-owned",
                theme_field: object(),
            },
        }
    )
    assert unmanaged.primary_value == "user-owned"
    assert dict(unmanaged.fields) == {}

    with pytest.raises(FeishuManagedRecordIntegrityError):
        parse_sync_record_item(
            {
                "record_id": "rec_bad",
                "fields": {
                    PRIMARY_FIELD_NAME: desired.managed_key,
                    sync_field_mappings()[5].field_name: object(),
                },
            }
        )


def test_reconciliation_is_deterministic_and_preserves_five_blank_records() -> None:
    scores = [_score("Theme", 1), _score("Theme", 2)]
    desired = build_desired_trend_records(
        scores,
        scope_name="casual_puzzle_tabletop",
    )
    blank_records = [
        FeishuSyncRecord(f"rec_blank_{index}", None, {}) for index in range(5)
    ]
    managed = FeishuSyncRecord("rec_managed", desired[0].managed_key, desired[0].fields)
    unmanaged = FeishuSyncRecord("rec_unmanaged", "user-owned", {})
    plan = build_reconciliation_plan(
        scores,
        [unmanaged, *blank_records, managed],
        scope_name="casual_puzzle_tabletop",
    )
    reversed_plan = build_reconciliation_plan(
        scores,
        [managed, *reversed(blank_records), unmanaged],
        scope_name="casual_puzzle_tabletop",
    )
    assert plan.current_record_count == 7
    assert plan.managed_record_count == 1
    assert plan.unmanaged_blank_record_count == 5
    assert plan.unmanaged_nonblank_record_count == 1
    assert plan.create_count == 1
    assert plan.update_count == 0
    assert plan.unchanged_count == 1
    assert repr(plan) == repr(reversed_plan)


def test_duplicate_and_stale_managed_records_are_typed_and_sanitized() -> None:
    score = _score("Theme", 1)
    desired = build_desired_trend_records(
        [score],
        scope_name="casual_puzzle_tabletop",
    )[0]
    duplicate_plan = build_reconciliation_plan(
        [score],
        [
            FeishuSyncRecord("rec_one", desired.managed_key, desired.fields),
            FeishuSyncRecord("rec_two", desired.managed_key, desired.fields),
        ],
        scope_name="casual_puzzle_tabletop",
    )
    assert duplicate_plan.duplicate_managed_key_count == 1
    with pytest.raises(FeishuDuplicateManagedKeyError) as duplicate_error:
        from src.feishu.synchronization import require_no_duplicate_managed_keys

        require_no_duplicate_managed_keys(duplicate_plan)
    assert desired.managed_key not in str(duplicate_error.value)
    assert "rec_one" not in str(duplicate_error.value)

    stale_score = _score("Stale", 2)
    stale_desired = build_desired_trend_records(
        [stale_score],
        scope_name="casual_puzzle_tabletop",
    )[0]
    stale_plan = build_reconciliation_plan(
        [score],
        [FeishuSyncRecord("rec_stale", stale_desired.managed_key, stale_desired.fields)],
        scope_name="casual_puzzle_tabletop",
    )
    assert stale_plan.stale_managed_record_count == 1
    with pytest.raises(FeishuStaleManagedRecordError):
        from src.feishu.synchronization import require_no_stale_managed_records

        require_no_stale_managed_records(stale_plan)


def test_apply_uses_batch_create_only_paces_between_requests_and_verifies(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "sync.duckdb"
    scores = [_score("Theme", 1), _score("Theme", 2)]
    _repository_with_scores(database_path, scores)
    transport, requests, state = _server(
        [{"record_id": f"rec_blank_{i}", "fields": {}} for i in range(5)]
    )
    sleeps: list[float] = []

    summary = sync_feishu_trends(
        SyncFeishuTrendsRequest(database_path=database_path, apply=True),
        _config(database_path),
        transport=transport,
        sleep=sleeps.append,
        write_batch_size=1,
    )

    record_requests = _record_requests(requests)
    assert summary.created_count == 2
    assert summary.updated_count == 0
    assert summary.final_managed_record_count == 2
    assert summary.final_create_count == 0
    assert summary.final_update_count == 0
    assert [request.url.path.rsplit("/", 1)[-1] for request in record_requests] == [
        "records",
        "batch_create",
        "batch_create",
        "records",
    ]
    assert sleeps == [0.5]
    assert sum(not record["fields"] for record in state[:5]) == 5
    assert all("batch_update" not in request.url.path for request in requests)

    requests.clear()
    noop = sync_feishu_trends(
        SyncFeishuTrendsRequest(database_path=database_path, apply=True),
        _config(database_path),
        transport=transport,
        sleep=sleeps.append,
    )
    assert noop.created_count == 0
    assert noop.updated_count == 0
    assert noop.final_create_count == 0
    assert noop.final_update_count == 0
    assert not any("batch_" in request.url.path for request in requests)


def test_default_sync_is_a_dry_run_and_never_writes(tmp_path: Path) -> None:
    database_path = tmp_path / "dry-run.duckdb"
    _repository_with_scores(database_path, [_score("Theme", 1)])
    transport, requests, state = _server(
        [{"record_id": f"rec_blank_{i}", "fields": {}} for i in range(5)]
    )

    summary = sync_feishu_trends(
        SyncFeishuTrendsRequest(database_path=database_path),
        _config(database_path),
        transport=transport,
    )

    assert summary.mode == "dry-run"
    assert summary.create_count == 1
    assert summary.update_count == 0
    assert [request.url.path.rsplit("/", 1)[-1] for request in _record_requests(requests)] == [
        "records"
    ]
    assert len(state) == 5


def test_second_dry_run_is_noop_and_changed_value_plans_update(tmp_path: Path) -> None:
    database_path = tmp_path / "sync.duckdb"
    scores = [_score("Theme", 1)]
    _repository_with_scores(database_path, scores)
    desired = build_desired_trend_records(
        scores,
        scope_name="casual_puzzle_tabletop",
    )[0]
    transport, requests, state = _server(
        [{"record_id": "rec_blank", "fields": {}}]
    )
    sync_feishu_trends(
        SyncFeishuTrendsRequest(database_path=database_path, apply=True),
        _config(database_path),
        transport=transport,
        sleep=lambda _: None,
    )
    requests.clear()
    dry_run = sync_feishu_trends(
        SyncFeishuTrendsRequest(database_path=database_path),
        _config(database_path),
        transport=transport,
    )
    assert dry_run.create_count == 0
    assert dry_run.update_count == 0
    assert dry_run.unchanged_count == 1
    assert not any("batch_" in request.url.path for request in requests)

    managed_record = next(
        record
        for record in state
        if record["fields"].get(PRIMARY_FIELD_NAME) == desired.managed_key
    )
    managed_fields = managed_record["fields"]
    assert isinstance(managed_fields, dict)
    managed_fields[sync_field_mappings()[6].field_name] = 99.0
    requests.clear()
    changed = sync_feishu_trends(
        SyncFeishuTrendsRequest(database_path=database_path),
        _config(database_path),
        transport=transport,
    )
    assert changed.create_count == 0
    assert changed.update_count == 1


def test_stale_apply_fails_before_batch_write(tmp_path: Path) -> None:
    database_path = tmp_path / "sync.duckdb"
    source_score = _score("Theme", 1)
    stale_score = _score("Stale", 2)
    stale_desired = build_desired_trend_records(
        [stale_score],
        scope_name="casual_puzzle_tabletop",
    )[0]
    _repository_with_scores(database_path, [source_score])
    transport, requests, _ = _server(
        [{"record_id": "rec_stale", "fields": build_batch_create_payload(stale_desired)["fields"]}]
    )

    with pytest.raises(FeishuStaleManagedRecordError):
        sync_feishu_trends(
            SyncFeishuTrendsRequest(database_path=database_path, apply=True),
            _config(database_path),
            transport=transport,
        )
    assert not any("batch_" in request.url.path for request in requests)


def test_batch_response_count_mismatch_is_typed_and_sanitized(tmp_path: Path) -> None:
    score = _score("Theme", 1)

    def bad_response(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "data": {"records": []}})

    transport, _requests, _ = _server([], response_override=bad_response)
    config = _config(tmp_path / "unused.duckdb")
    client_config = config.feishu_client_config
    with FeishuClient.from_config(client_config, transport=transport) as client:
        client.get_tenant_access_token()
        with pytest.raises(FeishuMalformedResponseError):
            client.batch_create_records(
                app_token=APP_TOKEN,
                table_id=TABLE_ID,
                records=[
                    build_batch_create_payload(
                        build_desired_trend_records(
                            [score],
                            scope_name="casual_puzzle_tabletop",
                        )[0]
                    )
                ],
            )


def test_source_validation_rejects_empty_mixed_cadence_and_duplicate_rows() -> None:
    score = _score("Theme", 1)
    with pytest.raises(FeishuSourceValidationError):
        validate_authoritative_scores([], scope_name=score.scope_name)

    mixed_scope = _score("Other", 1)
    object.__setattr__(mixed_scope, "scope_name", "other_scope")
    with pytest.raises(FeishuSourceValidationError):
        validate_authoritative_scores(
            [score, mixed_scope],
            scope_name=score.scope_name,
        )

    nonmonthly = _score("Weekly", 1)
    object.__setattr__(nonmonthly, "cadence", "weekly")
    with pytest.raises(FeishuSourceValidationError):
        validate_authoritative_scores([nonmonthly], scope_name=score.scope_name)

    with pytest.raises(FeishuSourceValidationError):
        validate_authoritative_scores([score, score], scope_name=score.scope_name)


def test_apply_updates_changed_record_with_exact_batch_update_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "update.duckdb"
    score = _score("Theme", 1)
    _repository_with_scores(database_path, [score])
    transport, requests, state = _server([{"record_id": "rec_blank", "fields": {}}])
    sync_feishu_trends(
        SyncFeishuTrendsRequest(database_path=database_path, apply=True),
        _config(database_path),
        transport=transport,
        sleep=lambda _: None,
    )
    managed_record = next(
        record
        for record in state
        if record["fields"].get(PRIMARY_FIELD_NAME) is not None
    )
    managed_fields = managed_record["fields"]
    assert isinstance(managed_fields, dict)
    changed_field = sync_field_mappings()[6].field_name
    managed_fields[changed_field] = 99.0
    requests.clear()

    summary = sync_feishu_trends(
        SyncFeishuTrendsRequest(database_path=database_path, apply=True),
        _config(database_path),
        transport=transport,
        sleep=lambda _: None,
    )

    assert summary.planned_create_count == 0
    assert summary.planned_update_count == 1
    update_requests = [
        request
        for request in requests
        if request.url.path.endswith("/records/batch_update")
    ]
    assert len(update_requests) == 1
    body = json.loads(update_requests[0].content.decode("utf-8"))
    assert set(body) == {"records"}
    assert set(body["records"][0]) == {"record_id", "fields"}
    assert body["records"][0]["fields"] == {changed_field: 0.0}
    assert PRIMARY_FIELD_NAME not in body["records"][0]["fields"]


@pytest.mark.parametrize(
    ("override", "error_type"),
    [
        (
            lambda _request: httpx.Response(
                503,
                text=f"forbidden {APP_TOKEN} {TENANT_TOKEN}",
            ),
            FeishuHTTPError,
        ),
        (
            lambda _request: httpx.Response(
                200,
                json={"code": 1254081, "msg": f"bad {APP_SECRET}"},
            ),
            FeishuAPIError,
        ),
    ],
)
def test_batch_http_and_api_failures_are_sanitized(
    tmp_path: Path,
    override: Any,
    error_type: type[Exception],
) -> None:
    score = _score("Theme", 1)
    transport, _requests, _ = _server([], response_override=override)
    config = _config(tmp_path / "errors.duckdb")
    with FeishuClient.from_config(config.feishu_client_config, transport=transport) as client:
        client.get_tenant_access_token()
        with pytest.raises(error_type) as error:
            client.batch_create_records(
                app_token=APP_TOKEN,
                table_id=TABLE_ID,
                records=[
                    build_batch_create_payload(
                        build_desired_trend_records(
                            [score],
                            scope_name="casual_puzzle_tabletop",
                        )[0]
                    )
                ],
            )
    assert APP_SECRET not in str(error.value)
    assert APP_TOKEN not in str(error.value)
    assert TENANT_TOKEN not in str(error.value)


def test_batch_duplicate_ids_and_transport_errors_are_typed(tmp_path: Path) -> None:
    scores = [_score("Theme", 1), _score("Other", 2)]

    def duplicate_response(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 0, "data": {"records": [{"record_id": "rec_same"}] * 2}},
        )

    transport, _requests, _ = _server([], response_override=duplicate_response)
    config = _config(tmp_path / "duplicate-response.duckdb")
    payloads = [
        build_batch_create_payload(record)
        for record in build_desired_trend_records(
            scores,
            scope_name="casual_puzzle_tabletop",
        )
    ]
    with FeishuClient.from_config(config.feishu_client_config, transport=transport) as client:
        client.get_tenant_access_token()
        with pytest.raises(FeishuRecordIntegrityError):
            client.batch_create_records(
                app_token=APP_TOKEN,
                table_id=TABLE_ID,
                records=payloads,
            )

    def timeout_response(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timeout {APP_TOKEN} {TENANT_TOKEN}", request=_request)

    transport, _requests, _ = _server([], response_override=timeout_response)
    with FeishuClient.from_config(config.feishu_client_config, transport=transport) as client:
        client.get_tenant_access_token()
        with pytest.raises(FeishuTimeoutError) as error:
            client.batch_create_records(
                app_token=APP_TOKEN,
                table_id=TABLE_ID,
                records=[payloads[0]],
            )
    assert error.value.__context__ is None

    def connection_response(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"connection {APP_TOKEN} {TENANT_TOKEN}",
            request=_request,
        )

    transport, _requests, _ = _server([], response_override=connection_response)
    with FeishuClient.from_config(config.feishu_client_config, transport=transport) as client:
        client.get_tenant_access_token()
        with pytest.raises(FeishuRequestError) as error:
            client.batch_create_records(
                app_token=APP_TOKEN,
                table_id=TABLE_ID,
                records=[payloads[0]],
            )
    assert error.value.__context__ is None


def test_partial_multi_batch_completion_is_rerunnable(tmp_path: Path) -> None:
    database_path = tmp_path / "partial.duckdb"
    scores = [_score("Theme", 1), _score("Other", 2)]
    _repository_with_scores(database_path, scores)
    calls = 0
    failure_enabled = True

    def override(_request: httpx.Request) -> httpx.Response | None:
        nonlocal calls
        calls += 1
        if failure_enabled and calls == 2:
            return httpx.Response(500, text=f"temporary {TENANT_TOKEN}")
        return None

    transport, requests, _state = _server([], response_override=override)
    with pytest.raises(FeishuPartialSynchronizationError) as error:
        sync_feishu_trends(
            SyncFeishuTrendsRequest(database_path=database_path, apply=True),
            _config(database_path),
            transport=transport,
            write_batch_size=1,
            sleep=lambda _: None,
        )
    assert error.value.successful_write_request_count == 1
    assert not any(request.url.path.endswith("/records") for request in requests[3:])

    failure_enabled = False
    requests.clear()
    summary = sync_feishu_trends(
        SyncFeishuTrendsRequest(database_path=database_path, apply=True),
        _config(database_path),
        transport=transport,
        write_batch_size=1,
        sleep=lambda _: None,
    )
    assert summary.final_create_count == 0
    assert summary.final_update_count == 0
