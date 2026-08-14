"""Synthetic DuckDB and Parquet boundary tests for BACKTEST-001."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from test_storage_model002 import _payload, _store_agg002, _store_model

from src.analysis.backtest_v1 import calculate_theme_launch_window_backtest
from src.storage import DuckDBRepository, StorageValidationError
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
