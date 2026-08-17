"""Synthetic latest-month MONETIZATION-001 workflow tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.sensor_tower import (
    GAME_IQ_IAP_BUNDLES_TAG,
    MONETIZATION_ADS_TAG,
    SensorTowerMarketRecord,
    SensorTowerSelectionConfig,
)
from src.sensor_tower.dto import GAME_GENRE_TAG, GAME_THEME_TAG
from src.storage import DuckDBRepository, MarketSnapshotRow
from src.workflows import (
    CollectMonetizationRequest,
    collect_monetization,
    format_collect_monetization_summary,
)
from src.workflows.errors import MonetizationWorkflowError

CURRENT_UTC = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
PERIOD_START = date(2026, 7, 1)
PERIOD_END = date(2026, 7, 31)
SCOPE_NAME = "casual_puzzle_tabletop"


def _snapshot(source_app_id: str, rank_position: int, theme: str) -> MarketSnapshotRow:
    return MarketSnapshotRow(
        scope_name=SCOPE_NAME,
        cadence="monthly",
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        rank_position=rank_position,
        source_app_id=source_app_id,
        unified_app_id=f"unified-{source_app_id}",
        scope_country="WW",
        device_type="total",
        category=7012,
        data_model="DM_2025_Q2",
        source_date=datetime(2026, 7, 15, tzinfo=UTC),
        source_country=None,
        current_units_value=None,
        units_absolute=100,
        comparison_units_value=None,
        units_delta=None,
        units_transformed_delta=None,
        current_revenue_value=None,
        revenue_absolute=10,
        comparison_revenue_value=None,
        revenue_delta=None,
        revenue_transformed_delta=None,
        absolute=None,
        delta=None,
        transformed_delta=None,
        game_theme=theme,
        game_genre="Puzzle",
        game_subgenre=None,
        game_product_model=None,
        game_art_style=None,
        game_setting=None,
        earliest_release_date=None,
        release_date_ww=None,
        publisher_country=None,
        most_popular_country_by_revenue=None,
        is_unified_source_value=None,
        collected_at=CURRENT_UTC,
    )


def _record(source_app_id: str, tags: dict[str, object]) -> SensorTowerMarketRecord:
    return SensorTowerMarketRecord(
        app_id=source_app_id,
        date=datetime(2026, 7, 15, tzinfo=UTC),
        units_absolute=100,
        revenue_absolute=10,
        custom_tags={GAME_GENRE_TAG: "Puzzle", GAME_THEME_TAG: "Fetched", **tags},
    )


class _FakeMarketClient:
    def __init__(self, records: list[SensorTowerMarketRecord]) -> None:
        self.records = records
        self.fetch_count = 0

    def fetch_market_candidates(self, request: object) -> list[SensorTowerMarketRecord]:
        del request
        self.fetch_count += 1
        return self.records

    def close(self) -> None:
        return None


def _config() -> SimpleNamespace:
    selection_config = SensorTowerSelectionConfig(
        api_limit=10,
        final_top_n=2,
        allowed_genres=("Puzzle",),
        exclude_china_revenue_market=False,
        scope_name=SCOPE_NAME,
    )
    return SimpleNamespace(
        sensor_tower_selection_config=selection_config,
        build_sensor_tower_market_request=lambda period_start, end_date: (
            period_start,
            end_date,
        ),
    )


def _repository(tmp_path: Path) -> tuple[DuckDBRepository, list[MarketSnapshotRow]]:
    rows = [_snapshot("a1", 1, "Theme"), _snapshot("a2", 2, "Other")]
    repository = DuckDBRepository(tmp_path / "workflow.duckdb")
    repository.open()
    repository.initialize_schema()
    repository.replace_market_snapshot_period(rows)
    return repository, rows


def test_latest_workflow_reuses_one_market_response_and_preserves_source_population(
    tmp_path: Path,
) -> None:
    repository, stored_rows = _repository(tmp_path)
    client = _FakeMarketClient(
        [
            _record("a1", {MONETIZATION_ADS_TAG: True}),
            _record(
                "a3",
                {MONETIZATION_ADS_TAG: False, GAME_IQ_IAP_BUNDLES_TAG: True},
            ),
        ]
    )
    request = CollectMonetizationRequest(
        month="2026-07",
        database_path=tmp_path / "workflow.duckdb",
        export_directory=tmp_path / "exports",
        skip_export=True,
    )

    summary = collect_monetization(
        request,
        _config(),
        current_utc=CURRENT_UTC,
        client=client,
        repository=repository,
    )

    assert client.fetch_count == 1
    assert summary.stored_snapshot_count == 2
    assert summary.candidate_count == 2
    assert summary.selected_count == 2
    assert summary.matched_source_record_count == 1
    assert summary.unmatched_stored_snapshot_count == 1
    assert summary.extra_selected_record_count == 1
    assert summary.profile_row_count == 2
    assert summary.classified_profile_count == 1
    assert summary.unknown_profile_count == 1
    assert summary.theme_metric_row_count == 2
    assert summary.metadata_api == "disabled"
    assert summary.feishu == "disabled"
    assert "parquet_export=skipped" in format_collect_monetization_summary(summary)
    assert repository.get_market_snapshot_period(stored_rows[0].period_key) == stored_rows
    assert not (tmp_path / "exports").exists()
    repository.close()


def test_older_than_latest_month_is_rejected_before_market_request(tmp_path: Path) -> None:
    repository, _ = _repository(tmp_path)
    client = _FakeMarketClient([])
    request = CollectMonetizationRequest(
        month="2026-06",
        database_path=tmp_path / "workflow.duckdb",
        export_directory=tmp_path / "exports",
        skip_export=True,
    )

    with pytest.raises(MonetizationWorkflowError, match="latest stored market month"):
        collect_monetization(
            request,
            _config(),
            current_utc=CURRENT_UTC,
            client=client,
            repository=repository,
        )
    assert client.fetch_count == 0
    repository.close()


def test_duplicate_fetched_source_ids_fail_without_output_replacement(tmp_path: Path) -> None:
    repository, stored_rows = _repository(tmp_path)
    client = _FakeMarketClient(
        [
            _record("a1", {MONETIZATION_ADS_TAG: True}),
            _record("a1", {MONETIZATION_ADS_TAG: False}),
        ]
    )
    request = CollectMonetizationRequest(
        month="2026-07",
        database_path=tmp_path / "workflow.duckdb",
        export_directory=tmp_path / "exports",
        skip_export=True,
    )

    with pytest.raises(MonetizationWorkflowError, match="fetched source identities"):
        collect_monetization(
            request,
            _config(),
            current_utc=CURRENT_UTC,
            client=client,
            repository=repository,
        )
    assert repository.get_market_snapshot_period(stored_rows[0].period_key) == stored_rows
    assert repository.get_app_monetization_profiles() == []
    repository.close()
