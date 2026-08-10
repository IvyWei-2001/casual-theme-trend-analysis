"""Mock-only HTTP and request-orchestration tests for Sensor Tower."""

from __future__ import annotations

import logging
import traceback
from datetime import date
from typing import Any

import httpx
import pytest

from src.config import AppConfig
from src.sensor_tower.client import SensorTowerClient
from src.sensor_tower.errors import (
    SensorTowerHTTPError,
    SensorTowerMalformedResponseError,
    SensorTowerRequestError,
    SensorTowerTimeoutError,
)
from src.sensor_tower.request import SensorTowerSelectionConfig, build_market_request
from src.sensor_tower.selection import fetch_and_select_market_records

TEST_TOKEN = "unit-test-token-do-not-log"


def _assert_secret_absent(text: str) -> None:
    if TEST_TOKEN in text:
        raise AssertionError("sanitized diagnostics contain the configured token")


def _assert_token_matches(value: str) -> None:
    if value != TEST_TOKEN:
        raise AssertionError("configured token was not sent to the mocked endpoint")


def _formatted_error(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def _market_row(
    app_id: int = 1,
    *,
    genre: str = "Puzzle",
    country_by_revenue: str | None = None,
) -> dict[str, Any]:
    tags: dict[str, str] = {"Game Genre": genre}
    if country_by_revenue is not None:
        tags["Most Popular Country by Revenue"] = country_by_revenue
    return {
        "app_id": app_id,
        "country": None,
        "date": "2026-08-07T00:00:00Z",
        "current_units_value": 1,
        "units_absolute": 1,
        "comparison_units_value": 1,
        "units_delta": 0,
        "units_transformed_delta": 0.0,
        "current_revenue_value": 1,
        "revenue_absolute": 1,
        "comparison_revenue_value": 1,
        "revenue_delta": 0,
        "revenue_transformed_delta": 0.0,
        "absolute": 1,
        "delta": 0,
        "transformed_delta": 0.0,
        "custom_tags": tags,
    }


def _client(handler: httpx.MockTransport) -> SensorTowerClient:
    return SensorTowerClient(
        TEST_TOKEN,
        base_url="https://api.sensortower.com",
        transport=handler,
    )


def test_auth_token_reaches_mocked_endpoint_and_verified_query_is_sent() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=[_market_row()])

    request = build_market_request(date(2026, 8, 7))
    with _client(httpx.MockTransport(handler)) as client:
        records = client.fetch_market_candidates(request)

    assert len(records) == 1
    assert captured[0].url.path == (
        "/v1/unified/sales_report_estimates_comparison_attributes"
    )
    _assert_token_matches(captured[0].url.params["auth_token"])
    assert captured[0].url.params["limit"] == "1200"
    assert captured[0].url.params["date"] == "2026-08-07"
    assert captured[0].url.params["end_date"] == "2026-08-07"
    assert "start_date" not in captured[0].url.params
    assert "final_top_n" not in captured[0].url.params


def test_token_is_absent_from_logs_and_client_repr(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    request = build_market_request(date(2026, 8, 7))
    with caplog.at_level(logging.DEBUG):
        with _client(httpx.MockTransport(handler)) as client:
            client.fetch_market_candidates(request)
            client_repr = repr(client)

    _assert_secret_absent(caplog.text)
    _assert_secret_absent(client_repr)


def test_non_2xx_is_a_sanitized_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"invalid token {TEST_TOKEN}")

    request = build_market_request(date(2026, 8, 7))
    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(SensorTowerHTTPError) as error:
            client.fetch_market_candidates(request)

    assert error.value.status_code == 401
    _assert_secret_absent(str(error.value))


def test_malformed_json_is_a_sanitized_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    request = build_market_request(date(2026, 8, 7))
    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(SensorTowerMalformedResponseError) as error:
            client.fetch_market_candidates(request)

    _assert_secret_absent(str(error.value))


def test_timeout_is_a_sanitized_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timeout {TEST_TOKEN}", request=request)

    request = build_market_request(date(2026, 8, 7))
    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(SensorTowerTimeoutError) as error:
            client.fetch_market_candidates(request)

    _assert_secret_absent(str(error.value))


def test_timeout_error_has_no_httpx_context_or_secret_in_traceback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timeout {TEST_TOKEN}", request=request)

    request = build_market_request(date(2026, 8, 7))
    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(SensorTowerTimeoutError) as error:
            client.fetch_market_candidates(request)

    assert "timed out" in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    _assert_secret_absent(str(error.value))
    _assert_secret_absent(_formatted_error(error.value))


def test_generic_request_error_is_distinct_and_has_no_httpx_context_or_secret() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"network failure {TEST_TOKEN}", request=request)

    request = build_market_request(date(2026, 8, 7))
    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(SensorTowerRequestError) as error:
            client.fetch_market_candidates(request)

    assert type(error.value) is SensorTowerRequestError
    assert "market request failed" in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    _assert_secret_absent(str(error.value))
    _assert_secret_absent(_formatted_error(error.value))


def test_client_uses_injected_endpoint_path() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=[_market_row()])

    endpoint_path = "/v1/configured-market"
    request = build_market_request(date(2026, 8, 7), endpoint_path=endpoint_path)
    with SensorTowerClient(
        TEST_TOKEN,
        base_url="https://api.sensortower.com",
        endpoint_path=endpoint_path,
        transport=httpx.MockTransport(handler),
    ) as client:
        client.fetch_market_candidates(request)

    assert captured[0].url.path == endpoint_path


def test_app_config_builds_client_request_and_selection_from_one_boundary() -> None:
    captured: list[httpx.Request] = []
    config = AppConfig(
        sensor_tower_api_url="https://api.sensortower.com",
        sensor_tower_auth_token=TEST_TOKEN,
        sensor_tower_endpoint_path="/v1/configured-market",
        sensor_tower_category=7001,
        sensor_tower_country="US",
        sensor_tower_device_type="total",
        sensor_tower_custom_tags_mode="include_unified_apps",
        sensor_tower_data_model="DM_TEST",
        sensor_tower_filter_field_name="Game Genre",
        sensor_tower_filter_global=False,
        sensor_tower_filter_exclude=True,
        sensor_tower_api_limit=4,
        sensor_tower_final_top_n=1,
        sensor_tower_allowed_genres=("Puzzle",),
        sensor_tower_exclude_china_revenue_market=False,
        sensor_tower_scope_name="configured_scope",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=[_market_row(1, genre="Puzzle"), _market_row(2, genre="Arcade")],
        )

    request = config.build_sensor_tower_market_request(date(2026, 8, 7))
    selection_config = config.sensor_tower_selection_config
    assert request.selection_config() == selection_config
    assert request.request_config() == config.sensor_tower_request_config

    with SensorTowerClient.from_config(
        config.sensor_tower_client_config,
        transport=httpx.MockTransport(handler),
    ) as client:
        selected = fetch_and_select_market_records(client, request)

    assert [record.app_id for record in selected] == [1]
    assert captured[0].url.path == config.sensor_tower_endpoint_path
    assert captured[0].url.params["category"] == str(config.sensor_tower_category)
    assert captured[0].url.params["country"] == config.sensor_tower_country
    assert captured[0].url.params["limit"] == str(config.sensor_tower_api_limit)


def test_fetch_and_select_orchestrates_mock_http_then_local_filtering() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                _market_row(1, genre="Arcade"),
                _market_row(2, genre="pUzZle"),
            ],
        )

    request = build_market_request(
        date(2026, 8, 7),
        api_limit=1200,
        final_top_n=1,
    )
    selection_config = SensorTowerSelectionConfig(
        api_limit=1200,
        final_top_n=1,
        allowed_genres=("Puzzle", "Tabletop"),
        exclude_china_revenue_market=True,
        scope_name="casual_puzzle_tabletop",
    )
    with _client(httpx.MockTransport(handler)) as client:
        selected = fetch_and_select_market_records(client, request, selection_config)

    assert [record.app_id for record in selected] == [2]
