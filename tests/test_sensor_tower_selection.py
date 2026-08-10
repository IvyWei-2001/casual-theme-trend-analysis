"""Tests for local Sensor Tower eligibility and tag normalization."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from src.sensor_tower.dto import SensorTowerMarketRecord
from src.sensor_tower.errors import (
    NoEligibleMarketRecordsError,
    SensorTowerSelectionConfigurationError,
)
from src.sensor_tower.parser import parse_market_response
from src.sensor_tower.request import SensorTowerSelectionConfig, build_market_request
from src.sensor_tower.selection import fetch_and_select_market_records, select_market_records


def _record(
    app_id: int,
    *,
    genre: str | None = "Puzzle",
    revenue_country: str | None = None,
) -> SensorTowerMarketRecord:
    tags: dict[str, str] = {}
    if genre is not None:
        tags["Game Genre"] = genre
    if revenue_country is not None:
        tags["Most Popular Country by Revenue"] = revenue_country

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
            "custom_tags": tags,
        }
    )


def _candidate_records(
    eligible_count: int,
    total_count: int = 1200,
) -> list[SensorTowerMarketRecord]:
    return [
        _record(index, genre="Puzzle" if index < eligible_count else "Arcade")
        for index in range(total_count)
    ]


def test_1200_candidates_with_1105_eligible_return_exactly_1000() -> None:
    records = _candidate_records(1105)

    selected = select_market_records(
        records,
        allowed_genres=("Puzzle", "Tabletop"),
        final_top_n=1000,
        exclude_china_revenue_market=True,
    )

    assert len(selected) == 1000
    assert [record.app_id for record in selected] == list(range(1000))


def test_1200_candidates_with_998_eligible_return_all_998_and_warn(
    caplog: pytest.LogCaptureFixture,
) -> None:
    records = _candidate_records(998)

    with caplog.at_level("WARNING"):
        selected = select_market_records(
            records,
            allowed_genres=("Puzzle", "Tabletop"),
            final_top_n=1000,
            exclude_china_revenue_market=True,
        )

    assert len(selected) == 998
    assert "candidates=1200" in caplog.text
    assert "selected=998" in caplog.text


def test_filtering_happens_before_truncation_and_preserves_source_order() -> None:
    records = [
        _record(10, genre="Arcade"),
        _record(20, genre="Puzzle"),
        _record(30, genre="Tabletop"),
        _record(40, genre="Arcade"),
        _record(50, genre="Puzzle"),
    ]

    selected = select_market_records(
        records,
        allowed_genres=("Puzzle", "Tabletop"),
        final_top_n=3,
        exclude_china_revenue_market=True,
    )

    assert [record.app_id for record in selected] == [20, 30, 50]


def test_missing_and_non_allowed_genres_are_excluded() -> None:
    records = [_record(1, genre=None), _record(2, genre="Arcade"), _record(3)]

    selected = select_market_records(
        records,
        allowed_genres=("Puzzle", "Tabletop"),
        final_top_n=1000,
        exclude_china_revenue_market=True,
    )

    assert [record.app_id for record in selected] == [3]


def test_genre_matching_is_case_insensitive() -> None:
    records = [_record(1, genre="pUzZle"), _record(2, genre="TABLETOP")]

    selected = select_market_records(
        records,
        allowed_genres=("Puzzle", "Tabletop"),
        final_top_n=1000,
        exclude_china_revenue_market=True,
    )

    assert [record.app_id for record in selected] == [1, 2]


def test_china_revenue_market_is_configurable() -> None:
    records = [_record(1, revenue_country="China"), _record(2, revenue_country="US")]

    excluded = select_market_records(
        records,
        allowed_genres=("Puzzle", "Tabletop"),
        final_top_n=1000,
        exclude_china_revenue_market=True,
    )
    retained = select_market_records(
        records,
        allowed_genres=("Puzzle", "Tabletop"),
        final_top_n=1000,
        exclude_china_revenue_market=False,
    )

    assert [record.app_id for record in excluded] == [2]
    assert [record.app_id for record in retained] == [1, 2]


def test_zero_eligible_records_raise_typed_error() -> None:
    with pytest.raises(NoEligibleMarketRecordsError, match="candidates=2"):
        select_market_records(
            [_record(1, genre="Arcade"), _record(2, genre=None)],
            allowed_genres=("Puzzle", "Tabletop"),
            final_top_n=1000,
            exclude_china_revenue_market=True,
        )


def _raw_row(app_id: int, custom_tags: dict[str, str] | None = None) -> dict[str, Any]:
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
        **({"custom_tags": custom_tags} if custom_tags is not None else {}),
    }


def test_top_level_custom_tags_shape_is_normalized() -> None:
    record = parse_market_response(
        [_raw_row(1, {"Game Genre": "Puzzle", "Game Theme": "Decoration"})]
    )[0]

    assert record.game_genre == "Puzzle"
    assert record.game_theme == "Decoration"


def test_entities_custom_tags_and_aggregate_tags_shape_is_normalized() -> None:
    row = _raw_row(1)
    row["entities"] = [{"custom_tags": {"Game Genre": "Puzzle", "Game Theme": "Old"}}]
    row["aggregate_tags"] = {"Game Theme": "Decoration"}

    record = parse_market_response([row])[0]

    assert record.game_genre == "Puzzle"
    assert record.game_theme == "Decoration"
    assert record.model_extra["entities"] == row["entities"]


def test_aggregate_tags_override_entity_tag_with_same_key() -> None:
    row = _raw_row(1)
    row["entities"] = [{"custom_tags": {"Most Popular Country by Revenue": "US"}}]
    row["aggregate_tags"] = {"Most Popular Country by Revenue": "China"}

    record = parse_market_response([row])[0]

    assert record.most_popular_country_by_revenue == "China"


class _FakeCandidateClient:
    def __init__(self, records: list[SensorTowerMarketRecord]) -> None:
        self.records = records

    def fetch_market_candidates(
        self,
        request: object,
    ) -> list[SensorTowerMarketRecord]:
        return self.records


class _NeverCalledClient:
    def fetch_market_candidates(self, request: object) -> list[SensorTowerMarketRecord]:
        raise AssertionError("client must not be called when selection configuration drifts")


def test_fetch_and_select_derives_selection_config_from_request() -> None:
    request = build_market_request(
        date(2026, 8, 7),
        api_limit=4,
        final_top_n=1,
        allowed_genres=("Puzzle", "Tabletop"),
        exclude_china_revenue_market=False,
        scope_name="derived_scope",
    )

    selected = fetch_and_select_market_records(
        _FakeCandidateClient([_record(1), _record(2, genre="Arcade")]),
        request,
    )

    assert [record.app_id for record in selected] == [1]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("api_limit", 3),
        ("final_top_n", 2),
        ("allowed_genres", ("Tabletop",)),
        ("exclude_china_revenue_market", False),
        ("scope_name", "other_scope"),
    ],
)
def test_explicit_selection_config_must_match_request(
    field_name: str,
    value: object,
) -> None:
    request = build_market_request(
        date(2026, 8, 7),
        api_limit=4,
        final_top_n=1,
        allowed_genres=("Puzzle", "Tabletop"),
        exclude_china_revenue_market=True,
        scope_name="request_scope",
    )
    selection_values = request.selection_config().model_dump()
    selection_values[field_name] = value
    mismatched_config = SensorTowerSelectionConfig.model_validate(selection_values)

    with pytest.raises(SensorTowerSelectionConfigurationError, match=field_name):
        fetch_and_select_market_records(_NeverCalledClient(), request, mismatched_config)
