"""Mock-only tests for the read-only Feishu field inspection boundary."""

from __future__ import annotations

import logging
import os
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from src.__main__ import main
from src.config import AppConfig
from src.feishu.client import FeishuClient
from src.feishu.errors import (
    FeishuAPIError,
    FeishuAuthenticationError,
    FeishuConfigurationError,
    FeishuFieldIntegrityError,
    FeishuHTTPError,
    FeishuMalformedResponseError,
    FeishuRequestError,
    FeishuTimeoutError,
)
from src.feishu.inspection import (
    format_feishu_inspection_summary,
    inspect_feishu,
)
from src.feishu.models import FeishuClientConfig

APP_ID = "cli_test_app_id"
APP_SECRET = "cli_test_app_secret_do_not_log"
APP_TOKEN = "cli_test_app_token_1234"
TABLE_ID = "tbl_cli_test"
VIEW_ID = "vew_cli_test"
TENANT_TOKEN = "tenant_access_token_do_not_log"
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


def _field_page(*, second_page: bool = False) -> dict[str, Any]:
    if not second_page:
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "items": [
                    {
                        "field_id": "fld_primary",
                        "field_name": "Theme",
                        "type": 1,
                        "ui_type": "Text",
                        "is_primary": True,
                        "unknown_field": {"must": "be ignored"},
                    }
                ],
                "has_more": True,
                "page_token": "next-page-token",
            },
        }
    return {
        "code": 0,
        "msg": "success",
        "data": {
            "items": [
                {
                    "field_id": "fld_select",
                    "field_name": "Status",
                    "type": 4,
                    "ui_type": "SingleSelect",
                    "is_primary": False,
                    "property": {
                        "options": [
                            {"id": "opt-1", "name": "New", "color": 1},
                            {"id": "opt-2", "name": "Live", "color": 2},
                        ],
                        "unknown_property": "ignored",
                    },
                }
            ],
            "has_more": False,
        },
    }


def _client(handler: httpx.MockTransport) -> FeishuClient:
    return FeishuClient.from_config(_config().feishu_client_config, transport=handler)


def _assert_secrets_absent(value: str) -> None:
    assert APP_SECRET not in value
    assert TENANT_TOKEN not in value
    assert APP_TOKEN not in value


def _formatted_error(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def _direct_feishu_client_config(*, base_url: str) -> FeishuClientConfig:
    return FeishuClientConfig(
        base_url=base_url,
        app_id=APP_ID,
        app_secret=APP_SECRET,
        bitable_app_token=APP_TOKEN,
        bitable_table_id=TABLE_ID,
        bitable_view_id=VIEW_ID,
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://synthetic-url-user:synthetic-url-password@open.feishu.cn",
        "https://synthetic-url-user@open.feishu.cn",
    ],
)
def test_authenticated_feishu_base_urls_are_rejected_by_both_configs(
    base_url: str,
) -> None:
    with pytest.raises(ValidationError):
        AppConfig(feishu_api_base_url=base_url)
    with pytest.raises(ValidationError):
        _direct_feishu_client_config(base_url=base_url)


def test_valid_feishu_base_url_is_accepted_by_both_configs() -> None:
    base_url = "https://open.feishu.cn"

    assert AppConfig(feishu_api_base_url=base_url).feishu_api_base_url == base_url
    assert _direct_feishu_client_config(base_url=base_url).base_url == base_url


def test_app_config_authenticated_url_errors_hide_url_userinfo(
    caplog: pytest.LogCaptureFixture,
) -> None:
    username = "synthetic-url-user"
    password = "synthetic-url-password"
    base_url = f"https://{username}:{password}@open.feishu.cn"

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ValidationError) as error:
            AppConfig(feishu_api_base_url=base_url)

    rendered_errors = (
        str(error.value),
        repr(error.value),
        _formatted_error(error.value),
        caplog.text,
    )
    for rendered in rendered_errors:
        assert username not in rendered
        assert password not in rendered


def test_feishu_client_config_authenticated_url_errors_hide_url_userinfo() -> None:
    username = "synthetic-url-user"
    password = "synthetic-url-password"
    base_url = f"https://{username}:{password}@open.feishu.cn"

    with pytest.raises(ValidationError) as error:
        _direct_feishu_client_config(base_url=base_url)

    rendered_errors = (
        str(error.value),
        repr(error.value),
        _formatted_error(error.value),
    )
    for rendered in rendered_errors:
        assert username not in rendered
        assert password not in rendered


def test_feishu_client_repr_remains_credential_safe_for_valid_base_url() -> None:
    config = _direct_feishu_client_config(base_url="https://open.feishu.cn")

    with FeishuClient.from_config(
        config,
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    ) as client:
        rendered = repr(client)

    assert "https://open.feishu.cn" in rendered
    _assert_secrets_absent(rendered)


def test_authentication_and_paginated_field_gets_use_verified_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            assert request.url.path == "/open-apis/auth/v3/tenant_access_token/internal"
            assert request.read() == (
                b'{"app_id":"cli_test_app_id",'
                b'"app_secret":"cli_test_app_secret_do_not_log"}'
            )
            return httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": TENANT_TOKEN, "expire": 7200},
            )
        assert request.method == "GET"
        assert request.url.path == (
            "/open-apis/bitable/v1/apps/cli_test_app_token_1234/"
            "tables/tbl_cli_test/fields"
        )
        assert request.headers["Authorization"] == f"Bearer {TENANT_TOKEN}"
        if request.url.params.get("page_token") == "next-page-token":
            return httpx.Response(200, json=_field_page(second_page=True))
        return httpx.Response(200, json=_field_page())

    with _client(httpx.MockTransport(handler)) as client:
        access_token = client.get_tenant_access_token()
        fields = client.list_fields(
            app_token=APP_TOKEN,
            table_id=TABLE_ID,
            view_id=VIEW_ID,
        )

    assert access_token.tenant_access_token.get_secret_value() == TENANT_TOKEN
    assert access_token.expire == 7200
    assert [field.field_id for field in fields] == ["fld_primary", "fld_select"]
    assert fields[1].option_count == 2
    assert fields[1].option_names == ("New", "Live")
    assert fields[0].is_primary is True
    assert fields[1].is_primary is False
    assert [request.method for request in requests] == ["POST", "GET", "GET"]
    assert requests[1].url.params["page_size"] == "100"
    assert requests[1].url.params["view_id"] == VIEW_ID
    assert requests[2].url.params["page_token"] == "next-page-token"


def test_view_id_is_omitted_when_not_configured() -> None:
    config = AppConfig(
        feishu_app_id=APP_ID,
        feishu_app_secret=APP_SECRET,
        feishu_bitable_app_token=APP_TOKEN,
        feishu_bitable_table_id=TABLE_ID,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"code": 0, "tenant_access_token": TENANT_TOKEN})
        assert "view_id" not in request.url.params
        return httpx.Response(200, json=_field_page(second_page=True))

    with FeishuClient.from_config(
        config.feishu_client_config,
        transport=httpx.MockTransport(handler),
    ) as client:
        client.get_tenant_access_token()
        fields = client.list_fields(app_token=APP_TOKEN, table_id=TABLE_ID)

    assert len(fields) == 1


def test_inspection_result_reports_duplicate_names_and_masks_app_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"code": 0, "tenant_access_token": TENANT_TOKEN})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [
                        {
                            "field_id": "fld_one",
                            "field_name": "Duplicate",
                            "type": 1,
                            "ui_type": "Text",
                        },
                        {
                            "field_id": "fld_two",
                            "field_name": "Duplicate",
                            "type": 2,
                            "ui_type": "Number",
                        },
                    ],
                    "has_more": False,
                },
            },
        )

    with caplog.at_level(logging.WARNING):
        result = inspect_feishu(
            _config(),
            transport=httpx.MockTransport(handler),
            inspected_at=INSPECTED_AT,
        )

    assert result.field_count == 2
    assert result.primary_field_count == 0
    assert result.duplicate_field_names == ("Duplicate",)
    assert result.app_token_suffix == "1234"
    assert result.inspected_at == INSPECTED_AT
    assert "duplicate field names" in caplog.text
    assert APP_TOKEN not in repr(result)
    assert TENANT_TOKEN not in repr(result)
    assert format_feishu_inspection_summary(result).count("field_name=Duplicate") == 2


def test_authentication_errors_are_typed_and_secret_safe() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"bad credentials {APP_SECRET} {TENANT_TOKEN}")

    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(FeishuAuthenticationError) as error:
            client.get_tenant_access_token()

    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    _assert_secrets_absent(str(error.value))
    _assert_secrets_absent(_formatted_error(error.value))
    _assert_secrets_absent(repr(client))


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        (httpx.Response(200, json={"code": 123, "msg": "contains secret"}), FeishuAPIError),
        (httpx.Response(200, content=b"not-json"), FeishuMalformedResponseError),
        (
            httpx.Response(200, json={"code": 0, "data": {"items": "bad"}}),
            FeishuMalformedResponseError,
        ),
    ],
)
def test_field_response_failures_are_typed(
    response: httpx.Response,
    error_type: type[Exception],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"code": 0, "tenant_access_token": TENANT_TOKEN})
        return response

    with _client(httpx.MockTransport(handler)) as client:
        client.get_tenant_access_token()
        with pytest.raises(error_type):
            client.list_fields(app_token=APP_TOKEN, table_id=TABLE_ID)


def test_non_2xx_field_response_is_sanitized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"code": 0, "tenant_access_token": TENANT_TOKEN})
        return httpx.Response(403, text=f"forbidden {APP_TOKEN} {TENANT_TOKEN}")

    with _client(httpx.MockTransport(handler)) as client:
        client.get_tenant_access_token()
        with pytest.raises(FeishuHTTPError) as error:
            client.list_fields(app_token=APP_TOKEN, table_id=TABLE_ID)

    assert error.value.status_code == 403
    _assert_secrets_absent(str(error.value))


def test_timeout_and_connection_errors_have_no_httpx_context() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"code": 0, "tenant_access_token": TENANT_TOKEN})
        raise httpx.ReadTimeout(f"timeout {TENANT_TOKEN}", request=request)

    with _client(httpx.MockTransport(timeout_handler)) as client:
        client.get_tenant_access_token()
        with pytest.raises(FeishuTimeoutError) as error:
            client.list_fields(app_token=APP_TOKEN, table_id=TABLE_ID)

    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    _assert_secrets_absent(_formatted_error(error.value))

    def connection_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"code": 0, "tenant_access_token": TENANT_TOKEN})
        raise httpx.ConnectError(f"connection {TENANT_TOKEN}", request=request)

    with _client(httpx.MockTransport(connection_handler)) as client:
        client.get_tenant_access_token()
        with pytest.raises(FeishuRequestError) as connection_error:
            client.list_fields(app_token=APP_TOKEN, table_id=TABLE_ID)

    assert type(connection_error.value) is FeishuRequestError
    _assert_secrets_absent(_formatted_error(connection_error.value))


def test_duplicate_field_ids_fail_before_returning_partial_audit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"code": 0, "tenant_access_token": TENANT_TOKEN})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "items": [
                        {"field_id": "fld_duplicate", "field_name": "One", "type": 1},
                        {"field_id": "fld_duplicate", "field_name": "Two", "type": 2},
                    ],
                    "has_more": False,
                },
            },
        )

    with _client(httpx.MockTransport(handler)) as client:
        client.get_tenant_access_token()
        with pytest.raises(FeishuFieldIntegrityError):
            client.list_fields(app_token=APP_TOKEN, table_id=TABLE_ID)


@pytest.mark.parametrize(
    "overrides",
    [
        {"feishu_api_base_url": "http://open.feishu.cn"},
        {"feishu_bitable_table_id": "table_without_prefix"},
        {"feishu_bitable_view_id": "view_without_prefix"},
        {"feishu_timeout_seconds": 0},
        {"feishu_timeout_seconds": float("inf")},
    ],
)
def test_feishu_configuration_rejects_unsafe_structure(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        AppConfig.model_validate(overrides)


def test_empty_optional_feishu_credentials_are_allowed_for_plan_only() -> None:
    config = AppConfig(
        feishu_app_id="",
        feishu_app_secret="",
        feishu_bitable_app_token="",
        feishu_bitable_table_id="",
        feishu_bitable_view_id="",
    )

    assert config.feishu_app_id is None
    assert config.feishu_app_secret is None
    assert config.feishu_bitable_app_token is None
    assert config.feishu_bitable_table_id is None
    assert config.feishu_bitable_view_id is None


def test_real_feishu_configuration_requires_all_values_without_exposing_secrets() -> None:
    config = AppConfig()
    with pytest.raises(FeishuConfigurationError) as error:
        _ = config.feishu_client_config
    assert "APP_FEISHU_APP_ID" in str(error.value)
    _assert_secrets_absent(repr(config))


def test_cli_plan_only_does_not_use_network_database_or_files(
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
    exit_code = main(["inspect-feishu", "--plan-only"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "network=disabled" in captured.out
    assert "database=disabled" in captured.out
    assert "file_writes=disabled" in captured.out
    assert APP_SECRET not in captured.out
    assert not (tmp_path / "data").exists()


def test_cli_real_inspection_prints_safe_field_audit_without_writes(
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

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"code": 0, "tenant_access_token": TENANT_TOKEN})
        return httpx.Response(
            200,
            json=_field_page(
                second_page=request.url.params.get("page_token") == "next-page-token"
            ),
        )

    original_inspect = inspect_feishu

    def mocked_inspect(config: AppConfig) -> object:
        return original_inspect(
            config,
            transport=httpx.MockTransport(handler),
            inspected_at=INSPECTED_AT,
        )

    monkeypatch.setattr("src.cli.inspect_feishu", mocked_inspect)
    exit_code = main(["inspect-feishu"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "field_name=Theme" in captured.out
    assert "type=1" in captured.out
    assert APP_SECRET not in captured.out
    assert TENANT_TOKEN not in captured.out
    assert APP_TOKEN not in captured.out
    assert [request.method for request in requests] == ["POST", "GET", "GET"]
    assert all(request.method == "GET" for request in requests[1:])
    assert not (tmp_path / "data").exists()
