"""Synthetic DuckDB and Parquet boundary tests for BACKTEST-001."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from test_storage_model002 import _payload, _store_agg002, _store_model

from src.analysis.backtest_v1 import calculate_theme_launch_window_backtest
from src.storage import DuckDBRepository, StorageValidationError
from src.storage import repository as repository_module
from src.storage import schema as schema_module


def _calculate_and_seed(repository: DuckDBRepository):
    payload = _payload()
    _store_agg002(repository, payload)
    model = _store_model(repository, payload, calculated_at=payload.monthly_totals[0].calculated_at)
    scores = repository.get_theme_trend_scores()
    result = calculate_theme_launch_window_backtest(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        payload.theme_growth_source_metrics,
        scores,
        model.model_summaries,
        model.seasonality_profiles,
        calculated_at=payload.monthly_totals[0].calculated_at,
    )
    return result


def test_backtest_tables_round_trip_and_export_with_exact_columns(tmp_path: Path) -> None:
    repository = DuckDBRepository(tmp_path / "backtest.duckdb")
    repository.open()
    repository.initialize_schema()
    result = _calculate_and_seed(repository)

    repository.replace_theme_backtest_range(
        result.outcomes,
        result.feature_metrics,
        result.segment_metrics,
    )
    assert repository.get_theme_launch_window_outcomes() == list(result.outcomes)
    assert set(repository.get_theme_backtest_feature_metrics()) == set(result.feature_metrics)
    assert set(repository.get_theme_backtest_segment_metrics()) == set(result.segment_metrics)

    exports = (
        (
            schema_module.THEME_LAUNCH_WINDOW_OUTCOMES_TABLE,
            repository.export_theme_launch_window_outcomes_to_parquet,
        ),
        (
            schema_module.THEME_BACKTEST_FEATURE_METRICS_TABLE,
            repository.export_theme_backtest_feature_metrics_to_parquet,
        ),
        (
            schema_module.THEME_BACKTEST_SEGMENT_METRICS_TABLE,
            repository.export_theme_backtest_segment_metrics_to_parquet,
        ),
    )
    for table_name, exporter in exports:
        path = tmp_path / "exports" / f"{table_name}.parquet"
        exporter(path)
        connection = repository.open()
        assert (
            connection.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
            == (connection.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0])
        )
        assert tuple(
            row[0]
            for row in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchall()
        ) == getattr(schema_module, f"{table_name.upper()}_COLUMNS")
    repository.close()


def test_backtest_registry_validation_happens_before_opening_database(tmp_path: Path) -> None:
    source_repository = DuckDBRepository(tmp_path / "source.duckdb")
    source_repository.open()
    source_repository.initialize_schema()
    result = _calculate_and_seed(source_repository)
    source_repository.close()

    invalid_features = (*result.feature_metrics[:-1], replace(result.feature_metrics[0]))
    unopened = DuckDBRepository(tmp_path / "not-created.duckdb")
    with pytest.raises(StorageValidationError, match="exact registry"):
        unopened.replace_theme_backtest_range(
            result.outcomes,
            invalid_features,
            result.segment_metrics,
        )
    assert not (tmp_path / "not-created.duckdb").exists()


def test_replacement_cleans_stale_raw_period_and_is_idempotent(tmp_path: Path) -> None:
    repository = DuckDBRepository(tmp_path / "stale.duckdb")
    repository.open()
    repository.initialize_schema()
    result = _calculate_and_seed(repository)
    repository.replace_theme_backtest_range(
        result.outcomes,
        result.feature_metrics,
        result.segment_metrics,
    )

    stale_period = min(row.decision_period_start for row in result.outcomes)
    stale_period_end = next(
        row.decision_period_end
        for row in result.outcomes
        if row.decision_period_start == stale_period
    )
    smaller_outcomes = tuple(
        row for row in result.outcomes if row.decision_period_start != stale_period
    )
    replacement = (smaller_outcomes, result.feature_metrics, result.segment_metrics)
    repository.replace_theme_backtest_range(*replacement)

    assert not repository.get_theme_launch_window_outcomes(
        decision_period_start=stale_period,
        decision_period_end=stale_period_end,
    )
    first_snapshot = (
        repository.get_theme_launch_window_outcomes(),
        repository.get_theme_backtest_feature_metrics(),
        repository.get_theme_backtest_segment_metrics(),
    )
    repository.replace_theme_backtest_range(*replacement)
    assert (
        repository.get_theme_launch_window_outcomes(),
        repository.get_theme_backtest_feature_metrics(),
        repository.get_theme_backtest_segment_metrics(),
    ) == first_snapshot
    repository.close()


class _LateBacktestInsertFailureConnection:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def execute(self, query: str, parameters: Any = None) -> Any:
        if parameters is None:
            return self._connection.execute(query)
        return self._connection.execute(query, parameters)

    def executemany(self, query: str, parameters: Any) -> Any:
        if "INSERT INTO theme_backtest_segment_metrics" in query:
            raise RuntimeError("synthetic backtest segment insert failure")
        return self._connection.executemany(query, parameters)


class _LateBacktestInsertFailureRepository(DuckDBRepository):
    fail_late_insert = False

    def _require_initialized_connection(self) -> Any:
        connection = super()._require_initialized_connection()
        if self.fail_late_insert:
            return _LateBacktestInsertFailureConnection(connection)
        return connection


def test_late_insert_failure_preserves_all_three_prior_tables(tmp_path: Path) -> None:
    repository = _LateBacktestInsertFailureRepository(tmp_path / "late-failure.duckdb")
    repository.open()
    repository.initialize_schema()
    result = _calculate_and_seed(repository)
    repository.replace_theme_backtest_range(
        result.outcomes,
        result.feature_metrics,
        result.segment_metrics,
    )
    original = (
        repository.get_theme_launch_window_outcomes(),
        repository.get_theme_backtest_feature_metrics(),
        repository.get_theme_backtest_segment_metrics(),
    )

    repository.fail_late_insert = True
    with pytest.raises(RuntimeError, match="backtest segment insert"):
        repository.replace_theme_backtest_range(
            result.outcomes,
            result.feature_metrics,
            result.segment_metrics,
        )
    repository.fail_late_insert = False

    assert (
        repository.get_theme_launch_window_outcomes(),
        repository.get_theme_backtest_feature_metrics(),
        repository.get_theme_backtest_segment_metrics(),
    ) == original
    repository.close()


def test_internal_readback_mismatch_rolls_back_all_three_tables(
    tmp_path: Path,
) -> None:
    repository = DuckDBRepository(tmp_path / "readback-mismatch.duckdb")
    repository.open()
    repository.initialize_schema()
    result = _calculate_and_seed(repository)
    repository.replace_theme_backtest_range(
        result.outcomes,
        result.feature_metrics,
        result.segment_metrics,
    )
    original = (
        repository.get_theme_launch_window_outcomes(),
        repository.get_theme_backtest_feature_metrics(),
        repository.get_theme_backtest_segment_metrics(),
    )
    original_mapper = repository_module._theme_backtest_feature_metric_from_database_row
    armed = True

    def corrupt_once(row: Any) -> Any:
        nonlocal armed
        metric = original_mapper(row)
        if armed:
            armed = False
            return replace(metric, calculated_at=metric.calculated_at + timedelta(seconds=1))
        return metric

    repository_module._theme_backtest_feature_metric_from_database_row = corrupt_once
    try:
        with pytest.raises(StorageValidationError, match="feature readback"):
            repository.replace_theme_backtest_range(
                result.outcomes,
                result.feature_metrics,
                result.segment_metrics,
            )
    finally:
        repository_module._theme_backtest_feature_metric_from_database_row = original_mapper

    assert (
        repository.get_theme_launch_window_outcomes(),
        repository.get_theme_backtest_feature_metrics(),
        repository.get_theme_backtest_segment_metrics(),
    ) == original
    repository.close()


def test_version_five_to_six_migration_preserves_prior_rows(tmp_path: Path) -> None:
    repository = DuckDBRepository(tmp_path / "v5-to-v6.duckdb")
    repository.open()
    repository.initialize_schema()
    payload = _payload()
    _store_agg002(repository, payload)
    model = _store_model(repository, payload, calculated_at=payload.monthly_totals[0].calculated_at)
    connection = repository.open()
    prior_tables = (
        "app_metadata",
        "market_snapshots",
        "monthly_market_totals",
        "theme_monthly_metrics",
        "theme_trend_scores",
        "theme_market_structure_metrics",
        "theme_growth_source_metrics",
        "theme_dimension_monthly_metrics",
        "theme_representative_games",
        "theme_horizon_metrics",
        "theme_model_summaries",
        "theme_seasonality_profiles",
    )
    before = {
        table: (
            connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
            connection.execute(f"SELECT * FROM {table} ORDER BY ALL LIMIT 1").fetchone(),
        )
        for table in prior_tables
    }
    for table in (
        schema_module.THEME_LAUNCH_WINDOW_OUTCOMES_TABLE,
        schema_module.THEME_BACKTEST_FEATURE_METRICS_TABLE,
        schema_module.THEME_BACKTEST_SEGMENT_METRICS_TABLE,
    ):
        connection.execute(f"DROP TABLE {table}")
    connection.execute("DELETE FROM schema_migrations WHERE version = 6")
    assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (5,)

    repository.initialize_schema()

    after = {
        table: (
            connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
            connection.execute(f"SELECT * FROM {table} ORDER BY ALL LIMIT 1").fetchone(),
        )
        for table in prior_tables
    }
    assert after == before
    assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (6,)
    assert (
        "future_top_quintile_eligible_count"
        in schema_module.THEME_BACKTEST_SEGMENT_METRICS_COLUMNS
    )
    assert len(model.model_summaries) == before["theme_model_summaries"][0]
    repository.close()
