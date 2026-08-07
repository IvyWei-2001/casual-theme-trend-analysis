"""Mock-only HTTP and request-orchestration tests for Sensor Tower."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx
import pytest

from src.sensor_tower.client import SensorTowerClient
from src.sensor_tower.errors import (
    SensorTowerHTTPError,
    SensorTowerMalformedResponseError,
    SensorTowerTimeoutError,
)
from src.sensor_tower.request import SensorTowerSelectionConfig, build_market_request
from src.sensor_tower.selection import fetch_and_select_market_records

TEST_TOKEN = "unit-test-token-do-not-log"


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
    assert captured[0].url.params["auth_token"] == TEST_TOKEN
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

    assert TEST_TOKEN not in caplog.text
    assert TEST_TOKEN not in client_repr


def test_non_2xx_is_a_sanitized_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"invalid token {TEST_TOKEN}")

    request = build_market_request(date(2026, 8, 7))
    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(SensorTowerHTTPError) as error:
            client.fetch_market_candidates(request)

    assert error.value.status_code == 401
    assert TEST_TOKEN not in str(error.value)


def test_malformed_json_is_a_sanitized_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    request = build_market_request(date(2026, 8, 7))
    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(SensorTowerMalformedResponseError) as error:
            client.fetch_market_candidates(request)

    assert TEST_TOKEN not in str(error.value)


def test_timeout_is_a_sanitized_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timeout {TEST_TOKEN}", request=request)

    request = build_market_request(date(2026, 8, 7))
    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(SensorTowerTimeoutError) as error:
            client.fetch_market_candidates(request)

    assert TEST_TOKEN not in str(error.value)


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
