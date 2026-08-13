"""Mock-only integration tests for the AGG-001 workflow."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.analysis.errors import MissingSourcePeriodError
from src.config import AppConfig
from src.storage import AppMetadataRow, DuckDBRepository, MarketSnapshotRow, ParquetExportError
from src.workflows import (
    AggregateThemesRequest,
    aggregate_themes,
    format_aggregate_themes_summary,
)

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _period(month: str) -> tuple[date, date]:
    year, month_number = (int(value) for value in month.split("-"))
    start = date(year, month_number, 1)
    if month_number == 2:
        end_day = 29 if year % 4 == 0 else 28
    elif month_number in (4, 6, 9, 11):
        end_day = 30
    else:
        end_day = 31
    return start, date(year, month_number, end_day)


def _row(app_id: str, rank: int, month: str, theme: str | None) -> MarketSnapshotRow:
    period_start, period_end = _period(month)
    return MarketSnapshotRow(
        scope_name="casual_puzzle_tabletop",
        cadence="monthly",
        period_start=period_start,
        period_end=period_end,
        rank_position=rank,
        source_app_id=app_id,
        unified_app_id=app_id,
        scope_country="WW",
        device_type="total",
        category=7012,
        data_model="DM_2025_Q2",
        source_date=datetime(period_start.year, period_start.month, 15, tzinfo=UTC),
        source_country=None,
        current_units_value=None,
        units_absolute=float(rank),
        comparison_units_value=None,
        units_delta=None,
        units_transformed_delta=None,
        current_revenue_value=None,
        revenue_absolute=float(rank * 2),
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
        collected_at=NOW,
    )


def _metadata(app_id: str) -> AppMetadataRow:
    return AppMetadataRow(
        unified_app_id=app_id,
        name=None,
        publisher_display_name=f"Publisher {app_id}",
        publisher_resolution_source="publisher_name",
        android_app_id=None,
        ios_app_id=None,
        fetched_at=NOW,
    )


def _request(
    tmp_path: Path,
    *,
    start: str = "2026-07",
    end: str = "2026-07",
    plan_only: bool = False,
    skip_export: bool = False,
) -> AggregateThemesRequest:
    return AggregateThemesRequest(
        start_month=start,
        end_month=end,
        database_path=tmp_path / "data" / "aggregation.duckdb",
        export_directory=tmp_path / "exports",
        plan_only=plan_only,
        skip_export=skip_export,
    )


def _config() -> AppConfig:
    return AppConfig()


def _seed_source(database_path: Path) -> DuckDBRepository:
    repository = DuckDBRepository(database_path)
    repository.open()
    repository.initialize_schema()
    june = [_row("app-1", 1, "2026-06", "Decoration"), _row("app-old", 2, "2026-06", "Decoration")]
    july = [_row("app-1", 1, "2026-07", "Decoration"), _row("app-2", 2, "2026-07", "Unknown")]
    repository.upsert_app_metadata([_metadata("app-1"), _metadata("app-2")])
    repository.replace_market_snapshot_period(june)
    repository.replace_market_snapshot_period(july)
    return repository


def test_aggregate_workflow_uses_previous_month_outside_requested_range_and_skips_export(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, skip_export=True)
    repository = _seed_source(request.database_path)

    summary = aggregate_themes(
        request,
        _config(),
        current_utc=NOW,
        repository=repository,
    )

    assert summary.aggregated_month_count == 1
    assert summary.monthly_totals_row_count == 1
    assert summary.theme_metrics_row_count == 2
    assert summary.source_snapshot_row_count == 2
    assert summary.source_missing_theme_count == 0
    assert summary.monthly_totals_parquet_path is None
    assert summary.theme_metrics_parquet_path is None
    assert summary.market_structure_row_count == 2
    assert summary.growth_source_row_count == 2
    assert summary.dimension_row_count == 0
    assert summary.representative_game_row_count > 0
    assert summary.verification == "passed"
    assert not request.export_directory.exists()
    metrics = repository.get_theme_monthly_metrics()
    decoration = next(row for row in metrics if row.game_theme == "Decoration")
    assert decoration.has_previous_month is True
    assert decoration.new_entry_count == 0
    assert decoration.returning_product_count == 1
    unknown = next(row for row in metrics if row.game_theme == "Unknown")
    assert unknown.new_entry_count == 1
    assert unknown.returning_product_count == 0
    assert len(repository.get_theme_market_structure_metrics()) == 2
    assert len(repository.get_theme_growth_source_metrics()) == 2
    assert len(repository.get_theme_representative_games()) == summary.representative_game_row_count
    rendered = format_aggregate_themes_summary(summary)
    assert "app-1" not in rendered
    assert "auth_token" not in rendered
    assert "https://api.sensortower.com" not in rendered
    repository.close()


def test_aggregate_plan_only_does_not_open_database_or_create_files(tmp_path: Path) -> None:
    request = _request(
        tmp_path,
        start="2025-08",
        end="2025-10",
        plan_only=True,
    )

    def fail_repository_factory(path: Path) -> DuckDBRepository:
        raise AssertionError(f"repository must not be created: {path}")

    summary = aggregate_themes(
        request,
        _config(),
        current_utc=NOW,
        repository_factory=fail_repository_factory,
    )
    rendered = format_aggregate_themes_summary(summary)
    assert summary.planned_months == ("2025-08", "2025-09", "2025-10")
    assert "month_sequence=2025-08,2025-09,2025-10" in rendered
    assert "network=disabled" in rendered
    assert not request.database_path.exists()
    assert not request.export_directory.exists()


def test_missing_source_month_fails_before_replacing_derived_rows(tmp_path: Path) -> None:
    request = _request(tmp_path, start="2026-06", end="2026-07", skip_export=True)
    repository = DuckDBRepository(request.database_path)
    repository.open()
    repository.initialize_schema()
    july = [_row("app-1", 1, "2026-07", "Decoration")]
    repository.upsert_app_metadata([_metadata("app-1")])
    repository.replace_market_snapshot_period(july)

    with pytest.raises(MissingSourcePeriodError, match="2026-06"):
        aggregate_themes(
            request,
            _config(),
            current_utc=NOW,
            repository=repository,
        )
    assert repository.get_monthly_market_totals() == []
    assert repository.get_theme_monthly_metrics() == []
    repository.close()


def test_default_export_writes_both_derived_parquet_files(tmp_path: Path) -> None:
    request = _request(tmp_path)
    repository = _seed_source(request.database_path)
    repository.close()

    summary = aggregate_themes(request, _config(), current_utc=NOW)
    assert summary.monthly_totals_parquet_path == (
        request.export_directory / "monthly_market_totals.parquet"
    )
    assert summary.theme_metrics_parquet_path == (
        request.export_directory / "theme_monthly_metrics.parquet"
    )
    assert summary.monthly_totals_parquet_path.exists()
    assert summary.theme_metrics_parquet_path.exists()
    assert summary.market_structure_parquet_path is not None
    assert summary.growth_source_parquet_path is not None
    assert summary.dimension_parquet_path is not None
    assert summary.representative_games_parquet_path is not None
    assert summary.market_structure_parquet_path.exists()
    assert summary.growth_source_parquet_path.exists()
    assert summary.dimension_parquet_path.exists()
    assert summary.representative_games_parquet_path.exists()


def test_derived_export_failure_leaves_committed_duckdb_rows(tmp_path: Path) -> None:
    request = _request(tmp_path)
    repository = _seed_source(request.database_path)
    repository.close()

    def fail_metrics_export(repository: object, path: Path) -> None:
        raise ParquetExportError("theme_monthly_metrics", str(path))

    with pytest.raises(ParquetExportError):
        aggregate_themes(
            request,
            _config(),
            current_utc=NOW,
            theme_metrics_exporter=fail_metrics_export,
        )

    repository = DuckDBRepository(request.database_path)
    repository.open()
    repository.initialize_schema()
    assert len(repository.get_monthly_market_totals()) == 1
    assert len(repository.get_theme_monthly_metrics()) == 2
    assert len(repository.get_theme_market_structure_metrics()) == 2
    assert len(repository.get_theme_growth_source_metrics()) == 2
    assert len(repository.get_theme_representative_games()) > 0
    repository.close()
