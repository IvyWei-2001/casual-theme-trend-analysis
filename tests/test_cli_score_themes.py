"""CLI tests for TREND-001 with no Sensor Tower access."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path

from src.__main__ import main
from src.config import AppConfig
from src.storage import DuckDBRepository, MonthlyMarketTotal, ThemeMonthlyMetric

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


def _seed_repository(database_path: Path) -> DuckDBRepository:
    months = (
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
    repository = DuckDBRepository(database_path)
    repository.open()
    repository.initialize_schema()
    totals: list[MonthlyMarketTotal] = []
    metrics: list[ThemeMonthlyMetric] = []
    for month in months:
        period_start, period_end = _period(month)
        totals.append(
            MonthlyMarketTotal(
                scope_name="casual_puzzle_tabletop",
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
                scope_name="casual_puzzle_tabletop",
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
    repository.replace_theme_monthly_range(totals, metrics)
    return repository


def _clear_environment(monkeypatch) -> None:
    for name in tuple(os.environ):
        if name.startswith("APP_"):
            monkeypatch.delenv(name, raising=False)


def test_plan_only_needs_no_token_database_or_output_files(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "score-themes",
            "--start",
            "2025-08",
            "--end",
            "2026-07",
            "--plan-only",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "history_month_count=12" in captured.out
    assert "scorable_target_month_count=7" in captured.out
    assert "first_scorable_target_month=2026-01" in captured.out
    assert "network=disabled" in captured.out
    assert "token" not in captured.out.lower()
    assert not (tmp_path / "data" / "casual_theme_trends.duckdb").exists()
    assert not (tmp_path / "data" / "exports").exists()


def test_complete_cli_output_contains_components_but_no_ids_or_credentials(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    database_path = tmp_path / "data" / "scores.duckdb"
    export_directory = tmp_path / "exports"
    monkeypatch.setenv("APP_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("APP_EXPORT_DIRECTORY", str(export_directory))
    _seed_repository(database_path).close()

    exit_code = main(
        [
            "score-themes",
            "--start",
            "2025-08",
            "--end",
            "2026-07",
            "--top",
            "1",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.count("trend_rank=") == 1
    for field in (
        "growth_score=",
        "acceleration_score=",
        "new_product_score=",
        "concentration_penalty=",
        "latest_units_absolute_share=",
        "latest_revenue_absolute_share=",
        "revenue_absolute_overindex=",
    ):
        assert field in captured.out
    assert "app-" not in captured.out
    assert "token" not in captured.out.lower()
    assert "sensortower" not in captured.out.lower()
    assert (export_directory / "theme_trend_scores.parquet").exists()


def test_skip_export_and_invalid_top_are_handled_without_network(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    database_path = tmp_path / "skip" / "scores.duckdb"
    export_directory = tmp_path / "skip" / "exports"
    monkeypatch.setenv("APP_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("APP_EXPORT_DIRECTORY", str(export_directory))
    _seed_repository(database_path).close()

    assert main(
        [
            "score-themes",
            "--start",
            "2025-08",
            "--end",
            "2026-07",
            "--skip-export",
        ]
    ) == 0
    assert not (export_directory / "theme_trend_scores.parquet").exists()
    capsys.readouterr()

    assert main(
        [
            "score-themes",
            "--start",
            "2025-08",
            "--end",
            "2026-07",
            "--top",
            "0",
            "--plan-only",
        ]
    ) == 2
    assert "positive integer" in capsys.readouterr().err


def test_unused_config_helper_is_not_required_for_plan_only() -> None:
    assert AppConfig().sensor_tower_auth_token is None
