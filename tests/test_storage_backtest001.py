"""Synthetic DuckDB and Parquet boundary tests for BACKTEST-001."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_analysis_theme_monthly import _metadata, _row
from test_storage_model002 import (
    CALCULATED_AT,
    _month_start,
    _payload,
    _store_agg002,
    _store_model,
)

from src.analysis.backtest_v1 import calculate_theme_launch_window_backtest
from src.analysis.model_v2 import calculate_theme_model_metrics
from src.analysis.opportunity_aggregation import aggregate_theme_opportunity_metrics
from src.analysis.trend_score import calculate_theme_trend_scores
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


def _payload_with_month_count(month_count: int):
    source_periods = []
    metadata = {}
    for index in range(month_count):
        month = _month_start(index)
        row = _row(
            f"app-{index}",
            1,
            month=f"{month.year:04d}-{month.month:02d}",
            theme="Theme",
            units=100.0,
            revenue=100.0,
        )
        source_periods.append([row])
        metadata[row.unified_app_id] = _metadata(row.unified_app_id, "Publisher")
    return aggregate_theme_opportunity_metrics(
        source_periods,
        metadata,
        calculated_at=CALCULATED_AT,
    )


def _calculate_backtest(payload: Any):
    calculated_at = payload.monthly_totals[0].calculated_at
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        calculated_at,
    )
    scores = calculate_theme_trend_scores(
        payload.monthly_totals,
        payload.theme_metrics,
        calculated_at=calculated_at,
    )
    return calculate_theme_launch_window_backtest(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        payload.theme_growth_source_metrics,
        scores,
        model.model_summaries,
        model.seasonality_profiles,
        calculated_at=calculated_at,
    )


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


def test_wider_to_narrower_replacement_cleans_end_boundary_and_is_idempotent(
    tmp_path: Path,
) -> None:
    repository = DuckDBRepository(tmp_path / "wider-to-narrower.duckdb")
    repository.open()
    repository.initialize_schema()
    wide_payload = _payload_with_month_count(37)
    narrow_payload = _payload_with_month_count(36)
    wide_result = _calculate_backtest(wide_payload)
    narrow_result = _calculate_backtest(narrow_payload)
    _store_agg002(repository, wide_payload)
    _store_model(
        repository,
        wide_payload,
        calculated_at=wide_payload.monthly_totals[0].calculated_at,
    )

    repository.replace_theme_backtest_range(
        wide_result.outcomes,
        wide_result.feature_metrics,
        wide_result.segment_metrics,
    )
    end_decision_month = _month_start(35)
    end_decision_rows = repository.get_theme_launch_window_outcomes(
        decision_period_start=end_decision_month,
    )
    assert end_decision_rows
    assert {row.outcome_horizon_months for row in end_decision_rows} == {1}
    assert {row.outcome_period_start for row in end_decision_rows} == {_month_start(36)}

    repository.replace_theme_backtest_range(
        narrow_result.outcomes,
        narrow_result.feature_metrics,
        narrow_result.segment_metrics,
    )
    assert not repository.get_theme_launch_window_outcomes(
        decision_period_start=end_decision_month,
    )
    assert set(
        repository.get_theme_backtest_feature_metrics(
            backtest_start=narrow_result.feature_metrics[0].backtest_start,
            backtest_end=narrow_result.feature_metrics[0].backtest_end,
        )
    ) == set(narrow_result.feature_metrics)
    assert set(
        repository.get_theme_backtest_segment_metrics(
            backtest_start=narrow_result.segment_metrics[0].backtest_start,
            backtest_end=narrow_result.segment_metrics[0].backtest_end,
        )
    ) == set(narrow_result.segment_metrics)
    snapshot = (
        repository.get_theme_launch_window_outcomes(),
        repository.get_theme_backtest_feature_metrics(),
        repository.get_theme_backtest_segment_metrics(),
    )
    repository.replace_theme_backtest_range(
        narrow_result.outcomes,
        narrow_result.feature_metrics,
        narrow_result.segment_metrics,
    )
    assert (
        repository.get_theme_launch_window_outcomes(),
        repository.get_theme_backtest_feature_metrics(),
        repository.get_theme_backtest_segment_metrics(),
    ) == snapshot
    repository.close()


def test_exact_aggregate_readers_keep_multiple_ranges_separate(tmp_path: Path) -> None:
    repository = DuckDBRepository(tmp_path / "exact-aggregate-readers.duckdb")
    repository.open()
    repository.initialize_schema()
    wide_payload = _payload_with_month_count(37)
    narrow_payload = _payload_with_month_count(36)
    wide_result = _calculate_backtest(wide_payload)
    narrow_result = _calculate_backtest(narrow_payload)
    _store_agg002(repository, wide_payload)
    _store_model(
        repository,
        wide_payload,
        calculated_at=wide_payload.monthly_totals[0].calculated_at,
    )
    repository.replace_theme_backtest_range(
        narrow_result.outcomes,
        narrow_result.feature_metrics,
        narrow_result.segment_metrics,
    )
    repository.replace_theme_backtest_range(
        wide_result.outcomes,
        wide_result.feature_metrics,
        wide_result.segment_metrics,
    )

    scope_name = wide_result.feature_metrics[0].scope_name
    wide_start = wide_result.feature_metrics[0].backtest_start
    wide_end = wide_result.feature_metrics[0].backtest_end
    narrow_start = narrow_result.feature_metrics[0].backtest_start
    narrow_end = narrow_result.feature_metrics[0].backtest_end
    exact_features = repository.get_theme_backtest_feature_metrics_exact(
        scope_name=scope_name,
        backtest_start=wide_start,
        backtest_end=wide_end,
    )
    exact_segments = repository.get_theme_backtest_segment_metrics_exact(
        scope_name=scope_name,
        backtest_start=wide_start,
        backtest_end=wide_end,
    )
    assert len(exact_features) == 228
    assert len(exact_segments) == len(wide_result.segment_metrics)
    assert {row.backtest_start for row in exact_features} == {wide_start}
    assert {row.backtest_end for row in exact_features} == {wide_end}
    assert {row.backtest_start for row in exact_segments} == {wide_start}
    assert {row.backtest_end for row in exact_segments} == {wide_end}
    assert set(exact_features) == set(wide_result.feature_metrics)
    assert set(exact_segments) == set(wide_result.segment_metrics)
    assert len(
        repository.get_theme_backtest_feature_metrics_exact(
            scope_name=scope_name,
            backtest_start=narrow_start,
            backtest_end=narrow_end,
        )
    ) == 228
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


class _EndBoundaryReadbackConnection:
    def __init__(self, connection: Any, injected_row: Any) -> None:
        self._connection = connection
        self._injected_row = injected_row
        self._injected = False

    def execute(self, query: str, parameters: Any = None) -> Any:
        if parameters is None:
            return self._connection.execute(query)
        return self._connection.execute(query, parameters)

    def executemany(self, query: str, parameters: Any) -> Any:
        result = self._connection.executemany(query, parameters)
        if "INSERT INTO theme_backtest_segment_metrics" in query and not self._injected:
            self._connection.execute(
                repository_module._INSERT_THEME_LAUNCH_WINDOW_OUTCOME_SQL,
                repository_module._theme_launch_window_outcome_parameters(self._injected_row),
            )
            self._injected = True
        return result


class _EndBoundaryReadbackRepository(DuckDBRepository):
    injected_row: Any | None = None

    def _require_initialized_connection(self) -> Any:
        connection = super()._require_initialized_connection()
        if self.injected_row is None:
            return connection
        return _EndBoundaryReadbackConnection(connection, self.injected_row)


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


def test_internal_readback_includes_end_boundary_and_rolls_back_all_three_tables(
    tmp_path: Path,
) -> None:
    repository = _EndBoundaryReadbackRepository(tmp_path / "end-boundary-readback.duckdb")
    repository.open()
    repository.initialize_schema()
    result = _calculate_and_seed(repository)
    original = (
        repository.get_theme_launch_window_outcomes(),
        repository.get_theme_backtest_feature_metrics(),
        repository.get_theme_backtest_segment_metrics(),
    )
    wider_result = _calculate_backtest(_payload_with_month_count(37))
    end_decision_month = _month_start(35)
    injected_row = next(
        row
        for row in wider_result.outcomes
        if row.decision_period_start == end_decision_month
    )
    assert injected_row.decision_period_end == date(2026, 7, 31)
    repository.injected_row = injected_row
    try:
        with pytest.raises(
            StorageValidationError,
            match="backtest outcome readback verification failed",
        ) as error:
            repository.replace_theme_backtest_range(
                result.outcomes,
                result.feature_metrics,
                result.segment_metrics,
            )
    finally:
        repository.injected_row = None

    assert str(error.value) == "backtest outcome readback verification failed"
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
