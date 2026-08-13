"""Synthetic schema, repository, rollback, and Parquet tests for MODEL-002."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_analysis_theme_monthly import _metadata, _row

from src.analysis.model_v2 import calculate_theme_model_metrics
from src.analysis.opportunity_aggregation import aggregate_theme_opportunity_metrics
from src.analysis.trend_score import calculate_theme_trend_scores
from src.storage import DuckDBRepository, SnapshotPeriodKey, StorageValidationError
from src.storage import schema as schema_module

CALCULATED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _month_start(index: int) -> date:
    month_number = 2023 * 12 + 8 - 1 + index
    year, month_zero_based = divmod(month_number, 12)
    return date(year, month_zero_based + 1, 1)


def _period_end(period_start: date) -> date:
    if period_start.month == 12:
        next_start = date(period_start.year + 1, 1, 1)
    else:
        next_start = date(period_start.year, period_start.month + 1, 1)
    return date.fromordinal(next_start.toordinal() - 1)


def _payload(*, calculated_at: datetime = CALCULATED_AT):
    source_periods = []
    metadata = {}
    for index in range(36):
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
        calculated_at=calculated_at,
    )


def _initialized(path: Path) -> DuckDBRepository:
    repository = DuckDBRepository(path)
    repository.open()
    repository.initialize_schema()
    return repository


def _target_periods(payload: Any) -> tuple[SnapshotPeriodKey, ...]:
    return tuple(
        SnapshotPeriodKey(
            scope_name=row.scope_name,
            cadence=row.cadence,
            period_start=row.period_start,
            period_end=row.period_end,
        )
        for row in payload.monthly_totals
    )


def _store_agg002(repository: DuckDBRepository, payload: Any) -> None:
    repository.replace_theme_opportunity_range(
        payload.monthly_totals,
        payload.theme_metrics,
        payload.theme_market_structure_metrics,
        payload.theme_growth_source_metrics,
        payload.theme_dimension_monthly_metrics,
        payload.theme_representative_games,
    )


def _store_model(repository: DuckDBRepository, payload: Any, *, calculated_at: datetime) -> Any:
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        calculated_at,
    )
    trend_scores = calculate_theme_trend_scores(
        payload.monthly_totals,
        payload.theme_metrics,
        calculated_at=calculated_at,
    )
    target_periods = _target_periods(payload)
    repository.replace_theme_model_range(
        trend_scores,
        model.horizon_metrics,
        model.model_summaries,
        model.seasonality_profiles,
        target_periods=target_periods,
        trend_target_periods=target_periods[5:],
    )
    return model


def test_fresh_schema_adds_only_the_three_model_tables_with_exact_columns(
    tmp_path: Path,
) -> None:
    repository = _initialized(tmp_path / "fresh.duckdb")
    connection = repository.open()
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main'"
        ).fetchall()
    }
    assert {
        schema_module.THEME_HORIZON_METRICS_TABLE,
        schema_module.THEME_MODEL_SUMMARIES_TABLE,
        schema_module.THEME_SEASONALITY_PROFILES_TABLE,
    } <= tables
    for table_name, expected_columns in (
        (
            schema_module.THEME_HORIZON_METRICS_TABLE,
            schema_module.THEME_HORIZON_METRICS_COLUMNS,
        ),
        (
            schema_module.THEME_MODEL_SUMMARIES_TABLE,
            schema_module.THEME_MODEL_SUMMARIES_COLUMNS,
        ),
        (
            schema_module.THEME_SEASONALITY_PROFILES_TABLE,
            schema_module.THEME_SEASONALITY_PROFILES_COLUMNS,
        ),
    ):
        actual_columns = tuple(
            row[1] for row in connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        )
        assert actual_columns == expected_columns
    assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (5,)
    repository.close()


def test_version_four_database_migrates_without_rewriting_existing_rows(tmp_path: Path) -> None:
    repository = _initialized(tmp_path / "version-four.duckdb")
    connection = repository.open()
    connection.execute("INSERT INTO app_metadata VALUES (?, ?, ?, ?, ?, ?, ?)", [
        "app-existing",
        "Existing",
        "Publisher",
        "publisher_name",
        None,
        None,
        CALCULATED_AT,
    ])
    for table_name in (
        schema_module.THEME_HORIZON_METRICS_TABLE,
        schema_module.THEME_MODEL_SUMMARIES_TABLE,
        schema_module.THEME_SEASONALITY_PROFILES_TABLE,
    ):
        connection.execute(f"DROP TABLE {table_name}")
    connection.execute("DELETE FROM schema_migrations WHERE version = 5")
    assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (4,)

    repository.initialize_schema()
    assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (5,)
    assert connection.execute(
        "SELECT unified_app_id, publisher_display_name FROM app_metadata"
    ).fetchone() == ("app-existing", "Publisher")
    assert connection.execute(
        "SELECT count(*) FROM theme_horizon_metrics"
    ).fetchone() == (0,)
    repository.close()


def test_model_rows_round_trip_readers_and_deterministic_zstd_exports(tmp_path: Path) -> None:
    repository = _initialized(tmp_path / "model.duckdb")
    payload = _payload()
    _store_agg002(repository, payload)
    model = _store_model(repository, payload, calculated_at=CALCULATED_AT)

    assert set(repository.get_theme_horizon_metrics()) == set(model.horizon_metrics)
    assert set(repository.get_theme_model_summaries()) == set(model.model_summaries)
    assert set(repository.get_theme_seasonality_profiles()) == set(model.seasonality_profiles)
    assert len(repository.get_theme_horizon_metrics(horizon_month_count=36)) == 6
    assert len(repository.get_theme_seasonality_profiles(metric_name="downloads_sum")) == 13 * 12

    exports = (
        (
            schema_module.THEME_HORIZON_METRICS_TABLE,
            schema_module.THEME_HORIZON_METRICS_COLUMNS,
            repository.export_theme_horizon_metrics_to_parquet,
        ),
        (
            schema_module.THEME_MODEL_SUMMARIES_TABLE,
            schema_module.THEME_MODEL_SUMMARIES_COLUMNS,
            repository.export_theme_model_summaries_to_parquet,
        ),
        (
            schema_module.THEME_SEASONALITY_PROFILES_TABLE,
            schema_module.THEME_SEASONALITY_PROFILES_COLUMNS,
            repository.export_theme_seasonality_profiles_to_parquet,
        ),
    )
    for table_name, columns, exporter in exports:
        path = tmp_path / "exports" / f"{table_name}.parquet"
        exporter(path)
        first_bytes = path.read_bytes()
        exporter(path)
        assert path.read_bytes() == first_bytes
        assert tuple(
            row[0]
            for row in repository.open().execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchall()
        ) == columns
        assert repository.open().execute(
            "SELECT count(*) FROM read_parquet(?)", [str(path)]
        ).fetchone() == (
            repository.open().execute(f"SELECT count(*) FROM {table_name}").fetchone()[0],
        )
    repository.close()


class _FailingConnection:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def execute(self, query: str, parameters: Any = None) -> Any:
        if "INSERT INTO theme_model_summaries" in query:
            raise RuntimeError("synthetic model summary insert failure")
        if parameters is None:
            return self._connection.execute(query)
        return self._connection.execute(query, parameters)

    def executemany(self, query: str, parameters: Any) -> Any:
        if "INSERT INTO theme_model_summaries" in query:
            raise RuntimeError("synthetic model summary insert failure")
        return self._connection.executemany(query, parameters)


class _FailingRepository(DuckDBRepository):
    fail_late_insert = False

    def _require_initialized_connection(self) -> Any:
        connection = super()._require_initialized_connection()
        return _FailingConnection(connection) if self.fail_late_insert else connection


def test_model_replacement_rolls_back_all_four_output_sets(tmp_path: Path) -> None:
    repository = _FailingRepository(tmp_path / "rollback.duckdb")
    repository.open()
    repository.initialize_schema()
    original_payload = _payload()
    _store_agg002(repository, original_payload)
    original_model = _store_model(repository, original_payload, calculated_at=CALCULATED_AT)
    original_scores = repository.get_theme_trend_scores()

    replacement_time = CALCULATED_AT + timedelta(minutes=1)
    replacement_model = calculate_theme_model_metrics(
        original_payload.monthly_totals,
        original_payload.theme_market_structure_metrics,
        replacement_time,
    )
    replacement_scores = calculate_theme_trend_scores(
        original_payload.monthly_totals,
        original_payload.theme_metrics,
        calculated_at=replacement_time,
    )
    target_periods = _target_periods(original_payload)
    repository.fail_late_insert = True
    with pytest.raises(RuntimeError, match="model summary insert"):
        repository.replace_theme_model_range(
            replacement_scores,
            replacement_model.horizon_metrics,
            replacement_model.model_summaries,
            replacement_model.seasonality_profiles,
            target_periods=target_periods,
            trend_target_periods=target_periods[5:],
        )
    repository.fail_late_insert = False

    assert repository.get_theme_trend_scores() == original_scores
    assert set(repository.get_theme_horizon_metrics()) == set(original_model.horizon_metrics)
    assert set(repository.get_theme_model_summaries()) == set(original_model.model_summaries)
    assert set(repository.get_theme_seasonality_profiles()) == set(
        original_model.seasonality_profiles
    )
    repository.close()


class _NoConnectionRepository(DuckDBRepository):
    def _require_initialized_connection(self) -> Any:
        raise AssertionError("MODEL-002 replacement opened a connection before validation")


def test_model_replacement_rejects_duplicate_identity_before_connection_access(
    tmp_path: Path,
) -> None:
    repository = _NoConnectionRepository(tmp_path / "prevalidation.duckdb")
    repository.open()
    repository.initialize_schema()
    payload = _payload()
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        CALCULATED_AT,
    )
    with pytest.raises(StorageValidationError, match="unique identities"):
        repository.replace_theme_model_range(
            (),
            (*model.horizon_metrics, model.horizon_metrics[0]),
            model.model_summaries,
            model.seasonality_profiles,
            target_periods=_target_periods(payload),
            trend_target_periods=_target_periods(payload)[5:],
        )
    repository.close()


def test_model_replacement_rejects_mismatched_source_identity(tmp_path: Path) -> None:
    repository = _initialized(tmp_path / "source-identity.duckdb")
    payload = _payload()
    _store_agg002(repository, payload)
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        CALCULATED_AT,
    )
    mismatched_summary = replace(model.model_summaries[0], game_theme="Other")
    summaries = (mismatched_summary, *model.model_summaries[1:])
    with pytest.raises(StorageValidationError, match="AGG-002 theme identities"):
        repository.replace_theme_model_range(
            (),
            model.horizon_metrics,
            summaries,
            model.seasonality_profiles,
            target_periods=_target_periods(payload),
            trend_target_periods=_target_periods(payload)[5:],
        )
    repository.close()


def test_model_replacement_rejects_incomplete_seasonality_group(tmp_path: Path) -> None:
    repository = _initialized(tmp_path / "seasonality-group.duckdb")
    payload = _payload()
    _store_agg002(repository, payload)
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        CALCULATED_AT,
    )
    with pytest.raises(StorageValidationError, match="twelve rows"):
        repository.replace_theme_model_range(
            (),
            model.horizon_metrics,
            model.model_summaries,
            model.seasonality_profiles[:-1],
            target_periods=_target_periods(payload),
            trend_target_periods=_target_periods(payload)[5:],
        )
    repository.close()
