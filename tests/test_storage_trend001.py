"""Synthetic schema-v3, replacement, and export tests for TREND-001."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.analysis.trend_models import ThemeTrendScore
from src.storage import DuckDBRepository, StorageValidationError
from src.storage import schema as schema_module

CALCULATED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
SCORE_COLUMNS = schema_module.THEME_TREND_SCORES_COLUMNS


def _score(
    theme: str,
    *,
    actionable: bool = True,
    rank: int | None = 1,
) -> ThemeTrendScore:
    return ThemeTrendScore(
        scope_name="casual_puzzle_tabletop",
        cadence="monthly",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        game_theme=theme,
        window_start=date(2025, 8, 1),
        window_month_count=6,
        active_months_6m=6 if actionable else 1,
        latest_product_count=5 if actionable else 2,
        is_actionable=actionable,
        exclusion_reason=None if actionable else "insufficient_latest_product_count",
        latest_product_share=0.5,
        latest_units_absolute_share=0.5,
        latest_revenue_absolute_share=0.5,
        latest_new_entry_share=0.1,
        latest_median_rank=50.0,
        latest_publisher_count=2,
        latest_top_publisher_product_share=0.4,
        product_share_gain_3m=0.1,
        units_absolute_share_gain_3m=0.1,
        revenue_absolute_share_gain_3m=0.1,
        product_share_acceleration=0.02,
        units_absolute_share_acceleration=0.02,
        revenue_absolute_share_acceleration=0.02,
        recent3_new_entry_share=0.1,
        median_rank_improvement=5.0,
        publisher_count_gain_3m=1.0,
        units_absolute_overindex=1.0,
        revenue_absolute_overindex=1.0,
        recent3_units_coverage_ratio=1.0,
        recent3_revenue_coverage_ratio=1.0,
        latest_publisher_coverage_ratio=1.0,
        growth_score=50.0 if actionable else None,
        acceleration_score=50.0 if actionable else None,
        new_product_score=50.0 if actionable else None,
        concentration_penalty=50.0 if actionable else None,
        base_trend_score=40.0 if actionable else None,
        confidence_score=80.0,
        trend_score=32.0 if actionable else None,
        trend_rank=rank if actionable else None,
        calculated_at=CALCULATED_AT,
    )


def _initialized_repository(path: Path) -> DuckDBRepository:
    repository = DuckDBRepository(path)
    repository.open()
    repository.initialize_schema()
    return repository


def test_fresh_schema_initializes_sequentially_through_version_three(
    tmp_path: Path,
) -> None:
    repository = _initialized_repository(tmp_path / "fresh.duckdb")
    connection = repository.open()
    assert connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(1,), (2,), (3,)]
    assert tuple(row[1] for row in connection.execute(
        "PRAGMA table_info('theme_trend_scores')"
    ).fetchall()) == SCORE_COLUMNS
    repository.close()


def test_existing_version_two_upgrades_without_changing_source_or_v2_rows(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "version-two.duckdb"
    repository = DuckDBRepository(database_path)
    connection = repository.open()
    connection.execute(schema_module._CREATE_SCHEMA_MIGRATIONS_SQL)
    schema_module._apply_version_one(connection)
    schema_module._apply_version_two(connection)
    connection.execute(
        "INSERT INTO schema_migrations VALUES (1, ?), (2, ?)",
        [CALCULATED_AT, CALCULATED_AT],
    )
    connection.execute(
        "INSERT INTO app_metadata VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["app-1", "Name", "Publisher", "publisher_name", None, None, CALCULATED_AT],
    )
    connection.execute(
        "INSERT INTO monthly_market_totals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            "casual_puzzle_tabletop",
            "monthly",
            date(2026, 1, 1),
            date(2026, 1, 31),
            1,
            1,
            0,
            1,
            1,
            1.0,
            1,
            1.0,
            CALCULATED_AT,
        ],
    )

    repository.initialize_schema()
    assert connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(1,), (2,), (3,)]
    assert connection.execute("SELECT count(*) FROM app_metadata").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM monthly_market_totals").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM theme_trend_scores").fetchone() == (0,)
    repository.close()


def test_score_replacement_is_idempotent_and_only_replaces_target_rows(
    tmp_path: Path,
) -> None:
    repository = _initialized_repository(tmp_path / "scores.duckdb")
    connection = repository.open()
    connection.execute(
        "INSERT INTO app_metadata VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["app-1", "Name", "Publisher", "publisher_name", None, None, CALCULATED_AT],
    )
    connection.execute(
        "INSERT INTO monthly_market_totals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            "casual_puzzle_tabletop",
            "monthly",
            date(2026, 1, 1),
            date(2026, 1, 31),
            1,
            1,
            0,
            1,
            1,
            1.0,
            1,
            1.0,
            CALCULATED_AT,
        ],
    )
    before = (
        connection.execute("SELECT count(*) FROM app_metadata").fetchone(),
        connection.execute("SELECT count(*) FROM monthly_market_totals").fetchone(),
    )

    repository.replace_theme_trend_score_range([_score("A"), _score("B", rank=2)])
    repository.replace_theme_trend_score_range([_score("A"), _score("B", rank=2)])
    assert [row.game_theme for row in repository.get_theme_trend_scores()] == ["A", "B"]

    repository.replace_theme_trend_score_range([_score("C")])
    assert [row.game_theme for row in repository.get_theme_trend_scores()] == ["C"]
    assert (
        connection.execute("SELECT count(*) FROM app_metadata").fetchone(),
        connection.execute("SELECT count(*) FROM monthly_market_totals").fetchone(),
    ) == before

    with pytest.raises(StorageValidationError, match="ThemeTrendScore"):
        repository.replace_theme_trend_score_range([_score("C"), object()])  # type: ignore[list-item]
    assert [row.game_theme for row in repository.get_theme_trend_scores()] == ["C"]
    repository.close()


def test_score_parquet_has_explicit_columns_and_stable_order(tmp_path: Path) -> None:
    repository = _initialized_repository(tmp_path / "export.duckdb")
    repository.replace_theme_trend_score_range(
        [_score("Z", rank=2), _score("A", rank=1), _score("Unknown", actionable=False, rank=None)]
    )
    export_path = tmp_path / "exports" / "theme_trend_scores.parquet"
    repository.export_theme_trend_scores_to_parquet(export_path)
    connection = repository.open()
    assert connection.execute(
        "SELECT count(*) FROM read_parquet(?)", [str(export_path)]
    ).fetchone() == (3,)
    assert tuple(
        row[0]
        for row in connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(export_path)]
        ).fetchall()
    ) == SCORE_COLUMNS
    assert connection.execute(
        "SELECT game_theme FROM read_parquet(?)", [str(export_path)]
    ).fetchall() == [("A",), ("Z",), ("Unknown",)]
    repository.close()
