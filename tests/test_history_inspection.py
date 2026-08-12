"""Synthetic coverage for the HIST-002 read-only history inspection."""

from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.config import AppConfig
from src.storage import DuckDBRepository, MarketSnapshotRow
from src.workflows.history_inspection import (
    HistoryInspectionRequest,
    format_history_inspection_plan,
    inspect_history,
)

AS_OF = datetime(2026, 8, 12, tzinfo=UTC)


def _row(month: str, rank: int = 1) -> MarketSnapshotRow:
    year, month_number = (int(part) for part in month.split("-"))
    period_start = date(year, month_number, 1)
    period_end = date(year, month_number, calendar.monthrange(year, month_number)[1])
    return MarketSnapshotRow(
        scope_name="casual_puzzle_tabletop",
        cadence="monthly",
        period_start=period_start,
        period_end=period_end,
        rank_position=rank,
        source_app_id=f"synthetic-source-{month}-{rank}",
        unified_app_id=f"synthetic-unified-{month}-{rank}",
        scope_country="WW",
        device_type="total",
        category=7012,
        data_model="DM_2025_Q2",
        source_date=AS_OF,
        source_country=None,
        current_units_value=None,
        units_absolute=0.0,
        comparison_units_value=None,
        units_delta=None,
        units_transformed_delta=None,
        current_revenue_value=None,
        revenue_absolute=None,
        comparison_revenue_value=None,
        revenue_delta=None,
        revenue_transformed_delta=None,
        absolute=None,
        delta=None,
        transformed_delta=None,
        game_theme="",
        game_genre="Puzzle",
        game_subgenre="N/A",
        game_product_model="Unknown",
        game_art_style=None,
        game_setting=None,
        earliest_release_date=None,
        release_date_ww=None,
        publisher_country=None,
        most_popular_country_by_revenue=None,
        is_unified_source_value=None,
        collected_at=AS_OF,
    )


def _repository(tmp_path: Path) -> DuckDBRepository:
    repository = DuckDBRepository(tmp_path / "history.duckdb")
    repository.open()
    repository.initialize_schema()
    return repository


def _request(path: Path) -> HistoryInspectionRequest:
    return HistoryInspectionRequest(
        start_month="2023-08", end_month="2026-07", database_path=path
    )


def test_plan_only_validates_exact_36_months_without_configuration_or_storage() -> None:
    summary = inspect_history(
        HistoryInspectionRequest("2023-08", "2026-07", plan_only=True),
        current_utc=AS_OF,
    )

    assert summary.expected_month_count == 36
    assert summary.expected_months[0] == "2023-08"
    assert summary.expected_months[-1] == "2026-07"
    assert "configuration=disabled" in format_history_inspection_plan(summary)
    assert "database=disabled" in format_history_inspection_plan(summary)


def test_missing_database_is_not_created_by_read_only_inspection(tmp_path: Path) -> None:
    database_path = tmp_path / "missing" / "history.duckdb"

    with pytest.raises(FileNotFoundError):
        inspect_history(_request(database_path), AppConfig(), current_utc=AS_OF)

    assert not database_path.exists()
    assert not database_path.parent.exists()


def test_complete_36_month_history_preserves_null_and_zero_evidence(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    for month in inspect_history(
        HistoryInspectionRequest("2023-08", "2026-07", plan_only=True), current_utc=AS_OF
    ).expected_months:
        repository.replace_market_snapshot_period([_row(month)])
    repository.close()

    summary = inspect_history(_request(tmp_path / "history.duckdb"), AppConfig(), current_utc=AS_OF)

    assert summary.structurally_complete is True
    assert summary.present_month_count == 36
    first = summary.month_results[0]
    assert first.downloads_coverage_count == 1
    assert first.downloads_zero_count == 1
    assert first.downloads_sum == 0.0
    assert first.revenue_usd_coverage_count == 0
    assert first.revenue_usd_sum is None
    assert first.game_theme_coverage_count == 1
    assert first.game_art_style_coverage_count == 0


@pytest.mark.parametrize(
    "replacement",
    [
        lambda row: replace(row, units_absolute=-1.0),
        lambda row: replace(row, revenue_absolute=-1.0),
        lambda row: replace(row, game_genre="Strategy"),
        lambda row: replace(row, most_popular_country_by_revenue="China"),
    ],
)
def test_structural_quality_detects_invalid_stored_rows(
    tmp_path: Path, replacement: object
) -> None:
    row = replacement(_row("2026-07"))  # type: ignore[operator]
    # Database constraints intentionally reject several invalid shapes; inject
    # a fake read-only repository for the aggregate quality boundary instead.

    class FakeRepository:
        def open_read_only(self) -> object:
            return object()

        def verify_read_only_schema(self) -> None:
            return None

        def close(self) -> None:
            return None

        def get_market_snapshot_period(self, key: object) -> list[MarketSnapshotRow]:
            return [row] if key.period_start.month == 7 else []  # type: ignore[attr-defined]

        def get_app_metadata(self, _ids: object) -> dict[str, object]:
            return {}

    summary = inspect_history(
        HistoryInspectionRequest("2026-07", "2026-07", database_path=tmp_path / "unused.duckdb"),
        AppConfig(),
        current_utc=AS_OF,
        repository=FakeRepository(),  # type: ignore[arg-type]
    )
    assert summary.month_results[0].structural_issue_count == 1
