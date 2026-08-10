"""Tests for the verified Sensor Tower market request boundary."""

from __future__ import annotations

import json
from datetime import date

import pytest
from pydantic import ValidationError

from src.sensor_tower.request import (
    SENSOR_TOWER_MARKET_ENDPOINT_PATH,
    SensorTowerCustomFieldsFilter,
    SensorTowerMarketRequest,
    build_market_request,
)


def test_verified_query_parameters_and_endpoint_contract() -> None:
    request = build_market_request(date(2026, 8, 7))
    query = request.to_query_params("test-token")

    assert SENSOR_TOWER_MARKET_ENDPOINT_PATH == (
        "/v1/unified/sales_report_estimates_comparison_attributes"
    )
    assert query == {
        "comparison_attribute": "absolute",
        "time_range": "day",
        "measure": "units",
        "device_type": "total",
        "category": 7012,
        "country": "WW",
        "date": "2026-08-07",
        "end_date": "2026-08-07",
        "limit": 1200,
        "custom_tags_mode": "include_unified_apps",
        "data_model": "DM_2025_Q2",
        "auth_token": "test-token",
        "custom_fields_filter_id": (
            '{"custom_fields":[{"name":"Game Genre","values":["Puzzle","Tabletop"],'
            '"global":true,"exclude":false}]}'
        ),
    }
    assert "start_date" not in query
    assert "final_top_n" not in query


def test_custom_fields_filter_decodes_to_the_verified_json() -> None:
    request = build_market_request(date(2026, 8, 7))

    assert json.loads(request.custom_fields_filter_id()) == {
        "custom_fields": [
            {
                "exclude": False,
                "global": True,
                "name": "Game Genre",
                "values": ["Puzzle", "Tabletop"],
            }
        ]
    }


def test_category_country_and_data_model_are_configurable() -> None:
    request = SensorTowerMarketRequest(
        category=7001,
        country="US",
        data_model="DM_TEST",
        date=date(2026, 8, 1),
        end_date=date(2026, 8, 2),
    )

    query = request.to_query_params("test-token")

    assert query["category"] == 7001
    assert query["country"] == "US"
    assert query["data_model"] == "DM_TEST"
    assert query["date"] == "2026-08-01"
    assert query["end_date"] == "2026-08-02"


def test_approved_request_scope_drives_the_outbound_filter() -> None:
    request = build_market_request(
        date(2026, 8, 7),
        endpoint_path="/v1/configured-market",
        category=7001,
        country="US",
        device_type="phone",
        custom_tags_mode="include_unified_apps",
        data_model="DM_TEST",
        filter_field_name="Game Genre",
        filter_global=True,
        filter_exclude=False,
        allowed_genres=("Puzzle", "Tabletop"),
    )

    assert request.endpoint_path == "/v1/configured-market"
    assert request.selection_config().allowed_genres == ("Puzzle", "Tabletop")
    assert json.loads(request.custom_fields_filter_id()) == {
        "custom_fields": [
            {
                "exclude": False,
                "global": True,
                "name": "Game Genre",
                "values": ["Puzzle", "Tabletop"],
            }
        ]
    }


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        (
            "filter_field_name",
            "Game Theme",
            "filter_field_name='Game Genre' only",
        ),
        ("filter_global", False, "filter_global=true only"),
        ("filter_exclude", True, "filter_exclude=false only"),
        ("allowed_genres", ("Arcade",), "allowed_genres"),
    ],
)
def test_unsupported_filter_scope_values_are_rejected(
    field_name: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        build_market_request(date(2026, 8, 7), **{field_name: value})


def test_explicit_custom_filter_must_match_configured_genres() -> None:
    inconsistent_filter = SensorTowerCustomFieldsFilter.for_allowed_genres(("Arcade",))

    with pytest.raises(ValidationError, match="custom_fields_filter must match"):
        SensorTowerMarketRequest(
            date=date(2026, 8, 7),
            end_date=date(2026, 8, 7),
            allowed_genres=("Puzzle", "Tabletop"),
            custom_fields_filter=inconsistent_filter,
        )


@pytest.mark.parametrize("endpoint_path", ["", "v1/market", "/v1/market?country=WW"])
def test_endpoint_path_is_validated(endpoint_path: str) -> None:
    with pytest.raises(ValidationError):
        build_market_request(date(2026, 8, 7), endpoint_path=endpoint_path)


@pytest.mark.parametrize(
    "field_name",
    ["country", "device_type", "custom_tags_mode", "data_model", "filter_field_name"],
)
def test_request_text_boundary_fields_are_nonempty(field_name: str) -> None:
    with pytest.raises(ValidationError):
        build_market_request(date(2026, 8, 7), **{field_name: " "})


def test_request_category_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        build_market_request(date(2026, 8, 7), category=0)


def test_invalid_date_range_fails_before_request_construction() -> None:
    with pytest.raises(ValidationError, match="date must be less than or equal to end_date"):
        build_market_request(
            date(2026, 8, 8),
            end_date=date(2026, 8, 7),
        )


def test_api_limit_cannot_be_smaller_than_final_top_n() -> None:
    with pytest.raises(ValidationError, match="api_limit must be greater than or equal"):
        build_market_request(
            date(2026, 8, 7),
            api_limit=999,
            final_top_n=1000,
        )


def test_nonempty_genres_and_custom_field_values_are_validated() -> None:
    with pytest.raises(ValidationError, match="allowed genre names must be non-empty"):
        build_market_request(date(2026, 8, 7), allowed_genres=[" "])
