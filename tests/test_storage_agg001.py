"""Synthetic DuckDB, migration, replacement, and export tests for AGG-001."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.analysis.theme_monthly import aggregate_monthly_theme_metrics
from src.storage import (
    AppMetadataRow,
    DuckDBRepository,
    MarketSnapshotRow,
    StorageValidationError,
)
from src.storage import schema as schema_module

CALCULATED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


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


def _row(
    app_id: str,
    rank: int,
    *,
    month: str = "2026-07",
    theme: str | None = "Decoration",
    units: float | None = 1,
    revenue: float | None = 2,
) -> MarketSnapshotRow:
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
        units_absolute=units,
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
        collected_at=CALCULATED_AT,
    )


def _metadata(app_id: str, publisher: str | None = "Publisher") -> AppMetadataRow:
    return AppMetadataRow(
        unified_app_id=app_id,
        name=None,
        publisher_display_name=publisher,
        publisher_resolution_source="publisher_name" if publisher else "unavailable",
        android_app_id=None,
        ios_app_id=None,
        fetched_at=CALCULATED_AT,
    )


def _initialized_repository(path: Path) -> DuckDBRepository:
    repository = DuckDBRepository(path)
    repository.open()
    repository.initialize_schema()
    return repository


def _aggregate(rows: list[MarketSnapshotRow], metadata: dict[str, AppMetadataRow]):
    return aggregate_monthly_theme_metrics(
        [rows],
        metadata,
        calculated_at=CALCULATED_AT,
    )


def test_fresh_schema_has_version_four_tables_and_exact_columns(tmp_path: Path) -> None:
    repository = _initialized_repository(tmp_path / "fresh.duckdb")
    connection = repository.open()
    assert connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(1,), (2,), (3,), (4,), (5,), (6,)]
    assert (
        tuple(
            row[1]
            for row in connection.execute("PRAGMA table_info('monthly_market_totals')").fetchall()
        )
        == schema_module.MONTHLY_MARKET_TOTALS_COLUMNS
    )
    assert (
        tuple(
            row[1]
            for row in connection.execute("PRAGMA table_info('theme_monthly_metrics')").fetchall()
        )
        == schema_module.THEME_MONTHLY_METRICS_COLUMNS
    )
    repository.close()


def test_existing_version_one_rows_survive_sequential_upgrade(tmp_path: Path) -> None:
    database_path = tmp_path / "version-one.duckdb"
    repository = DuckDBRepository(database_path)
    connection = repository.open()
    connection.execute(schema_module._CREATE_SCHEMA_MIGRATIONS_SQL)
    schema_module._apply_version_one(connection)
    connection.execute(
        "INSERT INTO schema_migrations VALUES (1, ?)",
        [CALCULATED_AT],
    )
    source_row = _row("app-1", 1)
    connection.execute(
        "INSERT INTO app_metadata VALUES (?, ?, ?, ?, ?, ?, ?)",
        ["app-1", "Name", "Publisher", "publisher_name", None, None, CALCULATED_AT],
    )
    columns = ", ".join(schema_module.MARKET_SNAPSHOT_COLUMNS)
    values = [getattr(source_row, column) for column in schema_module.MARKET_SNAPSHOT_COLUMNS]
    connection.execute(
        f"INSERT INTO market_snapshots ({columns}) VALUES ({', '.join('?' for _ in values)})",
        values,
    )

    repository.initialize_schema()
    assert connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(1,), (2,), (3,), (4,), (5,), (6,)]
    assert connection.execute("SELECT count(*) FROM app_metadata").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM market_snapshots").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM monthly_market_totals").fetchone() == (0,)
    repository.close()


def test_derived_range_replaces_old_values_atomically_and_preserves_sources(
    tmp_path: Path,
) -> None:
    repository = _initialized_repository(tmp_path / "derived.duckdb")
    rows = [_row("app-1", 1), _row("app-2", 2, theme=None, units=None, revenue=None)]
    repository.replace_market_snapshot_period(rows)
    repository.upsert_app_metadata([_metadata("app-1"), _metadata("app-2", None)])
    source_before = repository.get_market_snapshot_period(rows[0].period_key)

    first = _aggregate(rows, {"app-1": _metadata("app-1"), "app-2": _metadata("app-2", None)})
    repository.replace_theme_monthly_range(first.monthly_totals, first.theme_metrics)
    repository.replace_theme_monthly_range(first.monthly_totals, first.theme_metrics)
    assert len(repository.get_monthly_market_totals()) == 1
    assert len(repository.get_theme_monthly_metrics()) == 1

    replacement_rows = [_row("app-1", 1, theme="New Theme", units=10, revenue=20)]
    replacement = _aggregate(replacement_rows, {"app-1": _metadata("app-1")})
    repository.replace_theme_monthly_range(
        replacement.monthly_totals,
        replacement.theme_metrics,
    )
    assert [row.game_theme for row in repository.get_theme_monthly_metrics()] == ["New Theme"]
    assert repository.get_market_snapshot_period(rows[0].period_key) == source_before

    with pytest.raises(StorageValidationError, match="ThemeMonthlyMetric"):
        repository.replace_theme_monthly_range(
            replacement.monthly_totals,
            [object()],  # type: ignore[list-item]
        )
    assert [row.game_theme for row in repository.get_theme_monthly_metrics()] == ["New Theme"]
    repository.close()


def test_derived_parquet_exports_are_readable_and_match_duckdb(tmp_path: Path) -> None:
    repository = _initialized_repository(tmp_path / "exports.duckdb")
    rows = [_row("app-2", 1), _row("app-1", 2, theme="A")]
    repository.replace_market_snapshot_period(rows)
    result = _aggregate(rows, {"app-1": _metadata("app-1"), "app-2": _metadata("app-2")})
    repository.replace_theme_monthly_range(result.monthly_totals, result.theme_metrics)

    totals_path = tmp_path / "exports" / "monthly_market_totals.parquet"
    metrics_path = tmp_path / "exports" / "theme_monthly_metrics.parquet"
    repository.export_monthly_market_totals_to_parquet(totals_path)
    repository.export_theme_monthly_metrics_to_parquet(metrics_path)
    assert repository.open().execute(
        "SELECT count(*) FROM read_parquet(?)", [str(totals_path)]
    ).fetchone() == (1,)
    assert repository.open().execute(
        "SELECT count(*) FROM read_parquet(?)", [str(metrics_path)]
    ).fetchone() == (2,)
    assert (
        tuple(
            row[0]
            for row in repository.open()
            .execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(totals_path)])
            .fetchall()
        )
        == schema_module.MONTHLY_MARKET_TOTALS_COLUMNS
    )
    assert repository.open().execute(
        "SELECT game_theme FROM read_parquet(?) ORDER BY game_theme", [str(metrics_path)]
    ).fetchall() == [("A",), ("Decoration",)]
    repository.close()
