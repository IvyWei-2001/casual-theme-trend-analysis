"""Mock-only tests for FEISHU-003A read-only Bitable record inspection."""

from __future__ import annotations

import os
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.__main__ import main
from src.config import AppConfig
from src.feishu.client import FeishuClient
from src.feishu.errors import (
    FeishuAPIError,
    FeishuHTTPError,
    FeishuMalformedResponseError,
    FeishuRecordIntegrityError,
    FeishuRequestError,
    FeishuSchemaIntegrityError,
    FeishuTimeoutError,
)
from src.feishu.field_schema import desired_feishu_fields
from src.feishu.inspection import (
    format_feishu_record_inspection_summary,
    inspect_feishu_records,
)
from src.feishu.models import FeishuClientConfig, FeishuRecordInspectionResult

APP_ID = "record_test_app_id"
APP_SECRET = "record_test_app_secret_do_not_log"
APP_TOKEN = "record_test_app_token_1234"
TABLE_ID = "tbl_record_test"
VIEW_ID = "vew_record_test"
TENANT_TOKEN = "record_tenant_token_do_not_log"
INSPECTED_AT = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def _config() -> AppConfig:
    return AppConfig(
        feishu_app_id=APP_ID,
        feishu_app_secret=APP_SECRET,
        feishu_bitable_app_token=APP_TOKEN,
        feishu_bitable_table_id=TABLE_ID,
        feishu_bitable_view_id=VIEW_ID,
        feishu_timeout_seconds=7,
    )


def _direct_client_config() -> FeishuClientConfig:
    return _config().feishu_client_config


def _primary_field() -> dict[str, Any]:
    return {
        "field_id": "fld_primary",
        "field_name": "文本",
        "type": 1,
        "ui_type": "Text",
        "is_primary": True,
    }


def _complete_field_items() -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = [_primary_field()]
    for index, desired in enumerate(desired_feishu_fields(), start=1):
        payload = desired.api_payload()
        item: dict[str, Any] = {
            "field_id": f"fld_{index}",
            "field_name": desired.field_name,
            "type": payload["type"],
            "is_primary": False,
        }
        if "property" in payload:
            item["property"] = payload["property"]
        fields.append(item)
    return fields


def _fields_response(
    fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "code": 0,
        "msg": "contains no useful test output",
        "data": {
            "items": _complete_field_items() if fields is None else fields,
            "has_more": False,
        },
    }


def _records_response(
    items: object,
    *,
    has_more: object = False,
    page_token: object = "__missing__",
) -> dict[str, Any]:
    data: dict[str, Any] = {"items": items, "has_more": has_more}
    if page_token != "__missing__":
        data["page_token"] = page_token
    return {"code": 0, "data": data}


def _server(
    record_responses: list[dict[str, Any]],
    *,
    fields: list[dict[str, Any]] | None = None,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    record_index = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal record_index
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": TENANT_TOKEN},
            )
        assert request.method == "GET"
        if request.url.path.endswith("/fields"):
            return httpx.Response(200, json=_fields_response(fields))
        if request.url.path.endswith("/records"):
            response = record_responses[record_index]
            record_index += 1
            return httpx.Response(200, json=response)
        raise AssertionError(f"unexpected path suffix: {request.url.path}")

    return httpx.MockTransport(handler), requests


def _client(transport: httpx.BaseTransport) -> FeishuClient:
    return FeishuClient.from_config(_direct_client_config(), transport=transport)


def _records_request(requests: list[httpx.Request]) -> list[httpx.Request]:
    return [request for request in requests if request.url.path.endswith("/records")]


def _assert_secrets_absent(value: str) -> None:
    assert APP_SECRET not in value
    assert TENANT_TOKEN not in value
    assert APP_TOKEN not in value


def _formatted_error(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def test_empty_record_table_is_one_page_and_omits_view_filter_and_search_params() -> None:
    transport, requests = _server([_records_response([])])

    with _client(transport) as client:
        client.get_tenant_access_token()
        result = client.list_records(app_token=APP_TOKEN, table_id=TABLE_ID)

    record_requests = _records_request(requests)
    assert result.page_count == 1
    assert result.record_count == 0
    assert result.records_with_primary_value == 0
    assert result.observed_field_names == frozenset()
    assert dict(record_requests[0].url.params) == {"page_size": "100"}
    assert record_requests[0].headers["Authorization"] == f"Bearer {TENANT_TOKEN}"


def test_single_page_records_keep_only_safe_presence_metadata() -> None:
    transport, _requests = _server(
        [
            _records_response(
                [
                    {
                        "record_id": "rec_sensitive_1",
                        "fields": {
                            "文本": "primary cell secret",
                            "趋势分": 99.5,
                        },
                        "unknown": "discarded",
                    },
                    {"record_id": "rec_sensitive_2", "fields": {"文本": ""}},
                ]
            )
        ]
    )

    with _client(transport) as client:
        client.get_tenant_access_token()
        result = client.list_records(app_token=APP_TOKEN, table_id=TABLE_ID)

    assert result.record_count == 2
    assert result.records[0].record_id == "rec_sensitive_1"
    assert result.records[0].fields_is_mapping is True
    assert result.records[0].field_names == frozenset({"文本", "趋势分"})
    assert result.records[0].has_primary_value is True
    assert result.records[1].has_primary_value is False
    rendered = repr(result)
    assert "rec_sensitive_1" not in rendered
    assert "primary cell secret" not in rendered
    assert "99.5" not in rendered


def test_multiple_pages_use_response_token_and_never_send_view_id() -> None:
    transport, requests = _server(
        [
            _records_response(
                [{"record_id": "rec_page_1", "fields": {"文本": "one"}}],
                has_more=True,
                page_token="records-next",
            ),
            _records_response(
                [{"record_id": "rec_page_2", "fields": {"月份": 0}}]
            ),
        ]
    )

    with _client(transport) as client:
        client.get_tenant_access_token()
        result = client.list_records(app_token=APP_TOKEN, table_id=TABLE_ID)

    record_requests = _records_request(requests)
    assert result.page_count == 2
    assert result.record_count == 2
    assert "page_token" not in record_requests[0].url.params
    assert record_requests[1].url.params["page_token"] == "records-next"
    for request in record_requests:
        assert "view_id" not in request.url.params
        assert "filter" not in request.url.params
        assert "sort" not in request.url.params
        assert "search" not in request.url.params


@pytest.mark.parametrize(
    "response",
    [
        _records_response(["not-a-record"]),
        _records_response([{"fields": {}}]),
        _records_response([{"record_id": "", "fields": {}}]),
        _records_response([{"record_id": "rec_bad", "fields": []}]),
        {"code": 0, "data": {"items": "not-a-list"}},
        {"code": 0, "data": []},
        {"code": "0", "data": {"items": [], "has_more": False}},
        {"code": True, "data": {"items": [], "has_more": False}},
        {"code": 1001, "msg": "secret response text", "data": {}},
        _records_response([], has_more="false"),
        _records_response([], has_more=False, page_token=None),
        _records_response([], has_more=False, page_token=42),
    ],
)
def test_malformed_and_nonzero_record_responses_are_typed_and_sanitized(
    response: dict[str, Any],
) -> None:
    transport, _requests = _server([response])

    with _client(transport) as client:
        client.get_tenant_access_token()
        expected = FeishuAPIError if response.get("code") == 1001 else (
            FeishuMalformedResponseError
        )
        with pytest.raises(expected) as error:
            client.list_records(app_token=APP_TOKEN, table_id=TABLE_ID)

    _assert_secrets_absent(_formatted_error(error.value))
    assert "secret response text" not in _formatted_error(error.value)


def test_nonzero_code_is_not_replaced_with_raw_response_message() -> None:
    transport, _requests = _server(
        [{"code": 1254081, "msg": f"raw {APP_SECRET} {APP_TOKEN}", "data": {}}]
    )

    with _client(transport) as client:
        client.get_tenant_access_token()
        with pytest.raises(FeishuAPIError) as error:
            client.list_records(app_token=APP_TOKEN, table_id=TABLE_ID)

    assert str(error.value) == "Feishu record inspection failed with response code 1254081"
    _assert_secrets_absent(_formatted_error(error.value))


@pytest.mark.parametrize(
    "record_items",
    [
        [
            {"record_id": "rec_duplicate", "fields": {}},
            {"record_id": "rec_duplicate", "fields": {"文本": "same"}},
        ],
    ],
)
def test_duplicate_record_id_fails_without_exposing_the_identifier(
    record_items: list[dict[str, Any]],
) -> None:
    transport, _requests = _server([_records_response(record_items)])

    with _client(transport) as client:
        client.get_tenant_access_token()
        with pytest.raises(FeishuRecordIntegrityError) as error:
            client.list_records(app_token=APP_TOKEN, table_id=TABLE_ID)

    assert "rec_duplicate" not in _formatted_error(error.value)


def test_repeated_page_token_fails_without_exposing_the_token() -> None:
    transport, _requests = _server(
        [
            _records_response([], has_more=True, page_token="repeated-page-token"),
            _records_response([], has_more=True, page_token="repeated-page-token"),
        ]
    )

    with _client(transport) as client:
        client.get_tenant_access_token()
        with pytest.raises(FeishuRecordIntegrityError) as error:
            client.list_records(app_token=APP_TOKEN, table_id=TABLE_ID)

    assert "repeated-page-token" not in _formatted_error(error.value)


@pytest.mark.parametrize(
    "page_token",
    [
        pytest.param("__missing__", id="missing"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace-only"),
    ],
)
def test_has_more_true_without_a_nonempty_page_token_fails_locally(
    page_token: str,
) -> None:
    response = _records_response(
        [],
        has_more=True,
        **({} if page_token == "__missing__" else {"page_token": page_token}),
    )
    transport, requests = _server([response])

    with _client(transport) as client:
        client.get_tenant_access_token()
        with pytest.raises(FeishuRecordIntegrityError) as error:
            client.list_records(app_token=APP_TOKEN, table_id=TABLE_ID)

    rendered = _formatted_error(error.value)
    assert len(_records_request(requests)) == 1
    assert f"page_token={page_token}" not in rendered
    _assert_secrets_absent(rendered)
    assert "https://open.feishu.cn" not in rendered


def test_feishu_production_boundary_has_no_record_write_operations() -> None:
    source_root = Path(__file__).parents[1] / "src" / "feishu"
    forbidden = (
        "def create_record",
        "def update_record",
        "delete_record",
        "batch_delete",
        "/records/search",
        "method=\"DELETE\"",
        "method='DELETE'",
        "method=\"PUT\"",
        "method='PUT'",
        "method=\"PATCH\"",
        "method='PATCH'",
    )

    violations = [
        f"{path.name}:{term}"
        for path in sorted(source_root.glob("*.py"))
        for term in forbidden
        if term in path.read_text(encoding="utf-8")
    ]

    assert violations == []
    client_source = (source_root / "client.py").read_text(encoding="utf-8")
    assert "/records/batch_create" in client_source
    assert "/records/batch_update" in client_source


@pytest.mark.parametrize("failure", ["timeout", "connection", "http", "json"])
def test_request_failures_do_not_leak_httpx_context_or_secrets(failure: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"code": 0, "tenant_access_token": TENANT_TOKEN})
        if failure == "timeout":
            raise httpx.ReadTimeout(f"timeout {APP_TOKEN} {TENANT_TOKEN}", request=request)
        if failure == "connection":
            raise httpx.ConnectError(f"connection {APP_TOKEN} {TENANT_TOKEN}", request=request)
        if failure == "http":
            return httpx.Response(403, text=f"forbidden {APP_TOKEN} {TENANT_TOKEN}")
        return httpx.Response(200, content=f"not-json {APP_SECRET}".encode())

    with _client(httpx.MockTransport(handler)) as client:
        client.get_tenant_access_token()
        expected = {
            "timeout": FeishuTimeoutError,
            "connection": FeishuRequestError,
            "http": FeishuHTTPError,
            "json": FeishuMalformedResponseError,
        }[failure]
        with pytest.raises(expected) as error:
            client.list_records(app_token=APP_TOKEN, table_id=TABLE_ID)

    rendered = _formatted_error(error.value)
    _assert_secrets_absent(rendered)
    assert error.value.__context__ is None
    assert error.value.__cause__ is None


def test_schema_precheck_blocks_records_when_fields_are_missing() -> None:
    transport, requests = _server([_records_response([])], fields=[_primary_field()])

    with pytest.raises(FeishuSchemaIntegrityError):
        inspect_feishu_records(_config(), transport=transport, inspected_at=INSPECTED_AT)

    assert [request.method for request in requests] == ["POST", "GET"]
    assert not _records_request(requests)


def test_schema_precheck_blocks_records_when_a_desired_field_is_incompatible() -> None:
    fields = _complete_field_items()
    fields[1]["type"] = 2
    fields[1]["property"] = {"formatter": "0.00"}
    transport, requests = _server([_records_response([])], fields=fields)

    with pytest.raises(FeishuSchemaIntegrityError):
        inspect_feishu_records(_config(), transport=transport, inspected_at=INSPECTED_AT)

    assert [request.method for request in requests] == ["POST", "GET"]
    assert not _records_request(requests)


def test_schema_gated_record_summary_is_safe_and_complete() -> None:
    transport, requests = _server(
        [
            _records_response(
                [
                    {
                        "record_id": "rec_not_in_output_1",
                        "fields": {"文本": "primary secret", "题材": "Animals"},
                    }
                ],
                has_more=True,
                page_token="next-record-page",
            ),
            _records_response(
                [
                    {
                        "record_id": "rec_not_in_output_2",
                        "fields": {"文本": None, "趋势分": 1.2},
                    }
                ]
            ),
        ]
    )

    result = inspect_feishu_records(
        _config(),
        transport=transport,
        inspected_at=INSPECTED_AT,
    )
    output = format_feishu_record_inspection_summary(result)

    assert result.schema_field_count == 22
    assert result.desired_non_primary_field_count == 21
    assert result.compatible_existing_count == 21
    assert result.missing_field_count == 0
    assert result.incompatible_field_count == 0
    assert result.existing_primary_field_name == "文本"
    assert result.record_page_count == 2
    assert result.record_count == 2
    assert result.records_with_primary_value == 1
    assert result.records_without_primary_value == 1
    assert result.observed_field_name_count == 3
    assert result.duplicate_record_id_count == 0
    assert result.app_token_suffix == "1234"
    assert result.table_id == TABLE_ID
    assert "Feishu record inspection complete:" in output
    assert "mode=read-only" in output
    assert "record_count=2" in output
    assert "rec_not_in_output_1" not in output
    assert "primary secret" not in output
    assert APP_TOKEN not in output
    assert APP_SECRET not in output
    assert TENANT_TOKEN not in output
    assert "https://" not in output
    assert [request.method for request in requests] == ["POST", "GET", "GET", "GET"]


def test_record_inspection_result_repr_contains_counts_only() -> None:
    result = FeishuRecordInspectionResult(
        schema_field_count=22,
        desired_non_primary_field_count=21,
        compatible_existing_count=21,
        missing_field_count=0,
        incompatible_field_count=0,
        existing_primary_field_name="文本",
        record_page_count=1,
        record_count=1,
        records_with_primary_value=1,
        records_without_primary_value=0,
        observed_field_name_count=2,
        duplicate_record_id_count=0,
        inspected_at=INSPECTED_AT,
        app_token_suffix="1234",
        table_id=TABLE_ID,
    )

    rendered = repr(result)
    assert "rec_not_in_output" not in rendered
    assert APP_TOKEN not in rendered
    assert "primary secret" not in rendered


def test_plan_only_does_not_load_configuration_logging_or_http_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in tuple(os.environ):
        if name.startswith("APP_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("record plan-only must not perform local or network setup")

    monkeypatch.setattr("src.cli.load_config", fail)
    monkeypatch.setattr("src.cli.configure_logging", fail)
    monkeypatch.setattr(httpx, "Client", fail)

    exit_code = main(["inspect-feishu-records", "--plan-only"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "mode=plan-only" in output
    assert "network=disabled" in output
    assert "database=disabled" in output
    assert "file_writes=disabled" in output
    assert "records_view_id=omitted" in output
    assert not (tmp_path / "data").exists()
