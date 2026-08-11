"""Mock-only tests for FEISHU-002 field-schema provisioning."""

from __future__ import annotations

import copy
import json
import os
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.__main__ import main
from src.config import AppConfig
from src.feishu.errors import (
    FeishuAPIError,
    FeishuHTTPError,
    FeishuMalformedResponseError,
    FeishuPartialProvisioningError,
    FeishuSchemaCompatibilityError,
    FeishuSchemaIntegrityError,
    FeishuSchemaValidationError,
    FeishuTimeoutError,
)
from src.feishu.field_schema import (
    DESIRED_FEISHU_FIELDS,
    FeishuDesiredField,
    desired_feishu_fields,
    validate_desired_schema,
)
from src.feishu.models import FeishuBitableField
from src.feishu.provisioning import (
    build_feishu_schema_plan,
    plan_feishu_schema,
    provision_feishu_schema,
)

APP_ID = "schema_test_app_id"
APP_SECRET = "schema_test_app_secret_do_not_log"
APP_TOKEN = "schema_test_app_token_1234"
TABLE_ID = "tbl_schema_test"
VIEW_ID = "vew_schema_test"
TENANT_TOKEN = "schema_tenant_token_do_not_log"
INSPECTED_AT = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 8, 11, 12, 1, tzinfo=UTC)


def _config() -> AppConfig:
    return AppConfig(
        feishu_app_id=APP_ID,
        feishu_app_secret=APP_SECRET,
        feishu_bitable_app_token=APP_TOKEN,
        feishu_bitable_table_id=TABLE_ID,
        feishu_bitable_view_id=VIEW_ID,
        feishu_timeout_seconds=7,
    )


def _primary_field(*, field_id: str = "fld_primary") -> dict[str, Any]:
    return {
        "field_id": field_id,
        "field_name": "文本",
        "type": 1,
        "ui_type": "Text",
        "is_primary": True,
    }


def _field_from_desired(
    desired: FeishuDesiredField,
    *,
    field_id: str,
    is_primary: bool = False,
) -> dict[str, Any]:
    payload = desired.api_payload()
    default_ui_type = {
        1: "Text",
        2: "Number",
        5: "DateTime",
        7: "Checkbox",
    }[desired.verified_api_type]
    field: dict[str, Any] = {
        "field_id": field_id,
        "field_name": payload["field_name"],
        "type": payload["type"],
        "ui_type": payload.get("ui_type", default_ui_type),
        "is_primary": is_primary,
    }
    if "property" in payload:
        field["property"] = copy.deepcopy(payload["property"])
    return field


def _server(
    initial_fields: list[dict[str, Any]] | None = None,
    *,
    create_failure: Callable[[int, httpx.Request], httpx.Response] | None = None,
    fail_at: int = 1,
) -> tuple[httpx.MockTransport, list[httpx.Request], list[dict[str, Any]]]:
    fields = copy.deepcopy(initial_fields or [_primary_field()])
    requests: list[httpx.Request] = []
    create_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal create_count
        requests.append(request)
        if request.url.path == "/open-apis/auth/v3/tenant_access_token/internal":
            assert request.method == "POST"
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "tenant_access_token": TENANT_TOKEN,
                    "expire": 7200,
                },
            )

        if request.url.path.endswith("/fields") and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"items": copy.deepcopy(fields), "has_more": False},
                },
            )

        if request.url.path.endswith("/fields") and request.method == "POST":
            create_count += 1
            if create_failure is not None and create_count == fail_at:
                return create_failure(create_count, request)
            body = json.loads(request.content.decode("utf-8"))
            field_id = f"fld_created_{create_count:02d}"
            field = {
                "field_id": field_id,
                "field_name": body["field_name"],
                "type": body["type"],
                "ui_type": {
                    1: "Text",
                    2: "Number",
                    5: "DateTime",
                    7: "Checkbox",
                }[body["type"]],
                "is_primary": False,
            }
            if "property" in body:
                field["property"] = copy.deepcopy(body["property"])
            fields.append(field)
            return httpx.Response(200, json={"code": 0, "data": {"field": field}})

        return httpx.Response(404, json={"code": 404})

    return httpx.MockTransport(handler), requests, fields


def _field_requests(requests: list[httpx.Request]) -> list[httpx.Request]:
    return [
        request
        for request in requests
        if request.url.path.endswith("/fields") and request.method == "POST"
    ]


def _assert_secrets_absent(value: str) -> None:
    assert APP_SECRET not in value
    assert TENANT_TOKEN not in value
    assert APP_TOKEN not in value


def test_desired_schema_has_exact_order_and_verified_properties() -> None:
    fields = desired_feishu_fields()
    expected_names = [
        "月份",
        "题材",
        "是否最新月份",
        "是否可行动",
        "排除原因",
        "趋势排名",
        "趋势分",
        "置信度",
        "增长分",
        "加速度分",
        "新产品分",
        "集中度惩罚",
        "最新产品数",
        "最新产品份额",
        "units_absolute份额",
        "revenue_absolute份额",
        "近3月新进入占比",
        "排名改善",
        "units_absolute超配倍数",
        "revenue_absolute超配倍数",
        "计算时间",
    ]

    assert len(fields) == 21
    assert [field.field_name for field in fields] == expected_names
    assert len(set(expected_names)) == len(expected_names)
    assert fields[0].verified_api_type == 5
    assert fields[0].property == {
        "date_formatter": "yyyy/MM/dd",
        "auto_fill": False,
    }
    assert fields[2].verified_api_type == 7
    assert fields[5].property == {"formatter": "0"}
    assert fields[6].property == {"formatter": "0.00"}
    assert fields[13].property == {"formatter": "0.00%"}
    assert fields[14].field_name == "units_absolute份额"
    assert fields[15].field_name == "revenue_absolute份额"
    assert fields[20].property == {
        "date_formatter": "yyyy-MM-dd HH:mm",
        "auto_fill": False,
    }


def test_schema_definition_is_validated_locally_and_rejects_duplicate_names() -> None:
    duplicate = FeishuDesiredField(
        field_name=DESIRED_FEISHU_FIELDS[0].field_name,
        logical_type="text",
        verified_api_type=1,
        ui_type=None,
        property=None,
        display_order=22,
    )

    with pytest.raises(FeishuSchemaValidationError):
        validate_desired_schema(DESIRED_FEISHU_FIELDS + (duplicate,))


def test_plan_only_needs_no_credentials_network_database_or_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in tuple(os.environ):
        if name.startswith("APP_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    def fail_client(*args: object, **kwargs: object) -> object:
        raise AssertionError("plan-only must not construct an HTTP client")

    monkeypatch.setattr(httpx, "Client", fail_client)
    exit_code = main(["provision-feishu-schema", "--plan-only"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "network=disabled" in output
    assert "database=disabled" in output
    assert "file_writes=disabled" in output
    assert "desired_non_primary_field_count=21" in output
    assert all(field.field_name in output for field in desired_feishu_fields())
    assert not (tmp_path / "data").exists()


def test_cli_rejects_plan_only_and_apply_together() -> None:
    with pytest.raises(SystemExit) as error:
        main(["provision-feishu-schema", "--plan-only", "--apply"])

    assert error.value.code == 2


def test_live_dry_run_lists_current_primary_and_never_creates_fields() -> None:
    transport, requests, _ = _server()
    plan = plan_feishu_schema(_config(), transport=transport)

    assert plan.current_field_count == 1
    assert plan.desired_field_count == 21
    assert plan.compatible_field_count == 0
    assert len(plan.missing_field_names) == 21
    assert plan.existing_primary_field_name == "文本"
    assert [request.method for request in requests] == ["POST", "GET"]
    assert _field_requests(requests) == []


def test_apply_creates_all_fields_in_order_and_sleeps_only_between_creates() -> None:
    transport, requests, fields = _server()
    sleeps: list[float] = []

    result = provision_feishu_schema(
        _config(),
        transport=transport,
        sleep=sleeps.append,
        inspected_at=INSPECTED_AT,
        completed_at=COMPLETED_AT,
    )

    desired = desired_feishu_fields()
    field_requests = _field_requests(requests)
    payloads = [json.loads(request.content.decode("utf-8")) for request in field_requests]
    assert result.before_field_count == 1
    assert result.created_field_count == 21
    assert result.compatible_field_count == 21
    assert result.final_field_count == 22
    assert result.created_field_names == tuple(field.field_name for field in desired)
    assert result.existing_primary_field_name == "文本"
    assert result.app_token_suffix == "1234"
    assert result.inspected_at == INSPECTED_AT
    assert result.completed_at == COMPLETED_AT
    assert [payload["field_name"] for payload in payloads] == list(result.created_field_names)
    assert payloads[0] == {
        "field_name": "月份",
        "type": 5,
        "property": {"date_formatter": "yyyy/MM/dd", "auto_fill": False},
    }
    assert payloads[2] == {"field_name": "是否最新月份", "type": 7}
    assert payloads[13]["property"] == {"formatter": "0.00%"}
    assert sleeps == [0.15] * 20
    assert len(fields) == 22
    assert [request.method for request in requests] == (
        ["POST", "GET"] + ["POST"] * 21 + ["GET"]
    )
    assert all(request.method not in {"PUT", "PATCH", "DELETE"} for request in requests)
    assert all("/records" not in request.url.path for request in requests)


def test_second_apply_is_idempotent_and_makes_no_create_request() -> None:
    transport, requests, _ = _server()
    provision_feishu_schema(_config(), transport=transport, sleep=lambda _: None)
    requests.clear()
    sleeps: list[float] = []

    result = provision_feishu_schema(
        _config(),
        transport=transport,
        sleep=sleeps.append,
        inspected_at=INSPECTED_AT,
        completed_at=COMPLETED_AT,
    )

    assert result.created_field_count == 0
    assert result.created_field_names == ()
    assert [request.method for request in requests] == ["POST", "GET", "GET"]
    assert _field_requests(requests) == []
    assert sleeps == []


def test_existing_compatible_fields_and_unrelated_fields_are_retained() -> None:
    desired = desired_feishu_fields()
    initial = [_primary_field()]
    initial.extend(
        _field_from_desired(field, field_id=f"fld_existing_{index}")
        for index, field in enumerate(desired[:4], start=1)
    )
    initial.append(
        {
            "field_id": "fld_unrelated",
            "field_name": "Unrelated",
            "type": 1,
            "ui_type": "Text",
            "is_primary": False,
        }
    )
    transport, requests, fields = _server(initial)

    result = provision_feishu_schema(_config(), transport=transport, sleep=lambda _: None)

    assert result.created_field_count == 17
    assert result.final_field_count == 23
    assert any(field["field_name"] == "Unrelated" for field in fields)
    assert len(_field_requests(requests)) == 17


def test_response_field_order_does_not_change_matching() -> None:
    desired = desired_feishu_fields()
    initial = [_primary_field()]
    initial.extend(
        _field_from_desired(field, field_id=f"fld_existing_{index}")
        for index, field in enumerate(desired[:3], start=1)
    )
    transport, requests, fields = _server(initial)

    original_handler = transport.handler

    def reversed_handler(request: httpx.Request) -> httpx.Response:
        response = original_handler(request)
        if request.method == "GET" and request.url.path.endswith("/fields"):
            payload = response.json()
            payload["data"]["items"] = list(reversed(payload["data"]["items"]))
            return httpx.Response(response.status_code, json=payload)
        return response

    result = provision_feishu_schema(
        _config(),
        transport=httpx.MockTransport(reversed_handler),
        sleep=lambda _: None,
    )

    assert result.created_field_count == 18
    assert result.final_field_count == 22
    assert len(fields) == 22
    assert len(_field_requests(requests)) == 18


def test_wrong_type_collision_fails_before_any_creation() -> None:
    wrong = {
        "field_id": "fld_wrong_type",
        "field_name": "趋势分",
        "type": 1,
        "ui_type": "Text",
        "is_primary": False,
    }
    transport, requests, _ = _server([_primary_field(), wrong])

    with pytest.raises(FeishuSchemaCompatibilityError) as error:
        provision_feishu_schema(_config(), transport=transport)

    message = str(error.value)
    assert "趋势分" in message
    assert "expected_logical_type=number" in message
    assert "actual_api_type=1" in message
    assert [request.method for request in requests] == ["POST", "GET"]


def test_incompatible_percentage_formatter_fails_before_any_creation() -> None:
    field = _field_from_desired(
        next(item for item in desired_feishu_fields() if item.field_name == "最新产品份额"),
        field_id="fld_wrong_formatter",
    )
    field["property"] = {"formatter": "0.00"}
    transport, requests, _ = _server([_primary_field(), field])

    with pytest.raises(FeishuSchemaCompatibilityError):
        provision_feishu_schema(_config(), transport=transport)

    assert [request.method for request in requests] == ["POST", "GET"]


def test_duplicate_existing_desired_name_fails_before_creation() -> None:
    desired_field = _field_from_desired(
        desired_feishu_fields()[0],
        field_id="fld_duplicate_one",
    )
    duplicate = copy.deepcopy(desired_field)
    duplicate["field_id"] = "fld_duplicate_two"
    transport, requests, _ = _server([_primary_field(), desired_field, duplicate])

    with pytest.raises(FeishuSchemaIntegrityError):
        provision_feishu_schema(_config(), transport=transport)

    assert [request.method for request in requests] == ["POST", "GET"]


@pytest.mark.parametrize(
    "initial_fields",
    [
        [
            {
                "field_id": "fld_non_primary",
                "field_name": "文本",
                "type": 1,
                "ui_type": "Text",
                "is_primary": False,
            }
        ],
        [_primary_field(), {**_primary_field(field_id="fld_second"), "field_name": "另一个主键"}],
    ],
)
def test_primary_field_integrity_is_required(
    initial_fields: list[dict[str, Any]],
) -> None:
    transport, requests, _ = _server(initial_fields)

    with pytest.raises(FeishuSchemaIntegrityError):
        provision_feishu_schema(_config(), transport=transport)

    assert [request.method for request in requests] == ["POST", "GET"]


@pytest.mark.parametrize(
    ("failure_response", "error_type"),
    [
        (
            lambda _index, _request: httpx.Response(
                403,
                text=f"forbidden {APP_TOKEN} {TENANT_TOKEN}",
            ),
            FeishuHTTPError,
        ),
        (
            lambda _index, _request: httpx.Response(
                200,
                json={"code": 1254081, "msg": f"bad {APP_SECRET}"},
            ),
            FeishuAPIError,
        ),
        (
            lambda _index, _request: httpx.Response(
                200,
                json={"code": 0, "data": {}},
            ),
            FeishuMalformedResponseError,
        ),
    ],
)
def test_create_failures_are_typed_and_sanitized(
    failure_response: Callable[[int, httpx.Request], httpx.Response],
    error_type: type[Exception],
) -> None:
    transport, _requests, _ = _server(create_failure=failure_response)

    with pytest.raises(error_type) as error:
        provision_feishu_schema(_config(), transport=transport)

    rendered = "".join(
        traceback.format_exception(type(error.value), error.value, error.value.__traceback__)
    )
    _assert_secrets_absent(rendered)
    assert error.value.__context__ is None
    assert error.value.__cause__ is None


def test_timeout_and_connection_errors_have_no_httpx_context() -> None:
    base_transport, _requests, _ = _server()
    base_handler = base_transport.handler

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/fields"):
            raise httpx.ReadTimeout(f"timeout {TENANT_TOKEN}", request=request)
        return base_handler(request)

    with pytest.raises(FeishuTimeoutError) as timeout_error:
        provision_feishu_schema(
            _config(),
            transport=httpx.MockTransport(timeout_handler),
        )
    assert timeout_error.value.__context__ is None
    _assert_secrets_absent(
        "".join(
            traceback.format_exception(
                type(timeout_error.value),
                timeout_error.value,
                timeout_error.value.__traceback__,
            )
        )
    )

    base_transport, _requests, _ = _server()
    base_handler = base_transport.handler

    def connection_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/fields"):
            raise httpx.ConnectError(f"connection {TENANT_TOKEN}", request=request)
        return base_handler(request)

    with pytest.raises(Exception) as connection_error:
        provision_feishu_schema(
            _config(),
            transport=httpx.MockTransport(connection_handler),
        )
    assert type(connection_error.value).__name__ == "FeishuRequestError"
    assert connection_error.value.__context__ is None
    _assert_secrets_absent(str(connection_error.value))


def test_partial_creation_is_rerunnable_without_rollback() -> None:
    enabled = True

    def failure_response(_index: int, _request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"temporary {TENANT_TOKEN}")

    transport, requests, fields = _server(
        create_failure=failure_response,
        fail_at=2,
    )
    with pytest.raises(FeishuPartialProvisioningError) as error:
        provision_feishu_schema(_config(), transport=transport, sleep=lambda _: None)
    assert error.value.created_field_names == ("月份",)
    assert len(fields) == 2

    requests.clear()
    original_handler = transport.handler

    def rerun_handler(request: httpx.Request) -> httpx.Response:
        nonlocal enabled
        if enabled and request.method == "POST" and request.url.path.endswith("/fields"):
            enabled = False
        return original_handler(request)

    result = provision_feishu_schema(
        _config(),
        transport=httpx.MockTransport(rerun_handler),
        sleep=lambda _: None,
    )

    assert result.created_field_count == 20
    assert result.final_field_count == 22
    assert len(fields) == 22


def test_cli_default_is_live_dry_run_and_apply_is_only_create_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in tuple(os.environ):
        if name.startswith("APP_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_FEISHU_APP_ID", APP_ID)
    monkeypatch.setenv("APP_FEISHU_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("APP_FEISHU_BITABLE_APP_TOKEN", APP_TOKEN)
    monkeypatch.setenv("APP_FEISHU_BITABLE_TABLE_ID", TABLE_ID)
    monkeypatch.setenv("APP_FEISHU_BITABLE_VIEW_ID", VIEW_ID)

    transport, requests, _ = _server()
    monkeypatch.setattr(
        "src.cli.plan_feishu_schema",
        lambda config: plan_feishu_schema(config, transport=transport),
    )
    assert main(["provision-feishu-schema"]) == 0
    dry_run_output = capsys.readouterr().out
    assert "missing_field_count=21" in dry_run_output
    assert "created_field_count=0" in dry_run_output
    assert len(_field_requests(requests)) == 0
    _assert_secrets_absent(dry_run_output)

    requests.clear()
    monkeypatch.setattr(
        "src.cli.provision_feishu_schema",
        lambda config: provision_feishu_schema(
            config,
            transport=transport,
            sleep=lambda _: None,
            inspected_at=INSPECTED_AT,
            completed_at=COMPLETED_AT,
        ),
    )
    assert main(["provision-feishu-schema", "--apply"]) == 0
    apply_output = capsys.readouterr().out
    assert "created_field_count=21" in apply_output
    assert len(_field_requests(requests)) == 21
    _assert_secrets_absent(apply_output)


def test_build_plan_uses_field_names_not_response_order() -> None:
    desired = desired_feishu_fields()
    primary = FeishuBitableField(
        field_id="fld_primary",
        field_name="文本",
        type=1,
        ui_type="Text",
        is_primary=True,
        option_count=0,
        option_names=(),
    )
    compatible = FeishuBitableField(
        field_id="fld_score",
        field_name="趋势分",
        type=2,
        ui_type="Number",
        is_primary=False,
        option_count=0,
        option_names=(),
        formatter="0.00",
    )

    plan = build_feishu_schema_plan(
        [compatible, primary],
        apply_requested=False,
        desired_fields=desired,
    )

    assert plan.existing_primary_field_name == "文本"
    assert plan.compatible_field_count == 1
    assert "趋势分" not in plan.missing_field_names
