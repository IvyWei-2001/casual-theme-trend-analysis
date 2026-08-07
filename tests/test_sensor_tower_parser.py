"""Contract tests for the verified Sensor Tower market response sample."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from src.sensor_tower import parse_market_response, parse_market_response_file

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sensor_tower" / "market_response_sample.json"


def _fixture_payload() -> list[dict[str, Any]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_verified_sample_parses_all_three_records() -> None:
    records = parse_market_response_file(FIXTURE_PATH)

    assert len(records) == 3
    assert [record.app_id for record in records] == [1483058899, 1195621598, 553834731]
    assert [record.game_theme for record in records] == [
        "Fashion / Aesthetics / Hair",
        "Decoration",
        "Candy / Dessert",
    ]


def test_top_level_date_is_timezone_aware() -> None:
    record = parse_market_response(_fixture_payload())[0]

    assert record.date.tzinfo is not None
    assert record.date.utcoffset() is not None


def test_custom_tag_helpers_preserve_verified_values_and_parse_dates() -> None:
    tags = parse_market_response(_fixture_payload())[0].custom_tags

    assert tags.game_theme == "Fashion / Aesthetics / Hair"
    assert tags.game_genre == "Puzzle"
    assert tags.game_subgenre == "Match Swap"
    assert tags.game_product_model == "Casual"
    assert tags.game_art_style == "3D Cartoon"
    assert tags.game_setting == "Modern"
    assert tags.earliest_release_date == date(2019, 11, 19)
    assert tags.release_date_ww == date(2020, 11, 15)
    assert tags.publisher_country == "US"
    assert tags.is_unified == "true"


def test_missing_game_theme_returns_none() -> None:
    payload = _fixture_payload()
    del payload[0]["custom_tags"]["Game Theme"]

    record = parse_market_response(payload)[0]

    assert record.game_theme is None
    assert record.custom_tags.game_theme is None


def test_invalid_optional_tag_date_is_non_fatal_and_reported() -> None:
    payload = _fixture_payload()
    payload[0]["custom_tags"]["Release Date (WW)"] = "not-a-date"

    record = parse_market_response(payload)[0]

    assert record.custom_tags.release_date_ww is None
    assert record.custom_tags.optional_date_validation_errors == (
        "Release Date (WW) must be a valid date in YYYY/MM/DD format",
    )


def test_unknown_top_level_field_is_tolerated() -> None:
    payload = _fixture_payload()
    payload[0]["future_source_field"] = {"new": True}

    record = parse_market_response(payload)[0]

    assert record.model_extra == {"future_source_field": {"new": True}}


def test_invalid_top_level_date_raises_clear_validation_error() -> None:
    payload = _fixture_payload()
    payload[0]["date"] = "not-a-date"

    with pytest.raises(ValidationError, match="date"):
        parse_market_response(payload)


def test_unit_value_is_preserved_under_source_name() -> None:
    record = parse_market_response(_fixture_payload())[0]

    assert record.current_units_value == 3388898
    assert not hasattr(record, "downloads")


def test_revenue_value_is_preserved_without_currency_semantics() -> None:
    record = parse_market_response(_fixture_payload())[0]

    assert record.current_revenue_value == 451543999
    assert not hasattr(record, "revenue")
