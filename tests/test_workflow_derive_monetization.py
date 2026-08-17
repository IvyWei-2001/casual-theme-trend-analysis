"""Offline range workflow tests for MONETIZATION-001."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.storage import DuckDBRepository, MarketSnapshotRow
from src.workflows import (
    DeriveMonetizationRequest,
    derive_monetization,
    format_derive_monetization_summary,
)
from src.workflows.errors import MonetizationWorkflowError

CURRENT_UTC = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
SCOPE_NAME = "casual_puzzle_tabletop"


def _snapshot(
    month_start: date,
    app_id: str,
    rank: int,
    revenue: float | None,
) -> MarketSnapshotRow:
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    period_end = date.fromordinal(next_month.toordinal() - 1)
    return MarketSnapshotRow(
        scope_name=SCOPE_NAME,
        cadence="monthly",
        period_start=month_start,
        period_end=period_end,
        rank_position=rank,
        source_app_id=app_id,
        unified_app_id=f"unified-{app_id}",
        scope_country="WW",
        device_type="total",
        category=7012,
        data_model="DM_2025_Q2",
        source_date=datetime(month_start.year, month_start.month, 15, tzinfo=UTC),
        source_country=None,
        current_units_value=None,
        units_absolute=rank * 10,
        comparison_units_value=None,
        units_delta=None,
        units_transformed_delta=None,
        current_revenue_value=None,
        revenue_absolute=revenue,
        comparison_revenue_value=None,
        revenue_delta=None,
        revenue_transformed_delta=None,
        absolute=None,
        delta=None,
        transformed_delta=None,
        game_theme="Theme" if rank == 1 else "Unknown",
        game_genre="Puzzle",
        game_subgenre=None,
        game_product_model="context",
        game_art_style=None,
        game_setting=None,
        earliest_release_date=None,
        release_date_ww=None,
        publisher_country=None,
        most_popular_country_by_revenue=None,
        is_unified_source_value=None,
        collected_at=CURRENT_UTC,
    )


def _seed(path: Path, months: tuple[str, ...]) -> DuckDBRepository:
    repository = DuckDBRepository(path)
    repository.open()
    repository.initialize_schema()
    for month in months:
        year, month_number = (int(part) for part in month.split("-"))
        month_start = date(year, month_number, 1)
        repository.replace_market_snapshot_period(
            [
                _snapshot(month_start, f"{month}-one", 1, None),
                _snapshot(month_start, f"{month}-two", 2, 0),
                _snapshot(month_start, f"{month}-three", 3, 10),
            ]
        )
    return repository


def _request(
    path: Path,
    export_directory: Path,
    *,
    skip_export: bool = True,
) -> DeriveMonetizationRequest:
    return DeriveMonetizationRequest(
        start_month="2026-05",
        end_month="2026-07",
        database_path=path,
        export_directory=export_directory,
        skip_export=skip_export,
    )


def test_plan_only_validates_range_without_opening_repository_or_files(tmp_path: Path) -> None:
    request = _request(tmp_path / "not-created.duckdb", tmp_path / "exports")

    def fail_factory(_: Path) -> object:
        raise AssertionError("plan-only must not construct a repository")

    summary = derive_monetization(
        request.__class__(
            start_month=request.start_month,
            end_month=request.end_month,
            database_path=request.database_path,
            export_directory=request.export_directory,
            plan_only=True,
        ),
        current_utc=CURRENT_UTC,
        repository_factory=fail_factory,  # type: ignore[arg-type]
    )

    assert summary.planned_months == ("2026-05", "2026-06", "2026-07")
    assert summary.verification == "not_run"
    assert "network=disabled" in format_derive_monetization_summary(summary)
    assert not request.database_path.exists()
    assert not request.export_directory.exists()


def test_range_is_inclusive_oldest_to_newest_and_uses_only_stored_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "derive.duckdb"
    export_directory = tmp_path / "exports"
    repository = _seed(database_path, ("2026-05", "2026-06", "2026-07"))
    summary = derive_monetization(
        _request(database_path, export_directory),
        current_utc=CURRENT_UTC,
        repository=repository,
    )

    assert summary.processed_month_count == 3
    assert summary.source_snapshot_row_count == 9
    assert summary.profile_row_count == 9
    assert summary.theme_metric_row_count == 6
    assert summary.expected_theme_identity_count == 6
    assert summary.metadata_api == "disabled"
    assert summary.feishu == "disabled"
    assert not export_directory.exists()
    assert len(repository.get_app_monetization_profiles()) == 9
    assert len(repository.get_theme_monetization_observability_metrics()) == 6
    repository.close()


def test_missing_month_fails_before_replacement_and_export(tmp_path: Path) -> None:
    database_path = tmp_path / "missing.duckdb"
    repository = _seed(database_path, ("2026-05", "2026-07"))
    existing = repository.get_market_snapshot_periods(date(2026, 5, 1), date(2026, 5, 31))
    assert existing

    with pytest.raises(MonetizationWorkflowError, match="missing stored monthly market period"):
        derive_monetization(
            _request(database_path, tmp_path / "exports"),
            current_utc=CURRENT_UTC,
            repository=repository,
        )
    assert repository.get_app_monetization_profiles() == []
    assert not (tmp_path / "exports").exists()
    repository.close()


def test_skip_export_does_not_change_market_rows_or_protected_derived_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "protected.duckdb"
    repository = _seed(database_path, ("2026-05", "2026-06", "2026-07"))
    before = repository.get_market_snapshot_periods(date(2026, 5, 1), date(2026, 7, 31))
    derive_monetization(
        _request(database_path, tmp_path / "exports"),
        current_utc=CURRENT_UTC,
        repository=repository,
    )
    after = repository.get_market_snapshot_periods(date(2026, 5, 1), date(2026, 7, 31))
    assert after == before
    assert repository._connection is not None
    assert repository._connection.execute(
        "SELECT count(*) FROM theme_trend_scores"
    ).fetchone() == (0,)
    assert repository._connection.execute(
        "SELECT count(*) FROM theme_model_summaries"
    ).fetchone() == (0,)
    repository.close()
