"""Synthetic DuckDB migration, atomic replacement, and export tests for AGG-002."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest
from test_analysis_theme_monthly import CALCULATED_AT, _metadata, _row
from test_storage_trend001 import _score

from src.analysis.errors import AggregationValidationError
from src.analysis.opportunity_aggregation import aggregate_theme_opportunity_metrics
from src.analysis.theme_monthly import aggregate_monthly_theme_metrics
from src.storage import DuckDBRepository, SnapshotPeriodKey, StorageValidationError
from src.storage import schema as schema_module


def _initialized(path: Path) -> DuckDBRepository:
    repository = DuckDBRepository(path)
    repository.open()
    repository.initialize_schema()
    return repository


def _payload(*, suffix: str = ""):
    current = [
        replace(
            _row(
                f"app-a{suffix}",
                1,
                month="2026-07",
                theme="Theme",
                units=10,
                revenue=100,
            ),
            game_subgenre="Match 3",
            game_product_model="Free",
            game_art_style="Illustration",
            game_setting="Garden",
        ),
        replace(
            _row(
                f"app-b{suffix}",
                2,
                month="2026-07",
                theme="Theme",
                units=0,
                revenue=0,
            ),
            game_subgenre="Match 3",
            game_product_model="Paid",
            game_art_style="Illustration",
            game_setting="Garden",
        ),
    ]
    previous = [
        _row(
            f"app-a{suffix}",
            1,
            month="2026-06",
            theme="Theme",
            units=8,
            revenue=80,
        )
    ]
    return aggregate_theme_opportunity_metrics(
        [current],
        {row.unified_app_id: _metadata(row.unified_app_id, "Publisher") for row in current},
        previous_periods={
            SnapshotPeriodKey(
                scope_name=current[0].scope_name,
                cadence="monthly",
                period_start=date(2026, 6, 1),
                period_end=date(2026, 6, 30),
            ): previous
        },
        calculated_at=CALCULATED_AT,
    )


def _insert_typed_row(
    connection: Any, table_name: str, columns: tuple[str, ...], row: object
) -> None:
    values = [getattr(row, column) for column in columns]
    connection.execute(
        f"INSERT INTO {table_name} ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in values)})",
        values,
    )


def test_fresh_schema_has_v5_and_exact_existing_columns(tmp_path: Path) -> None:
    repository = _initialized(tmp_path / "fresh.duckdb")
    connection = repository.open()
    assert connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(1,), (2,), (3,), (4,), (5,)]
    expected = (
        (
            schema_module.THEME_MARKET_STRUCTURE_METRICS_TABLE,
            schema_module.THEME_MARKET_STRUCTURE_METRICS_COLUMNS,
        ),
        (
            schema_module.THEME_GROWTH_SOURCE_METRICS_TABLE,
            schema_module.THEME_GROWTH_SOURCE_METRICS_COLUMNS,
        ),
        (
            schema_module.THEME_DIMENSION_MONTHLY_METRICS_TABLE,
            schema_module.THEME_DIMENSION_MONTHLY_METRICS_COLUMNS,
        ),
        (
            schema_module.THEME_REPRESENTATIVE_GAMES_TABLE,
            schema_module.THEME_REPRESENTATIVE_GAMES_COLUMNS,
        ),
    )
    for table_name, columns in expected:
        actual = tuple(
            row[1] for row in connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        )
        assert actual == columns
    repository.close()


def test_version_three_migrates_without_rewriting_existing_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "version-three.duckdb"
    repository = DuckDBRepository(database_path)
    connection = repository.open()
    connection.execute(schema_module._CREATE_SCHEMA_MIGRATIONS_SQL)
    schema_module._apply_version_one(connection)
    schema_module._apply_version_two(connection)
    schema_module._apply_version_three(connection)
    connection.execute(
        "INSERT INTO schema_migrations VALUES (1, ?), (2, ?), (3, ?)",
        [CALCULATED_AT, CALCULATED_AT, CALCULATED_AT],
    )

    source = _row("app-source", 1, month="2026-07", theme="Theme", units=4, revenue=5)
    metadata = _metadata("app-source", "Publisher")
    _insert_typed_row(connection, "app_metadata", schema_module.APP_METADATA_COLUMNS, metadata)
    _insert_typed_row(connection, "market_snapshots", schema_module.MARKET_SNAPSHOT_COLUMNS, source)
    legacy = aggregate_monthly_theme_metrics(
        [[source]],
        {source.unified_app_id: metadata},
        calculated_at=CALCULATED_AT,
    )
    _insert_typed_row(
        connection,
        "monthly_market_totals",
        schema_module.MONTHLY_MARKET_TOTALS_COLUMNS,
        legacy.monthly_totals[0],
    )
    _insert_typed_row(
        connection,
        "theme_monthly_metrics",
        schema_module.THEME_MONTHLY_METRICS_COLUMNS,
        legacy.theme_metrics[0],
    )
    _insert_typed_row(
        connection,
        "theme_trend_scores",
        schema_module.THEME_TREND_SCORES_COLUMNS,
        _score("Theme"),
    )

    repository.initialize_schema()
    assert connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(1,), (2,), (3,), (4,), (5,)]
    assert connection.execute("SELECT count(*) FROM app_metadata").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM market_snapshots").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM monthly_market_totals").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM theme_monthly_metrics").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM theme_trend_scores").fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM theme_market_structure_metrics").fetchone() == (
        0,
    )
    repository.close()


def test_v2_payload_round_trips_idempotently_and_exports_all_four_tables(tmp_path: Path) -> None:
    repository = _initialized(tmp_path / "round-trip.duckdb")
    result = _payload()
    repository.replace_theme_opportunity_range(
        result.monthly_totals,
        result.theme_metrics,
        result.theme_market_structure_metrics,
        result.theme_growth_source_metrics,
        result.theme_dimension_monthly_metrics,
        result.theme_representative_games,
    )
    repository.replace_theme_opportunity_range(
        result.monthly_totals,
        result.theme_metrics,
        result.theme_market_structure_metrics,
        result.theme_growth_source_metrics,
        result.theme_dimension_monthly_metrics,
        result.theme_representative_games,
    )
    assert repository.get_monthly_market_totals() == list(result.monthly_totals)
    assert repository.get_theme_monthly_metrics() == list(result.theme_metrics)
    assert set(repository.get_theme_market_structure_metrics()) == set(
        result.theme_market_structure_metrics
    )
    assert set(repository.get_theme_growth_source_metrics()) == set(
        result.theme_growth_source_metrics
    )
    assert set(repository.get_theme_dimension_monthly_metrics()) == set(
        result.theme_dimension_monthly_metrics
    )
    assert set(repository.get_theme_representative_games()) == set(
        result.theme_representative_games
    )

    exports = (
        (
            "theme_market_structure_metrics",
            repository.export_theme_market_structure_metrics_to_parquet,
        ),
        ("theme_growth_source_metrics", repository.export_theme_growth_source_metrics_to_parquet),
        (
            "theme_dimension_monthly_metrics",
            repository.export_theme_dimension_monthly_metrics_to_parquet,
        ),
        ("theme_representative_games", repository.export_theme_representative_games_to_parquet),
    )
    for table_name, exporter in exports:
        path = tmp_path / "exports" / f"{table_name}.parquet"
        exporter(path)
        assert (
            repository.open()
            .execute("SELECT count(*) FROM read_parquet(?)", [str(path)])
            .fetchone()[0]
            == repository.open().execute(f"SELECT count(*) FROM {table_name}").fetchone()[0]
        )
        assert tuple(
            row[0]
            for row in repository.open()
            .execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)])
            .fetchall()
        ) == getattr(schema_module, f"{table_name.upper()}_COLUMNS")
    repository.close()


@pytest.mark.parametrize(
    ("field_name", "coverage_field_name"),
    (
        ("downloads_current_coverage_count", "downloads_current_coverage_count"),
        ("revenue_usd_current_coverage_count", "revenue_usd_current_coverage_count"),
    ),
)
def test_growth_current_coverage_accepts_partial_or_full_but_not_above_product_count(
    field_name: str,
    coverage_field_name: str,
) -> None:
    result = _payload()
    growth = result.theme_growth_source_metrics[0]
    assert getattr(growth, coverage_field_name) == growth.current_product_count
    assert (
        replace(growth, **{field_name: 1}).current_product_count
        == growth.current_product_count
    )
    with pytest.raises(AggregationValidationError, match=field_name):
        replace(growth, **{field_name: growth.current_product_count + 1})


@pytest.mark.parametrize(
    "field_name",
    (
        "downloads_current_coverage_count",
        "revenue_usd_current_coverage_count",
    ),
)
def test_duckdb_rejects_growth_current_coverage_above_product_count(
    tmp_path: Path,
    field_name: str,
) -> None:
    repository = _initialized(tmp_path / f"invalid-{field_name}.duckdb")
    result = _payload()
    row = result.theme_growth_source_metrics[0]
    values = [getattr(row, column) for column in schema_module.THEME_GROWTH_SOURCE_METRICS_COLUMNS]
    values[schema_module.THEME_GROWTH_SOURCE_METRICS_COLUMNS.index(field_name)] = (
        row.current_product_count + 1
    )
    with pytest.raises(duckdb.ConstraintException):
        repository.open().execute(
            f"INSERT INTO {schema_module.THEME_GROWTH_SOURCE_METRICS_TABLE} "
            f"({', '.join(schema_module.THEME_GROWTH_SOURCE_METRICS_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in values)})",
            values,
        )
    repository.close()


def test_representative_rank_limit_is_enforced_by_repository_and_duckdb(tmp_path: Path) -> None:
    repository = _initialized(tmp_path / "representative-ranks.duckdb")
    result = _payload()
    representative = result.theme_representative_games[0]
    valid_ranks = tuple(replace(representative, evidence_rank=rank) for rank in (1, 2, 3))
    assert [row.evidence_rank for row in valid_ranks] == [1, 2, 3]

    sparse = tuple(
        row
        for row in result.theme_representative_games
        if not (row.evidence_type == representative.evidence_type and row.evidence_rank == 2)
    ) + (replace(representative, evidence_rank=3),)
    with pytest.raises(StorageValidationError, match="contiguous"):
        repository.replace_theme_opportunity_range(
            result.monthly_totals,
            result.theme_metrics,
            result.theme_market_structure_metrics,
            result.theme_growth_source_metrics,
            result.theme_dimension_monthly_metrics,
            sparse,
        )

    invalid = replace(representative, evidence_rank=3)
    object.__setattr__(invalid, "evidence_rank", 4)
    with pytest.raises(StorageValidationError, match="must not exceed"):
        repository.replace_theme_opportunity_range(
            result.monthly_totals,
            result.theme_metrics,
            result.theme_market_structure_metrics,
            result.theme_growth_source_metrics,
            result.theme_dimension_monthly_metrics,
            (*result.theme_representative_games, invalid),
        )

    values = [
        getattr(representative, column)
        for column in schema_module.THEME_REPRESENTATIVE_GAMES_COLUMNS
    ]
    values[schema_module.THEME_REPRESENTATIVE_GAMES_COLUMNS.index("evidence_rank")] = 4
    with pytest.raises(duckdb.ConstraintException):
        repository.open().execute(
            f"INSERT INTO {schema_module.THEME_REPRESENTATIVE_GAMES_TABLE} "
            f"({', '.join(schema_module.THEME_REPRESENTATIVE_GAMES_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in values)})",
            values,
        )
    repository.close()


def test_opportunity_replacement_rejects_duplicate_and_mismatched_identities(
    tmp_path: Path,
) -> None:
    repository = _initialized(tmp_path / "validation.duckdb")
    result = _payload()
    with pytest.raises(StorageValidationError, match="unique identities"):
        repository.replace_theme_opportunity_range(
            result.monthly_totals,
            result.theme_metrics,
            (*result.theme_market_structure_metrics, result.theme_market_structure_metrics[0]),
            result.theme_growth_source_metrics,
            result.theme_dimension_monthly_metrics,
            result.theme_representative_games,
        )
    mismatched_period = replace(
        result.theme_market_structure_metrics[0],
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
    )
    with pytest.raises(StorageValidationError, match="match AGG-001"):
        repository.replace_theme_opportunity_range(
            result.monthly_totals,
            result.theme_metrics,
            (mismatched_period,),
            result.theme_growth_source_metrics,
            result.theme_dimension_monthly_metrics,
            result.theme_representative_games,
        )
    mismatched_theme = replace(result.theme_growth_source_metrics[0], game_theme="Other")
    with pytest.raises(StorageValidationError, match="match AGG-001"):
        repository.replace_theme_opportunity_range(
            result.monthly_totals,
            result.theme_metrics,
            result.theme_market_structure_metrics,
            (mismatched_theme,),
            result.theme_dimension_monthly_metrics,
            result.theme_representative_games,
        )
    assert repository.get_monthly_market_totals() == []
    repository.close()


class _FailingConnection:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def execute(self, query: str, parameters: Any = None) -> Any:
        if "INSERT INTO theme_representative_games" in query:
            raise RuntimeError("synthetic later-table failure")
        if parameters is None:
            return self._connection.execute(query)
        return self._connection.execute(query, parameters)

    def executemany(self, query: str, parameters: Any) -> Any:
        if "INSERT INTO theme_representative_games" in query:
            raise RuntimeError("synthetic later-table failure")
        return self._connection.executemany(query, parameters)


class _FailingRepository(DuckDBRepository):
    fail_late_insert = False

    def _require_initialized_connection(self) -> Any:
        connection = super()._require_initialized_connection()
        return _FailingConnection(connection) if self.fail_late_insert else connection


class _NoTransactionRepository(DuckDBRepository):
    def _require_initialized_connection(self) -> Any:
        raise AssertionError("replacement transaction should not begin")


def test_repository_prevalidates_invalid_no_previous_payload_before_transaction(
    tmp_path: Path,
) -> None:
    repository = _NoTransactionRepository(tmp_path / "prevalidation.duckdb")
    repository.open()
    repository.initialize_schema()
    current = [
        _row("app-a", 1, month="2026-07", theme="Theme", units=1, revenue=1),
        _row("app-b", 2, month="2026-07", theme="Theme", units=2, revenue=2),
    ]
    result = aggregate_theme_opportunity_metrics([current], {}, calculated_at=CALCULATED_AT)
    invalid_growth = replace(result.theme_growth_source_metrics[0])
    object.__setattr__(
        invalid_growth,
        "downloads_current_coverage_count",
        invalid_growth.current_product_count + 1,
    )
    with pytest.raises(StorageValidationError, match="failed validation"):
        repository.replace_theme_opportunity_range(
            result.monthly_totals,
            result.theme_metrics,
            result.theme_market_structure_metrics,
            (invalid_growth,),
            result.theme_dimension_monthly_metrics,
            result.theme_representative_games,
        )
    repository.close()


def test_later_table_insert_failure_rolls_back_every_derived_table(tmp_path: Path) -> None:
    repository = _FailingRepository(tmp_path / "rollback.duckdb")
    repository.open()
    repository.initialize_schema()
    original = _payload()
    replacement = _payload(suffix="-new")
    repository.replace_theme_opportunity_range(
        original.monthly_totals,
        original.theme_metrics,
        original.theme_market_structure_metrics,
        original.theme_growth_source_metrics,
        original.theme_dimension_monthly_metrics,
        original.theme_representative_games,
    )
    repository.fail_late_insert = True
    with pytest.raises(RuntimeError, match="later-table"):
        repository.replace_theme_opportunity_range(
            replacement.monthly_totals,
            replacement.theme_metrics,
            replacement.theme_market_structure_metrics,
            replacement.theme_growth_source_metrics,
            replacement.theme_dimension_monthly_metrics,
            replacement.theme_representative_games,
        )
    repository.fail_late_insert = False
    assert set(repository.get_theme_monthly_metrics()) == set(original.theme_metrics)
    assert set(repository.get_theme_market_structure_metrics()) == set(
        original.theme_market_structure_metrics
    )
    assert set(repository.get_theme_growth_source_metrics()) == set(
        original.theme_growth_source_metrics
    )
    assert set(repository.get_theme_dimension_monthly_metrics()) == set(
        original.theme_dimension_monthly_metrics
    )
    assert set(repository.get_theme_representative_games()) == set(
        original.theme_representative_games
    )
    repository.close()
