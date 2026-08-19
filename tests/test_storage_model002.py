"""Synthetic schema, repository, rollback, and Parquet tests for MODEL-002."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
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


def _payload(*, calculated_at: datetime = CALCULATED_AT, month_count: int = 36):
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


def test_fresh_schema_retains_model_tables_with_exact_columns(
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
    assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (9,)
    repository.close()


@pytest.mark.parametrize(
    ("history_month_count", "complete_year_count"),
    ((36, 2), (24, 3)),
)
def test_duckdb_rejects_non_exact_profile_complete_year_count(
    tmp_path: Path,
    history_month_count: int,
    complete_year_count: int,
) -> None:
    repository = _initialized(
        tmp_path / f"profile-{history_month_count}-{complete_year_count}.duckdb"
    )
    payload = _payload()
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        CALCULATED_AT,
    )
    profile = next(row for row in model.seasonality_profiles if row.history_month_count == 36)
    columns = schema_module.THEME_SEASONALITY_PROFILES_COLUMNS
    values = [getattr(profile, column) for column in columns]
    values[columns.index("history_month_count")] = history_month_count
    values[columns.index("complete_year_count")] = complete_year_count
    query = (
        f"INSERT INTO {schema_module.THEME_SEASONALITY_PROFILES_TABLE} "
        f"({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})"
    )
    with pytest.raises(duckdb.ConstraintException):
        repository.open().execute(query, values)
    repository.close()


def test_duckdb_rejects_non_exact_summary_complete_year_count(tmp_path: Path) -> None:
    repository = _initialized(tmp_path / "summary-complete-year.duckdb")
    payload = _payload()
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        CALCULATED_AT,
    )
    summary = next(
        row for row in model.model_summaries if row.seasonality_history_month_count == 36
    )
    columns = schema_module.THEME_MODEL_SUMMARIES_COLUMNS
    values = [getattr(summary, column) for column in columns]
    values[columns.index("seasonality_complete_year_count")] = 2
    query = (
        f"INSERT INTO {schema_module.THEME_MODEL_SUMMARIES_TABLE} "
        f"({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})"
    )
    with pytest.raises(duckdb.ConstraintException):
        repository.open().execute(query, values)
    repository.close()


def test_version_four_database_migrates_without_rewriting_existing_rows(tmp_path: Path) -> None:
    repository = _initialized(tmp_path / "version-four.duckdb")
    connection = repository.open()
    connection.execute(
        "INSERT INTO app_metadata VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            "app-existing",
            "Existing",
            "Publisher",
            "publisher_name",
            None,
            None,
            CALCULATED_AT,
        ],
    )
    for table_name in (
        schema_module.THEME_HORIZON_METRICS_TABLE,
        schema_module.THEME_MODEL_SUMMARIES_TABLE,
        schema_module.THEME_SEASONALITY_PROFILES_TABLE,
        schema_module.THEME_LAUNCH_WINDOW_OUTCOMES_TABLE,
        schema_module.THEME_BACKTEST_FEATURE_METRICS_TABLE,
        schema_module.THEME_BACKTEST_SEGMENT_METRICS_TABLE,
        schema_module.APP_MONETIZATION_PROFILES_TABLE,
        schema_module.THEME_MONETIZATION_OBSERVABILITY_METRICS_TABLE,
        schema_module.THEME_DECISION_SUMMARIES_TABLE,
        schema_module.THEME_LAUNCH_WINDOW_ASSESSMENTS_TABLE,
        schema_module.THEME_DECISION_RISKS_TABLE,
        schema_module.THEME_CATEGORY_FIT_ASSESSMENTS_TABLE,
        schema_module.THEME_MIGRATION_HYPOTHESES_TABLE,
    ):
        connection.execute(f"DROP TABLE {table_name}")
    connection.execute("DELETE FROM schema_migrations WHERE version IN (5, 6, 7, 8, 9)")
    assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (4,)

    repository.initialize_schema()
    assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (9,)
    assert connection.execute(
        "SELECT unified_app_id, publisher_display_name FROM app_metadata"
    ).fetchone() == ("app-existing", "Publisher")
    assert connection.execute("SELECT count(*) FROM theme_horizon_metrics").fetchone() == (0,)
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
        assert (
            tuple(
                row[0]
                for row in repository.open()
                .execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)])
                .fetchall()
            )
            == columns
        )
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


def test_model_replacement_rejects_corrupted_naive_timestamp_before_connection_access(
    tmp_path: Path,
) -> None:
    repository = _NoConnectionRepository(tmp_path / "naive-timestamp.duckdb")
    repository.open()
    repository.initialize_schema()
    payload = _payload()
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        CALCULATED_AT,
    )
    corrupted_row = model.horizon_metrics[0]
    object.__setattr__(corrupted_row, "calculated_at", datetime(2026, 8, 10, 12, 0))

    with pytest.raises(StorageValidationError, match="MODEL-002 rows failed validation"):
        repository.replace_theme_model_range(
            (),
            model.horizon_metrics,
            model.model_summaries,
            model.seasonality_profiles,
            target_periods=_target_periods(payload),
            trend_target_periods=_target_periods(payload)[5:],
        )
    repository.close()


@pytest.mark.parametrize(
    ("history_month_count", "complete_year_count"),
    ((36, 2), (24, 3)),
)
def test_model_replacement_rejects_non_exact_complete_year_count_before_connection_access(
    tmp_path: Path,
    history_month_count: int,
    complete_year_count: int,
) -> None:
    repository = _NoConnectionRepository(
        tmp_path / f"prevalidation-{history_month_count}-{complete_year_count}.duckdb"
    )
    repository.open()
    repository.initialize_schema()
    payload = _payload()
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        CALCULATED_AT,
    )
    corrupted_profile = replace(model.seasonality_profiles[0])
    object.__setattr__(corrupted_profile, "history_month_count", history_month_count)
    object.__setattr__(corrupted_profile, "complete_year_count", complete_year_count)
    profiles = (corrupted_profile, *model.seasonality_profiles[1:])

    with pytest.raises(StorageValidationError, match="MODEL-002 rows failed validation"):
        repository.replace_theme_model_range(
            (),
            model.horizon_metrics,
            model.model_summaries,
            profiles,
            target_periods=_target_periods(payload),
            trend_target_periods=_target_periods(payload)[5:],
        )
    repository.close()


@pytest.mark.parametrize(
    ("field_name", "replacement_value"),
    (("observation_count", 2), ("history_start", date(2023, 9, 1))),
)
def test_model_replacement_rejects_mixed_seasonality_metadata_before_connection_access(
    tmp_path: Path,
    field_name: str,
    replacement_value: object,
) -> None:
    repository = _NoConnectionRepository(tmp_path / f"mixed-{field_name}.duckdb")
    repository.open()
    repository.initialize_schema()
    payload = _payload()
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        CALCULATED_AT,
    )
    original_profile = next(
        row for row in model.seasonality_profiles if row.history_month_count == 36
    )
    malformed_profile = replace(
        original_profile,
        **{field_name: replacement_value},
    )
    profiles = tuple(
        malformed_profile if row is original_profile else row for row in model.seasonality_profiles
    )

    with pytest.raises(StorageValidationError, match="metadata must be consistent"):
        repository.replace_theme_model_range(
            (),
            model.horizon_metrics,
            model.model_summaries,
            profiles,
            target_periods=_target_periods(payload),
            trend_target_periods=_target_periods(payload)[5:],
        )
    repository.close()


def test_model_replacement_rejects_mixed_complete_year_group_before_connection_access(
    tmp_path: Path,
) -> None:
    repository = _NoConnectionRepository(tmp_path / "mixed-complete-year.duckdb")
    repository.open()
    repository.initialize_schema()
    payload = _payload()
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        CALCULATED_AT,
    )
    original_profile = next(
        row for row in model.seasonality_profiles if row.history_month_count == 36
    )
    malformed_profile = replace(original_profile)
    object.__setattr__(malformed_profile, "complete_year_count", 2)
    profiles = tuple(
        malformed_profile if row is original_profile else row for row in model.seasonality_profiles
    )

    with pytest.raises(StorageValidationError, match="MODEL-002 rows failed validation"):
        repository.replace_theme_model_range(
            (),
            model.horizon_metrics,
            model.model_summaries,
            profiles,
            target_periods=_target_periods(payload),
            trend_target_periods=_target_periods(payload)[5:],
        )
    repository.close()


def test_model_replacement_rejects_summary_profile_complete_year_mismatch(
    tmp_path: Path,
) -> None:
    repository = _NoConnectionRepository(tmp_path / "summary-profile-year.duckdb")
    repository.open()
    repository.initialize_schema()
    payload = _payload()
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        CALCULATED_AT,
    )
    target = max(
        row.period_start for row in model.seasonality_profiles if row.history_month_count == 36
    )
    profiles = tuple(
        replace(row, history_month_count=24, complete_year_count=2, observation_count=2)
        if row.period_start == target and row.metric_name == "product_count"
        else row
        for row in model.seasonality_profiles
    )

    with pytest.raises(StorageValidationError, match="match model summary"):
        repository.replace_theme_model_range(
            (),
            model.horizon_metrics,
            model.model_summaries,
            profiles,
            target_periods=_target_periods(payload),
            trend_target_periods=_target_periods(payload)[5:],
        )
    repository.close()


def test_model_replacement_rejects_malformed_seasonality_mean_before_transaction(
    tmp_path: Path,
) -> None:
    repository = _NoConnectionRepository(tmp_path / "seasonality-mean.duckdb")
    repository.open()
    repository.initialize_schema()
    payload = _payload()
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        CALCULATED_AT,
    )
    original_profile = model.seasonality_profiles[0]
    malformed_index = original_profile.seasonal_index + 0.1
    malformed_profile = replace(
        original_profile,
        seasonal_index=malformed_index,
        index_deviation=malformed_index - 1,
    )
    profiles = (malformed_profile, *model.seasonality_profiles[1:])

    with pytest.raises(StorageValidationError, match="average approximately one"):
        repository.replace_theme_model_range(
            (),
            model.horizon_metrics,
            model.model_summaries,
            profiles,
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
