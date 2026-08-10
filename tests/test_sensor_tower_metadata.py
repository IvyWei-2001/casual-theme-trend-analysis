"""Synthetic contract tests for Sensor Tower metadata enrichment."""

from __future__ import annotations

import traceback
from typing import Any

import httpx
import pytest

from src.sensor_tower import (
    DEFAULT_SENSOR_TOWER_METADATA_FIELDS,
    EnrichedMarketRecord,
    SensorTowerClient,
    SensorTowerMetadataBatchError,
    SensorTowerMetadataHTTPError,
    SensorTowerMetadataIntegrityError,
    SensorTowerMetadataRequestConfig,
    SensorTowerNormalizedMetadata,
    attach_metadata,
    build_metadata_request,
    fetch_metadata_for_market_records,
    parse_metadata_response,
    select_market_records,
)
from src.sensor_tower.dto import SensorTowerMarketRecord

TEST_TOKEN = "metadata-unit-test-token-do-not-log"


def _market_record(app_id: int | str, *, genre: str = "Puzzle") -> SensorTowerMarketRecord:
    return SensorTowerMarketRecord.model_validate(
        {
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
            "custom_tags": {"Game Genre": genre},
        }
    )


def _synthetic_metadata_app(app_id: str) -> dict[str, Any]:
    """Synthetic contract fixture; this is not a captured Sensor Tower export."""

    ios_app_id: str | int = int(app_id) if app_id.isdigit() else f"ios-{app_id}"
    return {
        "unified_app_id": app_id,
        "name": f"App {app_id}",
        "publisher": {"name": f"Publisher {app_id}"},
        "android_apps": [{"app_id": f"com.example.{app_id}"}],
        "itunes_apps": [{"app_id": ios_app_id}],
    }


def _metadata_config(**overrides: object) -> SensorTowerMetadataRequestConfig:
    values: dict[str, object] = {
        "max_retries": 0,
        "retry_delay_seconds": 0,
        "batch_delay_seconds": 0,
    }
    values.update(overrides)
    return SensorTowerMetadataRequestConfig.model_validate(values)


def _client(handler: httpx.MockTransport) -> SensorTowerClient:
    return SensorTowerClient(TEST_TOKEN, transport=handler)


def test_metadata_request_uses_exact_verified_contract() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"apps": [_synthetic_metadata_app("1")]})

    request = build_metadata_request(["1"])
    with _client(httpx.MockTransport(handler)) as client:
        client.fetch_metadata_batch(request)

    assert captured[0].url.path == "/v1/unified/apps"
    assert set(captured[0].url.params) == {"app_id_type", "app_ids", "fields", "auth_token"}
    assert captured[0].url.params["app_id_type"] == "unified"
    assert captured[0].url.params["app_ids"] == "1"
    assert captured[0].url.params["fields"] == ",".join(DEFAULT_SENSOR_TOWER_METADATA_FIELDS)
    assert captured[0].url.params["auth_token"] == TEST_TOKEN


def test_metadata_endpoint_is_configurable_and_separate_from_market_endpoint() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"apps": [_synthetic_metadata_app("1")]})

    metadata_config = _metadata_config(endpoint_path="/v1/configured-metadata")
    request = build_metadata_request(["1"], config=metadata_config)
    with SensorTowerClient(
        TEST_TOKEN,
        endpoint_path="/v1/configured-market",
        metadata_endpoint_path="/v1/configured-metadata",
        transport=httpx.MockTransport(handler),
    ) as client:
        client.fetch_metadata_batch(request)

    assert captured[0].url.path == "/v1/configured-metadata"


@pytest.mark.parametrize(
    ("record_count", "expected_calls"),
    [(0, 0), (1, 1), (50, 1), (51, 2), (1000, 20)],
)
def test_metadata_batch_count_and_order(record_count: int, expected_calls: int) -> None:
    captured_ids: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ids = request.url.params["app_ids"].split(",")
        captured_ids.append(ids)
        return httpx.Response(
            200,
            json={"apps": [_synthetic_metadata_app(app_id) for app_id in ids]},
        )

    selected = [_market_record(index + 1) for index in range(record_count)]
    config = _metadata_config(batch_size=50)
    with _client(httpx.MockTransport(handler)) as client:
        result = fetch_metadata_for_market_records(
            client,
            selected,
            config,
            sleep=lambda _: None,
        )

    assert len(captured_ids) == expected_calls
    assert result.requested_count == record_count
    assert [app_id for batch in captured_ids for app_id in batch] == [
        str(index + 1) for index in range(record_count)
    ]


def test_duplicate_selected_ids_are_requested_once_and_filtered_records_are_not_requested() -> None:
    captured_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_ids.extend(request.url.params["app_ids"].split(","))
        return httpx.Response(
            200,
            json={
                "apps": [
                    _synthetic_metadata_app(app_id)
                    for app_id in request.url.params["app_ids"].split(",")
                ]
            },
        )

    candidates = [
        _market_record(99, genre="Arcade"),
        _market_record(20),
        _market_record(10),
        _market_record(20),
    ]
    selected = select_market_records(
        candidates,
        allowed_genres=("Puzzle", "Tabletop"),
        final_top_n=1000,
        exclude_china_revenue_market=True,
    )
    with _client(httpx.MockTransport(handler)) as client:
        result = fetch_metadata_for_market_records(
            client,
            selected,
            _metadata_config(),
            sleep=lambda _: None,
        )

    assert captured_ids == ["20", "10"]
    assert result.requested_unified_app_ids == ("20", "10")


def test_opaque_ids_are_trimmed_deduplicated_and_sent_unchanged() -> None:
    request = build_metadata_request(
        [
            " synthetic-unified-app-002 ",
            "synthetic-unified-app-001",
            "synthetic-unified-app-002",
        ]
    )

    assert request.app_ids == (
        "synthetic-unified-app-002",
        "synthetic-unified-app-001",
    )
    assert request.to_query_params(TEST_TOKEN)["app_ids"] == (
        "synthetic-unified-app-002,synthetic-unified-app-001"
    )


def test_opaque_metadata_response_id_matches_requested_id() -> None:
    result = parse_metadata_response(
        {"apps": [_synthetic_metadata_app("synthetic-unified-app-001")]},
        ["synthetic-unified-app-001"],
    )

    assert tuple(result.metadata_by_unified_app_id) == ("synthetic-unified-app-001",)
    assert result.missing_unified_app_ids == ()


def test_metadata_fields_are_mapped_with_verified_publisher_precedence() -> None:
    payload = {
        "apps": [
            {
                "unified_app_id": "001",
                "name": "  Example App  ",
                "publisher": {"name": "Publisher fallback"},
                "android_publisher_ids": ["Android+Publisher"],
                "itunes_publisher_ids": [12345],
                "android_apps": [{"app_id": " com.example.app "}],
                "itunes_apps": [{"app_id": 987654321}],
                "future_field": {"ignored": True},
            }
        ]
    }

    result = parse_metadata_response(payload, [1])
    metadata = result.metadata_by_unified_app_id["1"]

    assert metadata == SensorTowerNormalizedMetadata(
        unified_app_id="1",
        name="Example App",
        publisher_display_name="Android Publisher",
        publisher_resolution_source="android_publisher_ids",
        android_app_id="com.example.app",
        ios_app_id="987654321",
    )


@pytest.mark.parametrize(
    ("app", "expected_publisher", "expected_source"),
    [
        (
            {"unified_app_id": 1, "publisher": {"name": "Publisher"}},
            "Publisher",
            "publisher_name",
        ),
        (
            {"unified_app_id": 1, "itunes_publisher_ids": [123]},
            "123",
            "itunes_publisher_ids",
        ),
        (
            {"unified_app_id": 1},
            None,
            "unavailable",
        ),
    ],
)
def test_publisher_fallbacks_and_missing_name(
    app: dict[str, Any],
    expected_publisher: str | None,
    expected_source: str,
) -> None:
    result = parse_metadata_response({"apps": [app]}, [1])
    metadata = result.metadata_by_unified_app_id["1"]

    assert metadata.publisher_display_name == expected_publisher
    assert metadata.publisher_resolution_source == expected_source
    assert metadata.name is None


def test_missing_metadata_is_recorded_but_not_fatal_and_absent_apps_is_empty() -> None:
    result = parse_metadata_response({"apps": []}, [1, 2])
    assert result.metadata_by_unified_app_id == {}
    assert result.missing_unified_app_ids == ("1", "2")
    assert result.requested_count == 2
    assert result.returned_count == 0

    absent_apps = parse_metadata_response({}, [1])
    assert absent_apps.missing_unified_app_ids == ("1",)


def test_duplicate_and_unrequested_response_ids_fail_integrity_validation() -> None:
    duplicate = {"apps": [_synthetic_metadata_app("1"), _synthetic_metadata_app("1")]}
    with pytest.raises(SensorTowerMetadataIntegrityError, match="duplicate"):
        parse_metadata_response(duplicate, [1])

    with pytest.raises(SensorTowerMetadataIntegrityError, match="unrequested"):
        parse_metadata_response({"apps": [_synthetic_metadata_app("2")]}, [1])

    opaque_duplicate = {
        "apps": [
            _synthetic_metadata_app("synthetic-unified-app-001"),
            _synthetic_metadata_app("synthetic-unified-app-001"),
        ]
    }
    with pytest.raises(SensorTowerMetadataIntegrityError, match="duplicate"):
        parse_metadata_response(opaque_duplicate, ["synthetic-unified-app-001"])

    with pytest.raises(SensorTowerMetadataIntegrityError, match="unrequested"):
        parse_metadata_response(
            {"apps": [_synthetic_metadata_app("synthetic-unified-app-002")]},
            ["synthetic-unified-app-001"],
        )


@pytest.mark.parametrize("apps_value", ["not-an-array", {"id": 1}])
def test_malformed_apps_envelope_fails_clearly(apps_value: object) -> None:
    with pytest.raises(Exception, match="apps field"):
        parse_metadata_response({"apps": apps_value}, [1])


def test_retry_pacing_and_no_final_batch_delay() -> None:
    attempts = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"apps": [_synthetic_metadata_app("1")]})

    config = _metadata_config(max_retries=2, retry_delay_seconds=1.5, batch_delay_seconds=0.3)
    with _client(httpx.MockTransport(handler)) as client:
        fetch_metadata_for_market_records(
            client,
            [_market_record(1)],
            config,
            sleep=sleeps.append,
        )

    assert attempts == 2
    assert sleeps == [1.5]


def test_batch_delay_occurs_only_between_batches() -> None:
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "apps": [
                    _synthetic_metadata_app(app_id)
                    for app_id in request.url.params["app_ids"].split(",")
                ]
            },
        )

    with _client(httpx.MockTransport(handler)) as client:
        fetch_metadata_for_market_records(
            client,
            [_market_record(index) for index in range(1, 52)],
            _metadata_config(batch_size=50, batch_delay_seconds=0.3),
            sleep=sleeps.append,
        )

    assert sleeps == [0.3]


def test_exhausted_retries_raise_sanitized_batch_error_without_httpx_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"invalid token {TEST_TOKEN}")

    config = _metadata_config(max_retries=2)
    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(SensorTowerMetadataBatchError) as error:
            fetch_metadata_for_market_records(
                client,
                [_market_record(1)],
                config,
                sleep=lambda _: None,
            )

    assert error.value.batch_number == 1
    assert error.value.attempts == 3
    assert TEST_TOKEN not in str(error.value)
    assert TEST_TOKEN not in "".join(
        traceback.format_exception(type(error.value), error.value, error.value.__traceback__)
    )
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_attach_metadata_preserves_order_duplicates_and_missing_records() -> None:
    selected = [_market_record(2), _market_record(1), _market_record(2), _market_record(3)]
    before = [record.model_dump() for record in selected]
    result = parse_metadata_response(
        {"apps": [_synthetic_metadata_app("1"), _synthetic_metadata_app("2")]},
        [2, 1, 3],
    )

    enriched = attach_metadata(selected, result)

    assert isinstance(enriched[0], EnrichedMarketRecord)
    assert [item.market_record.app_id for item in enriched] == ["2", "1", "2", "3"]
    assert [item.metadata is None for item in enriched] == [False, False, False, True]
    assert enriched[0].metadata == enriched[2].metadata
    assert [record.model_dump() for record in selected] == before


def test_metadata_http_error_is_typed_and_token_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=f"failed {TEST_TOKEN}")

    request = build_metadata_request([1])
    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(SensorTowerMetadataHTTPError):
            client.fetch_metadata_batch(request)

    assert TEST_TOKEN not in caplog.text
    assert TEST_TOKEN not in repr(client)
