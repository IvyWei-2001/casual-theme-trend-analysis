"""Mock-only integration tests for the TREND-001 score workflow."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.config import AppConfig
from src.storage import DuckDBRepository, MonthlyMarketTotal, ThemeMonthlyMetric
from src.storage.errors import ParquetExportError
from src.workflows import (
    ScoreThemesRequest,
    format_score_themes_summary,
    score_themes,
)

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
SCOPE = "casual_puzzle_tabletop"
MONTHS = (
    "2025-08",
    "2025-09",
    "2025-10",
    "2025-11",
    "2025-12",
    "2026-01",
    "2026-02",
    "2026-03",
    "2026-04",
    "2026-05",
    "2026-06",
    "2026-07",
)


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


def _aggregate_rows() -> tuple[list[MonthlyMarketTotal], list[ThemeMonthlyMetric]]:
    totals: list[MonthlyMarketTotal] = []
    metrics: list[ThemeMonthlyMetric] = []
    for month in MONTHS:
        period_start, period_end = _period(month)
        totals.append(
            MonthlyMarketTotal(
                scope_name=SCOPE,
                cadence="monthly",
                period_start=period_start,
                period_end=period_end,
                snapshot_count=5,
                theme_present_count=5,
                theme_missing_count=0,
                metadata_coverage_count=5,
                units_absolute_coverage_count=5,
                units_absolute_sum=100.0,
                revenue_absolute_coverage_count=5,
                revenue_absolute_sum=100.0,
                calculated_at=NOW,
            )
        )
        metrics.append(
            ThemeMonthlyMetric(
                scope_name=SCOPE,
                cadence="monthly",
                period_start=period_start,
                period_end=period_end,
                game_theme="Growth",
                product_count=5,
                product_share=1.0,
                top_100_count=5,
                top_500_count=5,
                average_rank=50.0,
                median_rank=50.0,
                units_absolute_coverage_count=5,
                units_absolute_sum=100.0,
                units_absolute_share=1.0,
                revenue_absolute_coverage_count=5,
                revenue_absolute_sum=100.0,
                revenue_absolute_share=1.0,
                has_previous_month=True,
                new_entry_count=1,
                returning_product_count=4,
                new_entry_share=0.2,
                publisher_coverage_count=5,
                publisher_count=2,
                top_publisher_product_share=0.4,
                calculated_at=NOW,
            )
        )
    return totals, metrics


def _request(
    tmp_path: Path,
    *,
    plan_only: bool = False,
    skip_export: bool = False,
    top_n: int = 20,
) -> ScoreThemesRequest:
    return ScoreThemesRequest(
        start_month="2025-08",
        end_month="2026-07",
        database_path=tmp_path / "data" / "scores.duckdb",
        export_directory=tmp_path / "exports",
        plan_only=plan_only,
        skip_export=skip_export,
        top_n=top_n,
    )


def _seed_repository(database_path: Path) -> DuckDBRepository:
    repository = DuckDBRepository(database_path)
    repository.open()
    repository.initialize_schema()
    totals, metrics = _aggregate_rows()
    repository.replace_theme_monthly_range(totals, metrics)
    return repository


def test_plan_only_reports_seven_scorable_target_months_without_database_or_files(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, plan_only=True)

    def fail_repository_factory(path: Path) -> DuckDBRepository:
        raise AssertionError(f"repository must not be created: {path}")

    summary = score_themes(
        request,
        AppConfig(),
        current_utc=NOW,
        repository_factory=fail_repository_factory,
    )
    rendered = format_score_themes_summary(summary)
    assert summary.history_month_count == 12
    assert summary.scorable_target_month_count == 7
    assert summary.latest_target_month == "2026-07"
    assert "first_scorable_target_month=2026-01" in rendered
    assert "last_scorable_target_month=2026-07" in rendered
    assert "network=disabled" in rendered
    assert not request.database_path.exists()
    assert not request.export_directory.exists()


def test_complete_history_replaces_all_seven_targets_and_exports_scores(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, top_n=1)
    repository = _seed_repository(request.database_path)
    repository.close()

    summary = score_themes(request, AppConfig(), current_utc=NOW)
    assert summary.trend_row_count == 7
    assert summary.actionable_row_count == 7
    assert summary.non_actionable_row_count == 0
    assert summary.latest_actionable_theme_count == 1
    assert summary.trend_parquet_path == request.export_directory / "theme_trend_scores.parquet"
    assert summary.trend_parquet_path.exists()
    assert "trend_score=" in format_score_themes_summary(summary)
    assert "product_id" not in format_score_themes_summary(summary).lower()

    repository = DuckDBRepository(request.database_path)
    repository.open()
    repository.initialize_schema()
    assert len(repository.get_theme_trend_scores()) == 7
    repository.close()


def test_skip_export_stores_scores_without_creating_trend_parquet(tmp_path: Path) -> None:
    request = _request(tmp_path, skip_export=True)
    repository = _seed_repository(request.database_path)
    repository.close()

    summary = score_themes(request, AppConfig(), current_utc=NOW)
    assert summary.trend_parquet_path is None
    assert not request.export_directory.exists()


def test_short_history_fails_clearly(tmp_path: Path) -> None:
    request = ScoreThemesRequest(
        start_month="2025-08",
        end_month="2025-12",
        database_path=tmp_path / "scores.duckdb",
        export_directory=tmp_path / "exports",
        plan_only=True,
    )
    with pytest.raises(ValueError, match="at least six"):
        score_themes(request, AppConfig(), current_utc=NOW)


def test_export_failure_leaves_committed_trend_rows(tmp_path: Path) -> None:
    request = _request(tmp_path)
    repository = _seed_repository(request.database_path)
    repository.close()

    def fail_export(repository: object, path: Path) -> None:
        raise ParquetExportError("theme_trend_scores", str(path))

    with pytest.raises(ParquetExportError):
        score_themes(
            request,
            AppConfig(),
            current_utc=NOW,
            trend_exporter=fail_export,
        )

    repository = DuckDBRepository(request.database_path)
    repository.open()
    repository.initialize_schema()
    assert len(repository.get_theme_trend_scores()) == 7
    repository.close()
