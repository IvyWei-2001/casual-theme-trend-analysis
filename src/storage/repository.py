"""Repository operations for the versioned local DuckDB store."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from math import isclose, isfinite
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self, cast

import duckdb

from ..analysis.backtest_models import (
    BACKTEST_OUTCOME_HORIZONS,
    BACKTEST_POLICY_VERSION,
    FEATURE_DEFINITIONS,
    PRIMARY_OUTCOME_NAMES,
    ThemeBacktestFeatureMetric,
    ThemeBacktestSegmentMetric,
    ThemeLaunchWindowOutcome,
)
from ..analysis.backtest_models import (
    month_shift as month_shift_for_storage,
)
from ..analysis.backtest_models import (
    natural_month_end as natural_month_end_for_storage,
)
from ..analysis.model_v2_models import (
    ThemeHorizonMetric,
    ThemeModelSummary,
    ThemeSeasonalityProfile,
)
from ..analysis.models import MonthlyMarketTotal, ThemeMonthlyMetric
from ..analysis.opportunity_models import (
    DEFAULT_REPRESENTATIVE_GAME_LIMIT,
    ThemeDimensionMonthlyMetric,
    ThemeGrowthSourceMetric,
    ThemeMarketStructureMetric,
    ThemeRepresentativeGame,
)
from ..analysis.trend_models import ThemeTrendScore
from .connection import open_duckdb_connection, open_duckdb_read_only_connection
from .errors import (
    RepositoryConnectionModeError,
    RepositoryNotOpenError,
    SchemaNotInitializedError,
    StorageValidationError,
)
from .models import (
    AppMetadataRow,
    MarketSnapshotRow,
    MetadataCacheLookup,
    SnapshotPeriodKey,
    normalize_opaque_id_sequence,
    require_timezone_aware,
)
from .schema import (
    APP_METADATA_COLUMNS,
    APP_METADATA_TABLE,
    MARKET_SNAPSHOT_COLUMNS,
    MARKET_SNAPSHOTS_TABLE,
    MONTHLY_MARKET_TOTALS_COLUMNS,
    MONTHLY_MARKET_TOTALS_TABLE,
    THEME_BACKTEST_FEATURE_METRICS_COLUMNS,
    THEME_BACKTEST_FEATURE_METRICS_TABLE,
    THEME_BACKTEST_SEGMENT_METRICS_COLUMNS,
    THEME_BACKTEST_SEGMENT_METRICS_TABLE,
    THEME_DIMENSION_MONTHLY_METRICS_COLUMNS,
    THEME_DIMENSION_MONTHLY_METRICS_TABLE,
    THEME_GROWTH_SOURCE_METRICS_COLUMNS,
    THEME_GROWTH_SOURCE_METRICS_TABLE,
    THEME_HORIZON_METRICS_COLUMNS,
    THEME_HORIZON_METRICS_TABLE,
    THEME_LAUNCH_WINDOW_OUTCOMES_COLUMNS,
    THEME_LAUNCH_WINDOW_OUTCOMES_TABLE,
    THEME_MARKET_STRUCTURE_METRICS_COLUMNS,
    THEME_MARKET_STRUCTURE_METRICS_TABLE,
    THEME_MODEL_SUMMARIES_COLUMNS,
    THEME_MODEL_SUMMARIES_TABLE,
    THEME_MONTHLY_METRICS_COLUMNS,
    THEME_MONTHLY_METRICS_TABLE,
    THEME_REPRESENTATIVE_GAMES_COLUMNS,
    THEME_REPRESENTATIVE_GAMES_TABLE,
    THEME_SEASONALITY_PROFILES_COLUMNS,
    THEME_SEASONALITY_PROFILES_TABLE,
    THEME_TREND_SCORES_COLUMNS,
    THEME_TREND_SCORES_TABLE,
    initialize_schema,
    verify_read_only_schema,
)

_APP_METADATA_COLUMNS_SQL = ", ".join(APP_METADATA_COLUMNS)
_APP_METADATA_PLACEHOLDERS_SQL = ", ".join("?" for _ in APP_METADATA_COLUMNS)
_MARKET_SNAPSHOT_COLUMNS_SQL = ", ".join(MARKET_SNAPSHOT_COLUMNS)
_MARKET_SNAPSHOT_PLACEHOLDERS_SQL = ", ".join("?" for _ in MARKET_SNAPSHOT_COLUMNS)
_MONTHLY_MARKET_TOTALS_COLUMNS_SQL = ", ".join(MONTHLY_MARKET_TOTALS_COLUMNS)
_MONTHLY_MARKET_TOTALS_PLACEHOLDERS_SQL = ", ".join("?" for _ in MONTHLY_MARKET_TOTALS_COLUMNS)
_THEME_MONTHLY_METRICS_COLUMNS_SQL = ", ".join(THEME_MONTHLY_METRICS_COLUMNS)
_THEME_MONTHLY_METRICS_PLACEHOLDERS_SQL = ", ".join("?" for _ in THEME_MONTHLY_METRICS_COLUMNS)
_THEME_MARKET_STRUCTURE_METRICS_COLUMNS_SQL = ", ".join(THEME_MARKET_STRUCTURE_METRICS_COLUMNS)
_THEME_MARKET_STRUCTURE_METRICS_PLACEHOLDERS_SQL = ", ".join(
    "?" for _ in THEME_MARKET_STRUCTURE_METRICS_COLUMNS
)
_THEME_GROWTH_SOURCE_METRICS_COLUMNS_SQL = ", ".join(THEME_GROWTH_SOURCE_METRICS_COLUMNS)
_THEME_GROWTH_SOURCE_METRICS_PLACEHOLDERS_SQL = ", ".join(
    "?" for _ in THEME_GROWTH_SOURCE_METRICS_COLUMNS
)
_THEME_DIMENSION_MONTHLY_METRICS_COLUMNS_SQL = ", ".join(THEME_DIMENSION_MONTHLY_METRICS_COLUMNS)
_THEME_DIMENSION_MONTHLY_METRICS_PLACEHOLDERS_SQL = ", ".join(
    "?" for _ in THEME_DIMENSION_MONTHLY_METRICS_COLUMNS
)
_THEME_REPRESENTATIVE_GAMES_COLUMNS_SQL = ", ".join(THEME_REPRESENTATIVE_GAMES_COLUMNS)
_THEME_REPRESENTATIVE_GAMES_PLACEHOLDERS_SQL = ", ".join(
    "?" for _ in THEME_REPRESENTATIVE_GAMES_COLUMNS
)
_THEME_TREND_SCORES_COLUMNS_SQL = ", ".join(THEME_TREND_SCORES_COLUMNS)
_THEME_TREND_SCORES_PLACEHOLDERS_SQL = ", ".join("?" for _ in THEME_TREND_SCORES_COLUMNS)
_THEME_HORIZON_METRICS_COLUMNS_SQL = ", ".join(THEME_HORIZON_METRICS_COLUMNS)
_THEME_HORIZON_METRICS_PLACEHOLDERS_SQL = ", ".join("?" for _ in THEME_HORIZON_METRICS_COLUMNS)
_THEME_MODEL_SUMMARIES_COLUMNS_SQL = ", ".join(THEME_MODEL_SUMMARIES_COLUMNS)
_THEME_MODEL_SUMMARIES_PLACEHOLDERS_SQL = ", ".join("?" for _ in THEME_MODEL_SUMMARIES_COLUMNS)
_THEME_SEASONALITY_PROFILES_COLUMNS_SQL = ", ".join(THEME_SEASONALITY_PROFILES_COLUMNS)
_THEME_SEASONALITY_PROFILES_PLACEHOLDERS_SQL = ", ".join(
    "?" for _ in THEME_SEASONALITY_PROFILES_COLUMNS
)
_THEME_LAUNCH_WINDOW_OUTCOMES_COLUMNS_SQL = ", ".join(THEME_LAUNCH_WINDOW_OUTCOMES_COLUMNS)
_THEME_LAUNCH_WINDOW_OUTCOMES_PLACEHOLDERS_SQL = ", ".join(
    "?" for _ in THEME_LAUNCH_WINDOW_OUTCOMES_COLUMNS
)
_THEME_BACKTEST_FEATURE_METRICS_COLUMNS_SQL = ", ".join(THEME_BACKTEST_FEATURE_METRICS_COLUMNS)
_THEME_BACKTEST_FEATURE_METRICS_PLACEHOLDERS_SQL = ", ".join(
    "?" for _ in THEME_BACKTEST_FEATURE_METRICS_COLUMNS
)
_THEME_BACKTEST_SEGMENT_METRICS_COLUMNS_SQL = ", ".join(THEME_BACKTEST_SEGMENT_METRICS_COLUMNS)
_THEME_BACKTEST_SEGMENT_METRICS_PLACEHOLDERS_SQL = ", ".join(
    "?" for _ in THEME_BACKTEST_SEGMENT_METRICS_COLUMNS
)

_DELETE_MARKET_PERIOD_SQL = """
DELETE FROM market_snapshots
WHERE scope_name = ?
  AND cadence = ?
  AND period_start = ?
  AND period_end = ?
"""

_INSERT_MARKET_SNAPSHOT_SQL = (
    f"INSERT INTO {MARKET_SNAPSHOTS_TABLE} ({_MARKET_SNAPSHOT_COLUMNS_SQL}) "
    f"VALUES ({_MARKET_SNAPSHOT_PLACEHOLDERS_SQL})"
)

_UPSERT_APP_METADATA_SQL = f"""
INSERT INTO {APP_METADATA_TABLE} ({_APP_METADATA_COLUMNS_SQL})
VALUES ({_APP_METADATA_PLACEHOLDERS_SQL})
ON CONFLICT (unified_app_id) DO UPDATE SET
    name = EXCLUDED.name,
    publisher_display_name = EXCLUDED.publisher_display_name,
    publisher_resolution_source = EXCLUDED.publisher_resolution_source,
    android_app_id = EXCLUDED.android_app_id,
    ios_app_id = EXCLUDED.ios_app_id,
    fetched_at = EXCLUDED.fetched_at
"""

_DELETE_MONTHLY_MARKET_TOTALS_SQL = """
DELETE FROM monthly_market_totals
WHERE scope_name = ?
  AND cadence = ?
  AND period_start = ?
  AND period_end = ?
"""

_DELETE_THEME_MONTHLY_METRICS_SQL = """
DELETE FROM theme_monthly_metrics
WHERE scope_name = ?
  AND cadence = ?
  AND period_start = ?
  AND period_end = ?
"""

_INSERT_MONTHLY_MARKET_TOTAL_SQL = (
    f"INSERT INTO {MONTHLY_MARKET_TOTALS_TABLE} ({_MONTHLY_MARKET_TOTALS_COLUMNS_SQL}) "
    f"VALUES ({_MONTHLY_MARKET_TOTALS_PLACEHOLDERS_SQL})"
)

_INSERT_THEME_MONTHLY_METRIC_SQL = (
    f"INSERT INTO {THEME_MONTHLY_METRICS_TABLE} ({_THEME_MONTHLY_METRICS_COLUMNS_SQL}) "
    f"VALUES ({_THEME_MONTHLY_METRICS_PLACEHOLDERS_SQL})"
)

_DELETE_THEME_MARKET_STRUCTURE_METRICS_SQL = """
DELETE FROM theme_market_structure_metrics
WHERE scope_name = ?
  AND cadence = ?
  AND period_start = ?
  AND period_end = ?
"""

_DELETE_THEME_GROWTH_SOURCE_METRICS_SQL = """
DELETE FROM theme_growth_source_metrics
WHERE scope_name = ?
  AND cadence = ?
  AND period_start = ?
  AND period_end = ?
"""

_DELETE_THEME_DIMENSION_MONTHLY_METRICS_SQL = """
DELETE FROM theme_dimension_monthly_metrics
WHERE scope_name = ?
  AND cadence = ?
  AND period_start = ?
  AND period_end = ?
"""

_DELETE_THEME_REPRESENTATIVE_GAMES_SQL = """
DELETE FROM theme_representative_games
WHERE scope_name = ?
  AND cadence = ?
  AND period_start = ?
  AND period_end = ?
"""

_INSERT_THEME_MARKET_STRUCTURE_METRIC_SQL = (
    f"INSERT INTO {THEME_MARKET_STRUCTURE_METRICS_TABLE} "
    f"({_THEME_MARKET_STRUCTURE_METRICS_COLUMNS_SQL}) "
    f"VALUES ({_THEME_MARKET_STRUCTURE_METRICS_PLACEHOLDERS_SQL})"
)
_INSERT_THEME_GROWTH_SOURCE_METRIC_SQL = (
    f"INSERT INTO {THEME_GROWTH_SOURCE_METRICS_TABLE} "
    f"({_THEME_GROWTH_SOURCE_METRICS_COLUMNS_SQL}) "
    f"VALUES ({_THEME_GROWTH_SOURCE_METRICS_PLACEHOLDERS_SQL})"
)
_INSERT_THEME_DIMENSION_MONTHLY_METRIC_SQL = (
    f"INSERT INTO {THEME_DIMENSION_MONTHLY_METRICS_TABLE} "
    f"({_THEME_DIMENSION_MONTHLY_METRICS_COLUMNS_SQL}) "
    f"VALUES ({_THEME_DIMENSION_MONTHLY_METRICS_PLACEHOLDERS_SQL})"
)
_INSERT_THEME_REPRESENTATIVE_GAME_SQL = (
    f"INSERT INTO {THEME_REPRESENTATIVE_GAMES_TABLE} "
    f"({_THEME_REPRESENTATIVE_GAMES_COLUMNS_SQL}) "
    f"VALUES ({_THEME_REPRESENTATIVE_GAMES_PLACEHOLDERS_SQL})"
)

_DELETE_THEME_TREND_SCORES_SQL = """
DELETE FROM theme_trend_scores
WHERE scope_name = ?
  AND cadence = ?
  AND period_start = ?
  AND period_end = ?
"""

_INSERT_THEME_TREND_SCORE_SQL = (
    f"INSERT INTO {THEME_TREND_SCORES_TABLE} ({_THEME_TREND_SCORES_COLUMNS_SQL}) "
    f"VALUES ({_THEME_TREND_SCORES_PLACEHOLDERS_SQL})"
)

_DELETE_THEME_HORIZON_METRICS_SQL = """
DELETE FROM theme_horizon_metrics
WHERE scope_name = ?
  AND cadence = ?
  AND period_start = ?
  AND period_end = ?
"""
_DELETE_THEME_MODEL_SUMMARIES_SQL = """
DELETE FROM theme_model_summaries
WHERE scope_name = ?
  AND cadence = ?
  AND period_start = ?
  AND period_end = ?
"""
_DELETE_THEME_SEASONALITY_PROFILES_SQL = """
DELETE FROM theme_seasonality_profiles
WHERE scope_name = ?
  AND cadence = ?
  AND period_start = ?
  AND period_end = ?
"""
_INSERT_THEME_HORIZON_METRIC_SQL = (
    f"INSERT INTO {THEME_HORIZON_METRICS_TABLE} "
    f"({_THEME_HORIZON_METRICS_COLUMNS_SQL}) "
    f"VALUES ({_THEME_HORIZON_METRICS_PLACEHOLDERS_SQL})"
)
_INSERT_THEME_MODEL_SUMMARY_SQL = (
    f"INSERT INTO {THEME_MODEL_SUMMARIES_TABLE} "
    f"({_THEME_MODEL_SUMMARIES_COLUMNS_SQL}) "
    f"VALUES ({_THEME_MODEL_SUMMARIES_PLACEHOLDERS_SQL})"
)
_INSERT_THEME_SEASONALITY_PROFILE_SQL = (
    f"INSERT INTO {THEME_SEASONALITY_PROFILES_TABLE} "
    f"({_THEME_SEASONALITY_PROFILES_COLUMNS_SQL}) "
    f"VALUES ({_THEME_SEASONALITY_PROFILES_PLACEHOLDERS_SQL})"
)
_INSERT_THEME_LAUNCH_WINDOW_OUTCOME_SQL = (
    f"INSERT INTO {THEME_LAUNCH_WINDOW_OUTCOMES_TABLE} "
    f"({_THEME_LAUNCH_WINDOW_OUTCOMES_COLUMNS_SQL}) "
    f"VALUES ({_THEME_LAUNCH_WINDOW_OUTCOMES_PLACEHOLDERS_SQL})"
)
_INSERT_THEME_BACKTEST_FEATURE_METRIC_SQL = (
    f"INSERT INTO {THEME_BACKTEST_FEATURE_METRICS_TABLE} "
    f"({_THEME_BACKTEST_FEATURE_METRICS_COLUMNS_SQL}) "
    f"VALUES ({_THEME_BACKTEST_FEATURE_METRICS_PLACEHOLDERS_SQL})"
)
_INSERT_THEME_BACKTEST_SEGMENT_METRIC_SQL = (
    f"INSERT INTO {THEME_BACKTEST_SEGMENT_METRICS_TABLE} "
    f"({_THEME_BACKTEST_SEGMENT_METRICS_COLUMNS_SQL}) "
    f"VALUES ({_THEME_BACKTEST_SEGMENT_METRICS_PLACEHOLDERS_SQL})"
)


class DuckDBRepository:
    """Open, initialize, and query the local analytical DuckDB store."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._connection_mode: Literal["read-write", "read-only"] | None = None
        self._schema_initialized = False

    def open(self) -> duckdb.DuckDBPyConnection:
        """Open the configured database without creating business tables."""

        if self._connection is not None:
            if self._connection_mode != "read-write":
                raise RepositoryConnectionModeError(
                    "read-write", self._connection_mode or "unknown"
                )
            return self._connection
        self._connection = open_duckdb_connection(self.database_path)
        self._connection_mode = "read-write"
        self._schema_initialized = False
        return self._connection

    def open_read_only(self) -> duckdb.DuckDBPyConnection:
        """Open the existing database in DuckDB read-only mode."""

        if self._connection is not None:
            if self._connection_mode != "read-only":
                raise RepositoryConnectionModeError("read-only", self._connection_mode or "unknown")
            return self._connection
        self._connection = open_duckdb_read_only_connection(self.database_path)
        self._connection_mode = "read-only"
        self._schema_initialized = False
        return self._connection

    def close(self) -> None:
        """Close the connection if it is open; repeated calls are safe."""

        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._connection_mode = None
        self._schema_initialized = False

    def initialize_schema(self) -> None:
        """Explicitly create or verify the supported schema version."""

        self._require_connection_mode("read-write")
        connection = self._require_open_connection()
        initialize_schema(connection)
        self._schema_initialized = True

    def verify_read_only_schema(self) -> None:
        """Verify required read-only tables and columns without migrations."""

        self._require_connection_mode("read-only")
        connection = self._require_open_connection()
        verify_read_only_schema(connection)
        self._schema_initialized = True

    def replace_market_snapshot_period(
        self,
        rows: Sequence[MarketSnapshotRow],
    ) -> None:
        """Atomically replace one complete market period with validated rows."""

        rows_tuple, period_key = _validate_market_snapshot_period(rows)
        connection = self._require_initialized_connection()

        try:
            connection.execute("BEGIN TRANSACTION")
            connection.execute(
                _DELETE_MARKET_PERIOD_SQL,
                [
                    period_key.scope_name,
                    period_key.cadence,
                    period_key.period_start,
                    period_key.period_end,
                ],
            )
            connection.executemany(
                _INSERT_MARKET_SNAPSHOT_SQL,
                [_market_snapshot_parameters(row) for row in rows_tuple],
            )
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise

    def get_market_snapshot_period(
        self,
        key: SnapshotPeriodKey,
    ) -> list[MarketSnapshotRow]:
        """Read one period in ascending rank order."""

        if not isinstance(key, SnapshotPeriodKey):
            raise StorageValidationError("key must be a SnapshotPeriodKey")
        connection = self._require_initialized_connection()
        rows = connection.execute(
            f"SELECT {_MARKET_SNAPSHOT_COLUMNS_SQL} "
            f"FROM {MARKET_SNAPSHOTS_TABLE} "
            "WHERE scope_name = ? AND cadence = ? AND period_start = ? AND period_end = ? "
            "ORDER BY rank_position",
            [key.scope_name, key.cadence, key.period_start, key.period_end],
        ).fetchall()
        return [_market_snapshot_from_database_row(row) for row in rows]

    def get_monthly_market_totals(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> list[MonthlyMarketTotal]:
        """Read schema-v2 month-wide totals in deterministic identity order."""

        connection = self._require_initialized_connection()
        where_sql, parameters = _derived_filter_sql(
            scope_name=scope_name,
            cadence=cadence,
            period_start=period_start,
            period_end=period_end,
        )
        rows = connection.execute(
            f"SELECT {_MONTHLY_MARKET_TOTALS_COLUMNS_SQL} "
            f"FROM {MONTHLY_MARKET_TOTALS_TABLE} "
            f"{where_sql} "
            "ORDER BY scope_name, period_start, period_end, cadence",
            parameters,
        ).fetchall()
        return [_monthly_market_total_from_database_row(row) for row in rows]

    def get_theme_monthly_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeMonthlyMetric]:
        """Read schema-v2 theme metrics in deterministic identity order."""

        connection = self._require_initialized_connection()
        where_sql, parameters = _derived_filter_sql(
            scope_name=scope_name,
            cadence=cadence,
            period_start=period_start,
            period_end=period_end,
            game_theme=game_theme,
        )
        rows = connection.execute(
            f"SELECT {_THEME_MONTHLY_METRICS_COLUMNS_SQL} "
            f"FROM {THEME_MONTHLY_METRICS_TABLE} "
            f"{where_sql} "
            "ORDER BY scope_name, period_start, period_end, game_theme, cadence",
            parameters,
        ).fetchall()
        return [_theme_monthly_metric_from_database_row(row) for row in rows]

    def get_theme_market_structure_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeMarketStructureMetric]:
        """Read V2 market-structure rows in deterministic identity order."""

        connection = self._require_initialized_connection()
        where_sql, parameters = _derived_filter_sql(
            scope_name=scope_name,
            cadence=cadence,
            period_start=period_start,
            period_end=period_end,
            game_theme=game_theme,
        )
        rows = connection.execute(
            f"SELECT {_THEME_MARKET_STRUCTURE_METRICS_COLUMNS_SQL} "
            f"FROM {THEME_MARKET_STRUCTURE_METRICS_TABLE} "
            f"{where_sql} "
            "ORDER BY scope_name, period_start, period_end, game_theme, cadence",
            parameters,
        ).fetchall()
        return [_theme_market_structure_metric_from_database_row(row) for row in rows]

    def get_theme_growth_source_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeGrowthSourceMetric]:
        """Read V2 growth-source rows in deterministic identity order."""

        connection = self._require_initialized_connection()
        where_sql, parameters = _derived_filter_sql(
            scope_name=scope_name,
            cadence=cadence,
            period_start=period_start,
            period_end=period_end,
            game_theme=game_theme,
        )
        rows = connection.execute(
            f"SELECT {_THEME_GROWTH_SOURCE_METRICS_COLUMNS_SQL} "
            f"FROM {THEME_GROWTH_SOURCE_METRICS_TABLE} "
            f"{where_sql} "
            "ORDER BY scope_name, period_start, period_end, game_theme, cadence",
            parameters,
        ).fetchall()
        return [_theme_growth_source_metric_from_database_row(row) for row in rows]

    def get_theme_dimension_monthly_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
        dimension_type: str | None = None,
        dimension_value: str | None = None,
    ) -> list[ThemeDimensionMonthlyMetric]:
        """Read observed V2 dimension rows in deterministic identity order."""

        connection = self._require_initialized_connection()
        where_sql, parameters = _derived_filter_sql(
            scope_name=scope_name,
            cadence=cadence,
            period_start=period_start,
            period_end=period_end,
            game_theme=game_theme,
            dimension_type=dimension_type,
            dimension_value=dimension_value,
        )
        rows = connection.execute(
            f"SELECT {_THEME_DIMENSION_MONTHLY_METRICS_COLUMNS_SQL} "
            f"FROM {THEME_DIMENSION_MONTHLY_METRICS_TABLE} "
            f"{where_sql} "
            "ORDER BY scope_name, period_start, period_end, game_theme, "
            "dimension_type, dimension_value, cadence",
            parameters,
        ).fetchall()
        return [_theme_dimension_monthly_metric_from_database_row(row) for row in rows]

    def get_theme_representative_games(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
        evidence_type: str | None = None,
    ) -> list[ThemeRepresentativeGame]:
        """Read representative-game evidence in deterministic identity order."""

        connection = self._require_initialized_connection()
        where_sql, parameters = _derived_filter_sql(
            scope_name=scope_name,
            cadence=cadence,
            period_start=period_start,
            period_end=period_end,
            game_theme=game_theme,
            evidence_type=evidence_type,
        )
        rows = connection.execute(
            f"SELECT {_THEME_REPRESENTATIVE_GAMES_COLUMNS_SQL} "
            f"FROM {THEME_REPRESENTATIVE_GAMES_TABLE} "
            f"{where_sql} "
            "ORDER BY scope_name, period_start, period_end, game_theme, "
            "evidence_type, evidence_rank, cadence",
            parameters,
        ).fetchall()
        return [_theme_representative_game_from_database_row(row) for row in rows]

    def get_theme_trend_scores(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeTrendScore]:
        """Read schema-v3 trend scores in deterministic ranking order."""

        connection = self._require_initialized_connection()
        where_sql, parameters = _derived_filter_sql(
            scope_name=scope_name,
            cadence=cadence,
            period_start=period_start,
            period_end=period_end,
            game_theme=game_theme,
        )
        rows = connection.execute(
            f"SELECT {_THEME_TREND_SCORES_COLUMNS_SQL} "
            f"FROM {THEME_TREND_SCORES_TABLE} "
            f"{where_sql} "
            "ORDER BY scope_name, period_start, trend_rank NULLS LAST, game_theme, cadence",
            parameters,
        ).fetchall()
        return [_theme_trend_score_from_database_row(row) for row in rows]

    def get_theme_horizon_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
        horizon_month_count: int | None = None,
        metric_name: str | None = None,
    ) -> list[ThemeHorizonMetric]:
        """Read long-form horizon evidence in deterministic identity order."""

        connection = self._require_initialized_connection()
        where_sql, parameters = _derived_filter_sql(
            scope_name=scope_name,
            cadence=cadence,
            period_start=period_start,
            period_end=period_end,
            game_theme=game_theme,
            horizon_month_count=horizon_month_count,
            metric_name=metric_name,
        )
        rows = connection.execute(
            f"SELECT {_THEME_HORIZON_METRICS_COLUMNS_SQL} "
            f"FROM {THEME_HORIZON_METRICS_TABLE} "
            f"{where_sql} "
            "ORDER BY scope_name, period_start, period_end, game_theme, "
            "horizon_month_count, metric_name, cadence",
            parameters,
        ).fetchall()
        return [_theme_horizon_metric_from_database_row(row) for row in rows]

    def get_theme_model_summaries(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeModelSummary]:
        """Read model-evidence summaries in deterministic identity order."""

        connection = self._require_initialized_connection()
        where_sql, parameters = _derived_filter_sql(
            scope_name=scope_name,
            cadence=cadence,
            period_start=period_start,
            period_end=period_end,
            game_theme=game_theme,
        )
        rows = connection.execute(
            f"SELECT {_THEME_MODEL_SUMMARIES_COLUMNS_SQL} "
            f"FROM {THEME_MODEL_SUMMARIES_TABLE} "
            f"{where_sql} "
            "ORDER BY scope_name, period_start, period_end, game_theme, cadence",
            parameters,
        ).fetchall()
        return [_theme_model_summary_from_database_row(row) for row in rows]

    def get_theme_seasonality_profiles(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
        metric_name: str | None = None,
        calendar_month: int | None = None,
    ) -> list[ThemeSeasonalityProfile]:
        """Read seasonality profiles in deterministic identity order."""

        connection = self._require_initialized_connection()
        where_sql, parameters = _derived_filter_sql(
            scope_name=scope_name,
            cadence=cadence,
            period_start=period_start,
            period_end=period_end,
            game_theme=game_theme,
            metric_name=metric_name,
            calendar_month=calendar_month,
        )
        rows = connection.execute(
            f"SELECT {_THEME_SEASONALITY_PROFILES_COLUMNS_SQL} "
            f"FROM {THEME_SEASONALITY_PROFILES_TABLE} "
            f"{where_sql} "
            "ORDER BY scope_name, period_start, period_end, game_theme, "
            "metric_name, calendar_month, cadence",
            parameters,
        ).fetchall()
        return [_theme_seasonality_profile_from_database_row(row) for row in rows]

    def get_theme_launch_window_outcomes(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        decision_period_start: date | None = None,
        decision_period_end: date | None = None,
        game_theme: str | None = None,
        outcome_horizon_months: int | None = None,
    ) -> list[ThemeLaunchWindowOutcome]:
        """Read raw launch-window outcomes in deterministic identity order."""

        connection = self._require_initialized_connection()
        where_sql, parameters = _backtest_filter_sql(
            scope_name=scope_name,
            cadence=cadence,
            start_column="decision_period_start",
            end_column="decision_period_end",
            period_start=decision_period_start,
            period_end=decision_period_end,
            game_theme=game_theme,
            outcome_horizon_months=outcome_horizon_months,
        )
        rows = connection.execute(
            f"SELECT {_THEME_LAUNCH_WINDOW_OUTCOMES_COLUMNS_SQL} "
            f"FROM {THEME_LAUNCH_WINDOW_OUTCOMES_TABLE} "
            f"{where_sql} "
            "ORDER BY scope_name, decision_period_start, decision_period_end, "
            "game_theme, outcome_horizon_months, cadence",
            parameters,
        ).fetchall()
        return [_theme_launch_window_outcome_from_database_row(row) for row in rows]

    def get_theme_backtest_feature_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        backtest_start: date | None = None,
        backtest_end: date | None = None,
        outcome_horizon_months: int | None = None,
        feature_name: str | None = None,
        feature_group: str | None = None,
        outcome_name: str | None = None,
    ) -> list[ThemeBacktestFeatureMetric]:
        """Read continuous feature metrics in deterministic registry order."""

        connection = self._require_initialized_connection()
        where_sql, parameters = _backtest_filter_sql(
            scope_name=scope_name,
            cadence=cadence,
            start_column="backtest_start",
            end_column="backtest_end",
            period_start=backtest_start,
            period_end=backtest_end,
            outcome_horizon_months=outcome_horizon_months,
            feature_name=feature_name,
            feature_group=feature_group,
            outcome_name=outcome_name,
        )
        rows = connection.execute(
            f"SELECT {_THEME_BACKTEST_FEATURE_METRICS_COLUMNS_SQL} "
            f"FROM {THEME_BACKTEST_FEATURE_METRICS_TABLE} "
            f"{where_sql} "
            "ORDER BY scope_name, backtest_start, backtest_end, outcome_horizon_months, "
            "feature_name, outcome_name, cadence",
            parameters,
        ).fetchall()
        return [_theme_backtest_feature_metric_from_database_row(row) for row in rows]

    def get_theme_backtest_segment_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        backtest_start: date | None = None,
        backtest_end: date | None = None,
        outcome_horizon_months: int | None = None,
        segment_name: str | None = None,
        segment_value: str | None = None,
        outcome_name: str | None = None,
    ) -> list[ThemeBacktestSegmentMetric]:
        """Read categorical segment metrics in deterministic identity order."""

        connection = self._require_initialized_connection()
        where_sql, parameters = _backtest_filter_sql(
            scope_name=scope_name,
            cadence=cadence,
            start_column="backtest_start",
            end_column="backtest_end",
            period_start=backtest_start,
            period_end=backtest_end,
            outcome_horizon_months=outcome_horizon_months,
            segment_name=segment_name,
            segment_value=segment_value,
            outcome_name=outcome_name,
        )
        rows = connection.execute(
            f"SELECT {_THEME_BACKTEST_SEGMENT_METRICS_COLUMNS_SQL} "
            f"FROM {THEME_BACKTEST_SEGMENT_METRICS_TABLE} "
            f"{where_sql} "
            "ORDER BY scope_name, backtest_start, backtest_end, outcome_horizon_months, "
            "segment_name, segment_value, outcome_name, cadence",
            parameters,
        ).fetchall()
        return [_theme_backtest_segment_metric_from_database_row(row) for row in rows]

    def replace_theme_monthly_range(
        self,
        monthly_totals: Sequence[MonthlyMarketTotal],
        theme_metrics: Sequence[ThemeMonthlyMetric],
    ) -> None:
        """Atomically replace a complete set of schema-v2 derived rows."""

        totals_tuple, metrics_tuple, period_keys = _validate_theme_monthly_range(
            monthly_totals,
            theme_metrics,
        )
        connection = self._require_initialized_connection()

        try:
            connection.execute("BEGIN TRANSACTION")
            for key in period_keys:
                parameters = [
                    key.scope_name,
                    key.cadence,
                    key.period_start,
                    key.period_end,
                ]
                connection.execute(_DELETE_MONTHLY_MARKET_TOTALS_SQL, parameters)
                connection.execute(_DELETE_THEME_MONTHLY_METRICS_SQL, parameters)
            connection.executemany(
                _INSERT_MONTHLY_MARKET_TOTAL_SQL,
                [_monthly_market_total_parameters(row) for row in totals_tuple],
            )
            if metrics_tuple:
                connection.executemany(
                    _INSERT_THEME_MONTHLY_METRIC_SQL,
                    [_theme_monthly_metric_parameters(row) for row in metrics_tuple],
                )
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise

    def replace_theme_opportunity_range(
        self,
        monthly_totals: Sequence[MonthlyMarketTotal],
        theme_metrics: Sequence[ThemeMonthlyMetric],
        theme_market_structure_metrics: Sequence[ThemeMarketStructureMetric],
        theme_growth_source_metrics: Sequence[ThemeGrowthSourceMetric],
        theme_dimension_monthly_metrics: Sequence[ThemeDimensionMonthlyMetric],
        theme_representative_games: Sequence[ThemeRepresentativeGame],
    ) -> None:
        """Atomically replace the six AGG-001/AGG-002 derived output sets."""

        payload = _validate_theme_opportunity_range(
            monthly_totals,
            theme_metrics,
            theme_market_structure_metrics,
            theme_growth_source_metrics,
            theme_dimension_monthly_metrics,
            theme_representative_games,
        )
        (
            totals_tuple,
            metrics_tuple,
            structures_tuple,
            growth_tuple,
            dimensions_tuple,
            representative_tuple,
            period_keys,
        ) = payload
        connection = self._require_initialized_connection()
        try:
            connection.execute("BEGIN TRANSACTION")
            for key in period_keys:
                parameters = [
                    key.scope_name,
                    key.cadence,
                    key.period_start,
                    key.period_end,
                ]
                connection.execute(_DELETE_MONTHLY_MARKET_TOTALS_SQL, parameters)
                connection.execute(_DELETE_THEME_MONTHLY_METRICS_SQL, parameters)
                connection.execute(_DELETE_THEME_MARKET_STRUCTURE_METRICS_SQL, parameters)
                connection.execute(_DELETE_THEME_GROWTH_SOURCE_METRICS_SQL, parameters)
                connection.execute(_DELETE_THEME_DIMENSION_MONTHLY_METRICS_SQL, parameters)
                connection.execute(_DELETE_THEME_REPRESENTATIVE_GAMES_SQL, parameters)
            connection.executemany(
                _INSERT_MONTHLY_MARKET_TOTAL_SQL,
                [_monthly_market_total_parameters(row) for row in totals_tuple],
            )
            if metrics_tuple:
                connection.executemany(
                    _INSERT_THEME_MONTHLY_METRIC_SQL,
                    [_theme_monthly_metric_parameters(row) for row in metrics_tuple],
                )
            if structures_tuple:
                connection.executemany(
                    _INSERT_THEME_MARKET_STRUCTURE_METRIC_SQL,
                    [_theme_market_structure_metric_parameters(row) for row in structures_tuple],
                )
            if growth_tuple:
                connection.executemany(
                    _INSERT_THEME_GROWTH_SOURCE_METRIC_SQL,
                    [_theme_growth_source_metric_parameters(row) for row in growth_tuple],
                )
            if dimensions_tuple:
                connection.executemany(
                    _INSERT_THEME_DIMENSION_MONTHLY_METRIC_SQL,
                    [_theme_dimension_monthly_metric_parameters(row) for row in dimensions_tuple],
                )
            if representative_tuple:
                connection.executemany(
                    _INSERT_THEME_REPRESENTATIVE_GAME_SQL,
                    [_theme_representative_game_parameters(row) for row in representative_tuple],
                )
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise

    def replace_theme_trend_score_range(
        self,
        rows: Sequence[ThemeTrendScore],
        *,
        target_periods: Sequence[SnapshotPeriodKey] | None = None,
    ) -> None:
        """Atomically replace score rows for the requested target months.

        ``target_periods`` allows a valid empty theme result to clear stale rows
        for a scorable target month while leaving every source and schema-v2 row
        untouched.
        """

        scores_tuple, period_keys = _validate_theme_trend_score_range(
            rows,
            target_periods=target_periods,
        )
        if not period_keys:
            return
        connection = self._require_initialized_connection()

        try:
            connection.execute("BEGIN TRANSACTION")
            for key in period_keys:
                connection.execute(
                    _DELETE_THEME_TREND_SCORES_SQL,
                    [
                        key.scope_name,
                        key.cadence,
                        key.period_start,
                        key.period_end,
                    ],
                )
            if scores_tuple:
                connection.executemany(
                    _INSERT_THEME_TREND_SCORE_SQL,
                    [_theme_trend_score_parameters(row) for row in scores_tuple],
                )
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise

    def replace_theme_model_range(
        self,
        trend_scores: Sequence[ThemeTrendScore],
        horizon_metrics: Sequence[ThemeHorizonMetric],
        model_summaries: Sequence[ThemeModelSummary],
        seasonality_profiles: Sequence[ThemeSeasonalityProfile],
        *,
        target_periods: Sequence[SnapshotPeriodKey],
        trend_target_periods: Sequence[SnapshotPeriodKey] | None = None,
    ) -> None:
        """Atomically replace all MODEL-002 outputs for requested periods."""

        payload = _validate_theme_model_range(
            trend_scores,
            horizon_metrics,
            model_summaries,
            seasonality_profiles,
            target_periods=target_periods,
            trend_target_periods=trend_target_periods,
        )
        (
            scores_tuple,
            horizons_tuple,
            summaries_tuple,
            seasonality_tuple,
            target_keys,
            score_target_keys,
        ) = payload
        connection = self._require_initialized_connection()
        _verify_model_summary_source_identities(connection, target_keys, summaries_tuple)

        try:
            connection.execute("BEGIN TRANSACTION")
            for key in target_keys:
                parameters = [
                    key.scope_name,
                    key.cadence,
                    key.period_start,
                    key.period_end,
                ]
                connection.execute(_DELETE_THEME_HORIZON_METRICS_SQL, parameters)
                connection.execute(_DELETE_THEME_MODEL_SUMMARIES_SQL, parameters)
                connection.execute(_DELETE_THEME_SEASONALITY_PROFILES_SQL, parameters)
            for key in score_target_keys:
                connection.execute(
                    _DELETE_THEME_TREND_SCORES_SQL,
                    [key.scope_name, key.cadence, key.period_start, key.period_end],
                )
            if scores_tuple:
                connection.executemany(
                    _INSERT_THEME_TREND_SCORE_SQL,
                    [_theme_trend_score_parameters(row) for row in scores_tuple],
                )
            if horizons_tuple:
                connection.executemany(
                    _INSERT_THEME_HORIZON_METRIC_SQL,
                    [_theme_horizon_metric_parameters(row) for row in horizons_tuple],
                )
            if summaries_tuple:
                connection.executemany(
                    _INSERT_THEME_MODEL_SUMMARY_SQL,
                    [_theme_model_summary_parameters(row) for row in summaries_tuple],
                )
            if seasonality_tuple:
                connection.executemany(
                    _INSERT_THEME_SEASONALITY_PROFILE_SQL,
                    [_theme_seasonality_profile_parameters(row) for row in seasonality_tuple],
                )
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise

    def replace_theme_backtest_range(
        self,
        outcomes: Sequence[ThemeLaunchWindowOutcome],
        feature_metrics: Sequence[ThemeBacktestFeatureMetric],
        segment_metrics: Sequence[ThemeBacktestSegmentMetric],
    ) -> None:
        """Atomically replace the three BACKTEST-001 output tables.

        All dataclass and registry validation runs before a storage connection
        is requested.  Source-identity checks then run before the transaction;
        only the supplied backtest range is deleted and replaced.
        """

        payload = _validate_theme_backtest_range(
            outcomes,
            feature_metrics,
            segment_metrics,
        )
        outcomes_tuple, features_tuple, segments_tuple, backtest_start, backtest_end = payload
        connection = self._require_initialized_connection()
        _verify_backtest_source_identities(connection, outcomes_tuple)
        _verify_backtest_outcome_periods(connection, outcomes_tuple)
        decision_periods = {
            (row.decision_period_start, row.decision_period_end) for row in outcomes_tuple
        }
        if not decision_periods:
            decision_period = backtest_start
            while decision_period <= backtest_end:
                decision_periods.add(
                    (decision_period, natural_month_end_for_storage(decision_period))
                )
                decision_period = month_shift_for_storage(decision_period, 1)

        try:
            connection.execute("BEGIN TRANSACTION")
            for period_start, period_end in sorted(decision_periods):
                connection.execute(
                    f"DELETE FROM {THEME_LAUNCH_WINDOW_OUTCOMES_TABLE} "
                    "WHERE scope_name = ? AND cadence = 'monthly' "
                    "AND decision_period_start = ? AND decision_period_end = ?",
                    [features_tuple[0].scope_name, period_start, period_end],
                )
            connection.execute(
                f"DELETE FROM {THEME_BACKTEST_FEATURE_METRICS_TABLE} "
                "WHERE scope_name = ? AND cadence = 'monthly' "
                "AND backtest_start = ? AND backtest_end = ? AND backtest_policy_version = ?",
                [
                    features_tuple[0].scope_name,
                    backtest_start,
                    backtest_end,
                    BACKTEST_POLICY_VERSION,
                ],
            )
            connection.execute(
                f"DELETE FROM {THEME_BACKTEST_SEGMENT_METRICS_TABLE} "
                "WHERE scope_name = ? AND cadence = 'monthly' "
                "AND backtest_start = ? AND backtest_end = ? AND backtest_policy_version = ?",
                [
                    features_tuple[0].scope_name,
                    backtest_start,
                    backtest_end,
                    BACKTEST_POLICY_VERSION,
                ],
            )
            if outcomes_tuple:
                connection.executemany(
                    _INSERT_THEME_LAUNCH_WINDOW_OUTCOME_SQL,
                    [_theme_launch_window_outcome_parameters(row) for row in outcomes_tuple],
                )
            connection.executemany(
                _INSERT_THEME_BACKTEST_FEATURE_METRIC_SQL,
                [_theme_backtest_feature_metric_parameters(row) for row in features_tuple],
            )
            if segments_tuple:
                connection.executemany(
                    _INSERT_THEME_BACKTEST_SEGMENT_METRIC_SQL,
                    [_theme_backtest_segment_metric_parameters(row) for row in segments_tuple],
                )
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise

        _verify_backtest_readback(
            connection,
            outcomes_tuple,
            features_tuple,
            segments_tuple,
            scope_name=features_tuple[0].scope_name,
            backtest_start=backtest_start,
            backtest_end=backtest_end,
        )

    def upsert_app_metadata(self, rows: Sequence[AppMetadataRow]) -> None:
        """Transaction-safely upsert normalized metadata rows by unified ID."""

        connection = self._require_initialized_connection()
        latest_by_id: dict[str, AppMetadataRow] = {}
        for row in rows:
            if not isinstance(row, AppMetadataRow):
                raise StorageValidationError("metadata rows must be AppMetadataRow values")
            latest_by_id[row.unified_app_id] = row

        if not latest_by_id:
            return

        try:
            connection.execute("BEGIN TRANSACTION")
            connection.executemany(
                _UPSERT_APP_METADATA_SQL,
                [_app_metadata_parameters(row) for row in latest_by_id.values()],
            )
            connection.execute("COMMIT")
        except Exception:
            _rollback(connection)
            raise

    def get_app_metadata(
        self,
        unified_app_ids: Sequence[object],
    ) -> Mapping[str, AppMetadataRow]:
        """Read available metadata rows for normalized, deduplicated IDs."""

        connection = self._require_initialized_connection()
        normalized_ids = normalize_opaque_id_sequence(unified_app_ids)
        if not normalized_ids:
            return {}

        placeholders = ", ".join("?" for _ in normalized_ids)
        rows = connection.execute(
            f"SELECT {_APP_METADATA_COLUMNS_SQL} FROM {APP_METADATA_TABLE} "
            f"WHERE unified_app_id IN ({placeholders})",
            list(normalized_ids),
        ).fetchall()
        rows_by_id = {
            metadata_row.unified_app_id: metadata_row
            for metadata_row in (_app_metadata_from_database_row(row) for row in rows)
        }
        return {app_id: rows_by_id[app_id] for app_id in normalized_ids if app_id in rows_by_id}

    def lookup_metadata_cache(
        self,
        unified_app_ids: Sequence[object],
        *,
        as_of: datetime,
        max_age_days: int | float = 14,
    ) -> MetadataCacheLookup:
        """Classify cached metadata as fresh, stale, or missing locally."""

        normalized_ids = normalize_opaque_id_sequence(unified_app_ids)
        as_of_value = require_timezone_aware(as_of, field_name="as_of")
        if (
            isinstance(max_age_days, bool)
            or not isinstance(max_age_days, (int, float))
            or not isfinite(float(max_age_days))
            or max_age_days < 0
        ):
            raise StorageValidationError("max_age_days must be a non-negative finite number")

        cached_rows = self.get_app_metadata(normalized_ids)
        max_age = timedelta(days=float(max_age_days))
        fresh_metadata_by_id: dict[str, AppMetadataRow] = {}
        stale_ids: list[str] = []
        missing_ids: list[str] = []
        ids_to_fetch: list[str] = []

        for app_id in normalized_ids:
            metadata = cached_rows.get(app_id)
            if metadata is None:
                missing_ids.append(app_id)
                ids_to_fetch.append(app_id)
                continue

            age = as_of_value - metadata.fetched_at
            if age <= max_age:
                fresh_metadata_by_id[app_id] = metadata
            else:
                stale_ids.append(app_id)
                ids_to_fetch.append(app_id)

        return MetadataCacheLookup(
            fresh_metadata_by_id=fresh_metadata_by_id,
            ids_to_fetch=tuple(ids_to_fetch),
            stale_ids=tuple(stale_ids),
            missing_ids=tuple(missing_ids),
        )

    def export_market_snapshots_to_parquet(self, path: str | Path) -> None:
        """Atomically export market snapshots to deterministic Parquet."""

        from .parquet import export_market_snapshots_to_parquet

        export_market_snapshots_to_parquet(self, path)

    def export_app_metadata_to_parquet(self, path: str | Path) -> None:
        """Atomically export app metadata to deterministic Parquet."""

        from .parquet import export_app_metadata_to_parquet

        export_app_metadata_to_parquet(self, path)

    def export_monthly_market_totals_to_parquet(self, path: str | Path) -> None:
        """Atomically export monthly totals to deterministic Parquet."""

        from .parquet import export_monthly_market_totals_to_parquet

        export_monthly_market_totals_to_parquet(self, path)

    def export_theme_monthly_metrics_to_parquet(self, path: str | Path) -> None:
        """Atomically export theme metrics to deterministic Parquet."""

        from .parquet import export_theme_monthly_metrics_to_parquet

        export_theme_monthly_metrics_to_parquet(self, path)

    def export_theme_market_structure_metrics_to_parquet(self, path: str | Path) -> None:
        """Atomically export V2 market-structure metrics to Parquet."""

        from .parquet import export_theme_market_structure_metrics_to_parquet

        export_theme_market_structure_metrics_to_parquet(self, path)

    def export_theme_growth_source_metrics_to_parquet(self, path: str | Path) -> None:
        """Atomically export V2 growth-source metrics to Parquet."""

        from .parquet import export_theme_growth_source_metrics_to_parquet

        export_theme_growth_source_metrics_to_parquet(self, path)

    def export_theme_dimension_monthly_metrics_to_parquet(self, path: str | Path) -> None:
        """Atomically export V2 dimension metrics to Parquet."""

        from .parquet import export_theme_dimension_monthly_metrics_to_parquet

        export_theme_dimension_monthly_metrics_to_parquet(self, path)

    def export_theme_representative_games_to_parquet(self, path: str | Path) -> None:
        """Atomically export V2 representative-game evidence to Parquet."""

        from .parquet import export_theme_representative_games_to_parquet

        export_theme_representative_games_to_parquet(self, path)

    def export_theme_trend_scores_to_parquet(self, path: str | Path) -> None:
        """Atomically export trend scores to deterministic Parquet."""

        from .parquet import export_theme_trend_scores_to_parquet

        export_theme_trend_scores_to_parquet(self, path)

    def export_theme_horizon_metrics_to_parquet(self, path: str | Path) -> None:
        """Atomically export MODEL-002 horizon metrics to Parquet."""

        from .parquet import export_theme_horizon_metrics_to_parquet

        export_theme_horizon_metrics_to_parquet(self, path)

    def export_theme_model_summaries_to_parquet(self, path: str | Path) -> None:
        """Atomically export MODEL-002 summaries to Parquet."""

        from .parquet import export_theme_model_summaries_to_parquet

        export_theme_model_summaries_to_parquet(self, path)

    def export_theme_seasonality_profiles_to_parquet(self, path: str | Path) -> None:
        """Atomically export MODEL-002 seasonality profiles to Parquet."""

        from .parquet import export_theme_seasonality_profiles_to_parquet

        export_theme_seasonality_profiles_to_parquet(self, path)

    def export_theme_launch_window_outcomes_to_parquet(self, path: str | Path) -> None:
        """Atomically export raw BACKTEST-001 outcomes to Parquet."""

        from .parquet import export_theme_launch_window_outcomes_to_parquet

        export_theme_launch_window_outcomes_to_parquet(self, path)

    def export_theme_backtest_feature_metrics_to_parquet(self, path: str | Path) -> None:
        """Atomically export BACKTEST-001 feature metrics to Parquet."""

        from .parquet import export_theme_backtest_feature_metrics_to_parquet

        export_theme_backtest_feature_metrics_to_parquet(self, path)

    def export_theme_backtest_segment_metrics_to_parquet(self, path: str | Path) -> None:
        """Atomically export BACKTEST-001 segment metrics to Parquet."""

        from .parquet import export_theme_backtest_segment_metrics_to_parquet

        export_theme_backtest_segment_metrics_to_parquet(self, path)

    def _require_storage_connection(self) -> duckdb.DuckDBPyConnection:
        """Return a connection for package-internal export operations."""

        return self._require_initialized_connection()

    def _require_open_connection(self) -> duckdb.DuckDBPyConnection:
        if self._connection is None:
            raise RepositoryNotOpenError()
        return self._connection

    def _require_connection_mode(self, expected: Literal["read-write", "read-only"]) -> None:
        if self._connection is None:
            raise RepositoryNotOpenError()
        if self._connection_mode != expected:
            raise RepositoryConnectionModeError(expected, self._connection_mode or "unknown")

    def _require_initialized_connection(self) -> duckdb.DuckDBPyConnection:
        connection = self._require_open_connection()
        if not self._schema_initialized:
            raise SchemaNotInitializedError()
        return connection

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _validate_market_snapshot_period(
    rows: Sequence[MarketSnapshotRow],
) -> tuple[tuple[MarketSnapshotRow, ...], SnapshotPeriodKey]:
    rows_tuple = tuple(rows)
    if not rows_tuple:
        raise StorageValidationError("market snapshot period must contain at least one row")
    if any(not isinstance(row, MarketSnapshotRow) for row in rows_tuple):
        raise StorageValidationError("market snapshot rows must be MarketSnapshotRow values")

    first_row = rows_tuple[0]
    period_key = first_row.period_key
    provenance = first_row.request_provenance
    for row in rows_tuple[1:]:
        if row.period_key != period_key:
            raise StorageValidationError("all market snapshot rows must share one period key")
        if row.request_provenance != provenance:
            raise StorageValidationError("all market snapshot rows must share request provenance")

    unified_ids = [row.unified_app_id for row in rows_tuple]
    if len(set(unified_ids)) != len(unified_ids):
        raise StorageValidationError("market snapshot unified_app_id values must be unique")

    ranks = [row.rank_position for row in rows_tuple]
    if len(set(ranks)) != len(ranks):
        raise StorageValidationError("market snapshot rank_position values must be unique")
    expected_ranks = list(range(1, len(rows_tuple) + 1))
    if sorted(ranks) != expected_ranks:
        raise StorageValidationError("market snapshot ranks must be contiguous and start at 1")

    return rows_tuple, period_key


def _market_snapshot_parameters(row: MarketSnapshotRow) -> tuple[object, ...]:
    return (
        row.scope_name,
        row.cadence,
        row.period_start,
        row.period_end,
        row.rank_position,
        row.source_app_id,
        row.unified_app_id,
        row.scope_country,
        row.device_type,
        row.category,
        row.data_model,
        row.source_date,
        row.source_country,
        row.current_units_value,
        row.units_absolute,
        row.comparison_units_value,
        row.units_delta,
        row.units_transformed_delta,
        row.current_revenue_value,
        row.revenue_absolute,
        row.comparison_revenue_value,
        row.revenue_delta,
        row.revenue_transformed_delta,
        row.absolute,
        row.delta,
        row.transformed_delta,
        row.game_theme,
        row.game_genre,
        row.game_subgenre,
        row.game_product_model,
        row.game_art_style,
        row.game_setting,
        row.earliest_release_date,
        row.release_date_ww,
        row.publisher_country,
        row.most_popular_country_by_revenue,
        row.is_unified_source_value,
        row.collected_at,
    )


def _app_metadata_parameters(row: AppMetadataRow) -> tuple[object, ...]:
    return (
        row.unified_app_id,
        row.name,
        row.publisher_display_name,
        row.publisher_resolution_source,
        row.android_app_id,
        row.ios_app_id,
        row.fetched_at,
    )


def _monthly_market_total_parameters(row: MonthlyMarketTotal) -> tuple[object, ...]:
    return (
        row.scope_name,
        row.cadence,
        row.period_start,
        row.period_end,
        row.snapshot_count,
        row.theme_present_count,
        row.theme_missing_count,
        row.metadata_coverage_count,
        row.units_absolute_coverage_count,
        row.units_absolute_sum,
        row.revenue_absolute_coverage_count,
        row.revenue_absolute_sum,
        row.calculated_at,
    )


def _theme_monthly_metric_parameters(row: ThemeMonthlyMetric) -> tuple[object, ...]:
    return (
        row.scope_name,
        row.cadence,
        row.period_start,
        row.period_end,
        row.game_theme,
        row.product_count,
        row.product_share,
        row.top_100_count,
        row.top_500_count,
        row.average_rank,
        row.median_rank,
        row.units_absolute_coverage_count,
        row.units_absolute_sum,
        row.units_absolute_share,
        row.revenue_absolute_coverage_count,
        row.revenue_absolute_sum,
        row.revenue_absolute_share,
        row.has_previous_month,
        row.new_entry_count,
        row.returning_product_count,
        row.new_entry_share,
        row.publisher_coverage_count,
        row.publisher_count,
        row.top_publisher_product_share,
        row.calculated_at,
    )


def _theme_market_structure_metric_parameters(
    row: ThemeMarketStructureMetric,
) -> tuple[object, ...]:
    return tuple(getattr(row, column) for column in THEME_MARKET_STRUCTURE_METRICS_COLUMNS)


def _theme_growth_source_metric_parameters(
    row: ThemeGrowthSourceMetric,
) -> tuple[object, ...]:
    return tuple(getattr(row, column) for column in THEME_GROWTH_SOURCE_METRICS_COLUMNS)


def _theme_dimension_monthly_metric_parameters(
    row: ThemeDimensionMonthlyMetric,
) -> tuple[object, ...]:
    return tuple(getattr(row, column) for column in THEME_DIMENSION_MONTHLY_METRICS_COLUMNS)


def _theme_representative_game_parameters(
    row: ThemeRepresentativeGame,
) -> tuple[object, ...]:
    return tuple(getattr(row, column) for column in THEME_REPRESENTATIVE_GAMES_COLUMNS)


def _theme_trend_score_parameters(row: ThemeTrendScore) -> tuple[object, ...]:
    return (
        row.scope_name,
        row.cadence,
        row.period_start,
        row.period_end,
        row.game_theme,
        row.window_start,
        row.window_month_count,
        row.active_months_6m,
        row.latest_product_count,
        row.is_actionable,
        row.exclusion_reason,
        row.latest_product_share,
        row.latest_units_absolute_share,
        row.latest_revenue_absolute_share,
        row.latest_new_entry_share,
        row.latest_median_rank,
        row.latest_publisher_count,
        row.latest_top_publisher_product_share,
        row.product_share_gain_3m,
        row.units_absolute_share_gain_3m,
        row.revenue_absolute_share_gain_3m,
        row.product_share_acceleration,
        row.units_absolute_share_acceleration,
        row.revenue_absolute_share_acceleration,
        row.recent3_new_entry_share,
        row.median_rank_improvement,
        row.publisher_count_gain_3m,
        row.units_absolute_overindex,
        row.revenue_absolute_overindex,
        row.recent3_units_coverage_ratio,
        row.recent3_revenue_coverage_ratio,
        row.latest_publisher_coverage_ratio,
        row.growth_score,
        row.acceleration_score,
        row.new_product_score,
        row.concentration_penalty,
        row.base_trend_score,
        row.confidence_score,
        row.trend_score,
        row.trend_rank,
        row.calculated_at,
    )


def _theme_horizon_metric_parameters(row: ThemeHorizonMetric) -> tuple[object, ...]:
    return tuple(getattr(row, column) for column in THEME_HORIZON_METRICS_COLUMNS)


def _theme_model_summary_parameters(row: ThemeModelSummary) -> tuple[object, ...]:
    return tuple(getattr(row, column) for column in THEME_MODEL_SUMMARIES_COLUMNS)


def _theme_seasonality_profile_parameters(
    row: ThemeSeasonalityProfile,
) -> tuple[object, ...]:
    return tuple(getattr(row, column) for column in THEME_SEASONALITY_PROFILES_COLUMNS)


def _theme_launch_window_outcome_parameters(
    row: ThemeLaunchWindowOutcome,
) -> tuple[object, ...]:
    return tuple(getattr(row, column) for column in THEME_LAUNCH_WINDOW_OUTCOMES_COLUMNS)


def _theme_backtest_feature_metric_parameters(
    row: ThemeBacktestFeatureMetric,
) -> tuple[object, ...]:
    return tuple(getattr(row, column) for column in THEME_BACKTEST_FEATURE_METRICS_COLUMNS)


def _theme_backtest_segment_metric_parameters(
    row: ThemeBacktestSegmentMetric,
) -> tuple[object, ...]:
    return tuple(getattr(row, column) for column in THEME_BACKTEST_SEGMENT_METRICS_COLUMNS)


def _market_snapshot_from_database_row(row: Sequence[object]) -> MarketSnapshotRow:
    values = dict(zip(MARKET_SNAPSHOT_COLUMNS, row, strict=True))
    return MarketSnapshotRow(**cast(Any, values))


def _app_metadata_from_database_row(row: Sequence[object]) -> AppMetadataRow:
    values = dict(zip(APP_METADATA_COLUMNS, row, strict=True))
    return AppMetadataRow(**cast(Any, values))


def _monthly_market_total_from_database_row(row: Sequence[object]) -> MonthlyMarketTotal:
    values = dict(zip(MONTHLY_MARKET_TOTALS_COLUMNS, row, strict=True))
    return MonthlyMarketTotal(**cast(Any, values))


def _theme_monthly_metric_from_database_row(row: Sequence[object]) -> ThemeMonthlyMetric:
    values = dict(zip(THEME_MONTHLY_METRICS_COLUMNS, row, strict=True))
    return ThemeMonthlyMetric(**cast(Any, values))


def _theme_market_structure_metric_from_database_row(
    row: Sequence[object],
) -> ThemeMarketStructureMetric:
    values = dict(zip(THEME_MARKET_STRUCTURE_METRICS_COLUMNS, row, strict=True))
    return ThemeMarketStructureMetric(**cast(Any, values))


def _theme_growth_source_metric_from_database_row(
    row: Sequence[object],
) -> ThemeGrowthSourceMetric:
    values = dict(zip(THEME_GROWTH_SOURCE_METRICS_COLUMNS, row, strict=True))
    return ThemeGrowthSourceMetric(**cast(Any, values))


def _theme_dimension_monthly_metric_from_database_row(
    row: Sequence[object],
) -> ThemeDimensionMonthlyMetric:
    values = dict(zip(THEME_DIMENSION_MONTHLY_METRICS_COLUMNS, row, strict=True))
    return ThemeDimensionMonthlyMetric(**cast(Any, values))


def _theme_representative_game_from_database_row(
    row: Sequence[object],
) -> ThemeRepresentativeGame:
    values = dict(zip(THEME_REPRESENTATIVE_GAMES_COLUMNS, row, strict=True))
    return ThemeRepresentativeGame(**cast(Any, values))


def _theme_trend_score_from_database_row(row: Sequence[object]) -> ThemeTrendScore:
    values = dict(zip(THEME_TREND_SCORES_COLUMNS, row, strict=True))
    return ThemeTrendScore(**cast(Any, values))


def _theme_horizon_metric_from_database_row(row: Sequence[object]) -> ThemeHorizonMetric:
    values = dict(zip(THEME_HORIZON_METRICS_COLUMNS, row, strict=True))
    return ThemeHorizonMetric(**cast(Any, values))


def _theme_model_summary_from_database_row(row: Sequence[object]) -> ThemeModelSummary:
    values = dict(zip(THEME_MODEL_SUMMARIES_COLUMNS, row, strict=True))
    return ThemeModelSummary(**cast(Any, values))


def _theme_seasonality_profile_from_database_row(
    row: Sequence[object],
) -> ThemeSeasonalityProfile:
    values = dict(zip(THEME_SEASONALITY_PROFILES_COLUMNS, row, strict=True))
    return ThemeSeasonalityProfile(**cast(Any, values))


def _theme_launch_window_outcome_from_database_row(
    row: Sequence[object],
) -> ThemeLaunchWindowOutcome:
    values = dict(zip(THEME_LAUNCH_WINDOW_OUTCOMES_COLUMNS, row, strict=True))
    return ThemeLaunchWindowOutcome(**cast(Any, values))


def _theme_backtest_feature_metric_from_database_row(
    row: Sequence[object],
) -> ThemeBacktestFeatureMetric:
    values = dict(zip(THEME_BACKTEST_FEATURE_METRICS_COLUMNS, row, strict=True))
    return ThemeBacktestFeatureMetric(**cast(Any, values))


def _theme_backtest_segment_metric_from_database_row(
    row: Sequence[object],
) -> ThemeBacktestSegmentMetric:
    values = dict(zip(THEME_BACKTEST_SEGMENT_METRICS_COLUMNS, row, strict=True))
    return ThemeBacktestSegmentMetric(**cast(Any, values))


def _validate_theme_monthly_range(
    monthly_totals: Sequence[MonthlyMarketTotal],
    theme_metrics: Sequence[ThemeMonthlyMetric],
) -> tuple[
    tuple[MonthlyMarketTotal, ...],
    tuple[ThemeMonthlyMetric, ...],
    tuple[SnapshotPeriodKey, ...],
]:
    totals_tuple = tuple(monthly_totals)
    metrics_tuple = tuple(theme_metrics)
    if not totals_tuple:
        raise StorageValidationError("monthly aggregation replacement must contain totals")
    if any(not isinstance(row, MonthlyMarketTotal) for row in totals_tuple):
        raise StorageValidationError("monthly totals must be MonthlyMarketTotal values")
    if any(not isinstance(row, ThemeMonthlyMetric) for row in metrics_tuple):
        raise StorageValidationError("theme metrics must be ThemeMonthlyMetric values")
    try:
        totals_tuple = tuple(replace(row) for row in totals_tuple)
        metrics_tuple = tuple(replace(row) for row in metrics_tuple)
    except Exception as error:
        raise StorageValidationError("derived rows failed validation") from error

    period_keys = tuple(
        SnapshotPeriodKey(
            scope_name=row.scope_name,
            cadence=row.cadence,  # type: ignore[arg-type]
            period_start=row.period_start,
            period_end=row.period_end,
        )
        for row in totals_tuple
    )
    if len(set(period_keys)) != len(period_keys):
        raise StorageValidationError("monthly totals must have unique period identities")
    period_key_set = set(period_keys)
    metric_keys = [
        SnapshotPeriodKey(
            scope_name=row.scope_name,
            cadence=row.cadence,  # type: ignore[arg-type]
            period_start=row.period_start,
            period_end=row.period_end,
        )
        for row in metrics_tuple
    ]
    metric_identity_set = {
        (key, row.game_theme) for key, row in zip(metric_keys, metrics_tuple, strict=True)
    }
    if len(metric_identity_set) != len(metrics_tuple):
        raise StorageValidationError("theme metrics must have unique identities")
    if any(key not in period_key_set for key in metric_keys):
        raise StorageValidationError("theme metrics must belong to the replacement periods")
    return totals_tuple, metrics_tuple, period_keys


def _validate_theme_opportunity_range(
    monthly_totals: Sequence[MonthlyMarketTotal],
    theme_metrics: Sequence[ThemeMonthlyMetric],
    structures: Sequence[ThemeMarketStructureMetric],
    growth_sources: Sequence[ThemeGrowthSourceMetric],
    dimensions: Sequence[ThemeDimensionMonthlyMetric],
    representative_games: Sequence[ThemeRepresentativeGame],
) -> tuple[
    tuple[MonthlyMarketTotal, ...],
    tuple[ThemeMonthlyMetric, ...],
    tuple[ThemeMarketStructureMetric, ...],
    tuple[ThemeGrowthSourceMetric, ...],
    tuple[ThemeDimensionMonthlyMetric, ...],
    tuple[ThemeRepresentativeGame, ...],
    tuple[SnapshotPeriodKey, ...],
]:
    totals_tuple = tuple(monthly_totals)
    metrics_tuple = tuple(theme_metrics)
    structures_tuple = tuple(structures)
    growth_tuple = tuple(growth_sources)
    dimensions_tuple = tuple(dimensions)
    representative_tuple = tuple(representative_games)
    if not totals_tuple:
        raise StorageValidationError("opportunity replacement must contain monthly totals")
    expected_types = (
        (totals_tuple, MonthlyMarketTotal, "monthly totals"),
        (metrics_tuple, ThemeMonthlyMetric, "theme metrics"),
        (structures_tuple, ThemeMarketStructureMetric, "market structure metrics"),
        (growth_tuple, ThemeGrowthSourceMetric, "growth-source metrics"),
        (dimensions_tuple, ThemeDimensionMonthlyMetric, "dimension metrics"),
        (representative_tuple, ThemeRepresentativeGame, "representative games"),
    )
    for values, expected_type, label in expected_types:
        if any(not isinstance(row, expected_type) for row in values):
            raise StorageValidationError(f"{label} contain an invalid typed row")
    if any(row.evidence_rank > DEFAULT_REPRESENTATIVE_GAME_LIMIT for row in representative_tuple):
        raise StorageValidationError(
            f"representative evidence ranks must not exceed {DEFAULT_REPRESENTATIVE_GAME_LIMIT}"
        )
    try:
        totals_tuple = tuple(replace(row) for row in totals_tuple)
        metrics_tuple = tuple(replace(row) for row in metrics_tuple)
        structures_tuple = tuple(replace(row) for row in structures_tuple)
        growth_tuple = tuple(replace(row) for row in growth_tuple)
        dimensions_tuple = tuple(replace(row) for row in dimensions_tuple)
        representative_tuple = tuple(replace(row) for row in representative_tuple)
    except Exception as error:
        raise StorageValidationError("opportunity rows failed validation") from error

    period_keys = tuple(_period_key_from_total(row) for row in totals_tuple)
    if len(set(period_keys)) != len(period_keys):
        raise StorageValidationError("opportunity totals must have unique period identities")
    period_key_set = set(period_keys)
    metric_keys = tuple(_period_key_from_theme_metric(row) for row in metrics_tuple)
    theme_identities = {
        (key, row.game_theme) for key, row in zip(metric_keys, metrics_tuple, strict=True)
    }
    if len(theme_identities) != len(metrics_tuple):
        raise StorageValidationError("theme metrics must have unique identities")
    if any(key not in period_key_set for key in metric_keys):
        raise StorageValidationError("theme metrics must belong to replacement periods")

    structure_keys = tuple(_period_key_from_opportunity_row(row) for row in structures_tuple)
    structure_identities = {
        (key, row.game_theme) for key, row in zip(structure_keys, structures_tuple, strict=True)
    }
    if len(structure_identities) != len(structures_tuple):
        raise StorageValidationError("market structure metrics must have unique identities")
    growth_keys = tuple(_period_key_from_opportunity_row(row) for row in growth_tuple)
    growth_identities = {
        (key, row.game_theme) for key, row in zip(growth_keys, growth_tuple, strict=True)
    }
    if len(growth_identities) != len(growth_tuple):
        raise StorageValidationError("growth-source metrics must have unique identities")
    if structure_identities != theme_identities or growth_identities != theme_identities:
        raise StorageValidationError("V2 theme identities must match AGG-001 theme identities")

    dimension_keys = tuple(_period_key_from_opportunity_row(row) for row in dimensions_tuple)
    dimension_identities = {
        (key, row.game_theme, row.dimension_type, row.dimension_value)
        for key, row in zip(dimension_keys, dimensions_tuple, strict=True)
    }
    if len(dimension_identities) != len(dimensions_tuple):
        raise StorageValidationError("dimension metrics must have unique identities")
    if any(
        (key, row.game_theme) not in theme_identities
        for key, row in zip(dimension_keys, dimensions_tuple, strict=True)
    ):
        raise StorageValidationError("dimension metrics must match AGG-001 theme identities")

    representative_keys = tuple(
        _period_key_from_opportunity_row(row) for row in representative_tuple
    )
    representative_identities = {
        (key, row.game_theme, row.evidence_type, row.evidence_rank)
        for key, row in zip(representative_keys, representative_tuple, strict=True)
    }
    if len(representative_identities) != len(representative_tuple):
        raise StorageValidationError("representative games must have unique identities")
    if any(
        (key, row.game_theme) not in theme_identities
        for key, row in zip(representative_keys, representative_tuple, strict=True)
    ):
        raise StorageValidationError("representative games must match AGG-001 theme identities")
    evidence_groups: dict[tuple[SnapshotPeriodKey, str, str], list[int]] = defaultdict(list)
    for key, row in zip(representative_keys, representative_tuple, strict=True):
        evidence_groups[(key, row.game_theme, row.evidence_type)].append(row.evidence_rank)
    for ranks in evidence_groups.values():
        if sorted(ranks) != list(range(1, len(ranks) + 1)):
            raise StorageValidationError("representative evidence ranks must be contiguous")

    for _values, keys in (
        (structures_tuple, structure_keys),
        (growth_tuple, growth_keys),
        (dimensions_tuple, dimension_keys),
        (representative_tuple, representative_keys),
    ):
        if any(key not in period_key_set for key in keys):
            raise StorageValidationError("opportunity rows must belong to replacement periods")
    return (
        totals_tuple,
        metrics_tuple,
        structures_tuple,
        growth_tuple,
        dimensions_tuple,
        representative_tuple,
        period_keys,
    )


def _validate_theme_model_range(
    trend_scores: Sequence[ThemeTrendScore],
    horizon_metrics: Sequence[ThemeHorizonMetric],
    model_summaries: Sequence[ThemeModelSummary],
    seasonality_profiles: Sequence[ThemeSeasonalityProfile],
    *,
    target_periods: Sequence[SnapshotPeriodKey],
    trend_target_periods: Sequence[SnapshotPeriodKey] | None,
) -> tuple[
    tuple[ThemeTrendScore, ...],
    tuple[ThemeHorizonMetric, ...],
    tuple[ThemeModelSummary, ...],
    tuple[ThemeSeasonalityProfile, ...],
    tuple[SnapshotPeriodKey, ...],
    tuple[SnapshotPeriodKey, ...],
]:
    """Validate a MODEL-002 payload without opening or mutating DuckDB."""

    scores_tuple = tuple(trend_scores)
    horizons_tuple = tuple(horizon_metrics)
    summaries_tuple = tuple(model_summaries)
    seasonality_tuple = tuple(seasonality_profiles)
    typed_values = (
        (scores_tuple, ThemeTrendScore, "trend scores"),
        (horizons_tuple, ThemeHorizonMetric, "horizon metrics"),
        (summaries_tuple, ThemeModelSummary, "model summaries"),
        (seasonality_tuple, ThemeSeasonalityProfile, "seasonality profiles"),
    )
    for values, expected_type, label in typed_values:
        if any(not isinstance(row, expected_type) for row in values):
            raise StorageValidationError(f"{label} contain an invalid typed row")
    try:
        scores_tuple = tuple(replace(row) for row in scores_tuple)
        horizons_tuple = tuple(replace(row) for row in horizons_tuple)
        summaries_tuple = tuple(replace(row) for row in summaries_tuple)
        seasonality_tuple = tuple(replace(row) for row in seasonality_tuple)
    except Exception as error:
        raise StorageValidationError("MODEL-002 rows failed validation") from error

    target_keys = _validate_target_periods(target_periods)
    if not target_keys:
        raise StorageValidationError("MODEL-002 target periods must not be empty")
    target_key_set = set(target_keys)

    summary_keys = tuple(_period_key_from_model_summary(row) for row in summaries_tuple)
    summary_identities = {
        _model_theme_identity(key, row.game_theme)
        for key, row in zip(summary_keys, summaries_tuple, strict=True)
    }
    if len(summary_identities) != len(summaries_tuple):
        raise StorageValidationError("model summaries must have unique identities")
    if any(key not in target_key_set for key in summary_keys):
        raise StorageValidationError("model summaries must belong to target periods")
    summary_by_identity = {
        _model_theme_identity(key, row.game_theme): row
        for key, row in zip(summary_keys, summaries_tuple, strict=True)
    }

    horizon_keys = tuple(_period_key_from_model_horizon(row) for row in horizons_tuple)
    horizon_identities = {
        (*_model_theme_identity(key, row.game_theme), row.horizon_month_count, row.metric_name)
        for key, row in zip(horizon_keys, horizons_tuple, strict=True)
    }
    if len(horizon_identities) != len(horizons_tuple):
        raise StorageValidationError("horizon metrics must have unique identities")
    if any(key not in target_key_set for key in horizon_keys):
        raise StorageValidationError("horizon metrics must belong to target periods")
    if any(
        _model_theme_identity(key, row.game_theme) not in summary_by_identity
        for key, row in zip(horizon_keys, horizons_tuple, strict=True)
    ):
        raise StorageValidationError("horizon metrics must reference a model summary")
    horizon_groups: dict[tuple[SnapshotPeriodKey, str, int], list[ThemeHorizonMetric]] = (
        defaultdict(list)
    )
    for key, row in zip(horizon_keys, horizons_tuple, strict=True):
        horizon_groups[(key, row.game_theme, row.horizon_month_count)].append(row)
    for rows in horizon_groups.values():
        active_months = {row.active_month_count for row in rows}
        if len(active_months) != 1:
            raise StorageValidationError("horizon active-month evidence must be consistent")

    seasonality_keys = tuple(_period_key_from_model_seasonality(row) for row in seasonality_tuple)
    seasonality_identities = {
        (*_model_theme_identity(key, row.game_theme), row.metric_name, row.calendar_month)
        for key, row in zip(seasonality_keys, seasonality_tuple, strict=True)
    }
    if len(seasonality_identities) != len(seasonality_tuple):
        raise StorageValidationError("seasonality profiles must have unique identities")
    if any(key not in target_key_set for key in seasonality_keys):
        raise StorageValidationError("seasonality profiles must belong to target periods")
    if any(
        _model_theme_identity(key, row.game_theme) not in summary_by_identity
        for key, row in zip(seasonality_keys, seasonality_tuple, strict=True)
    ):
        raise StorageValidationError("seasonality profiles must reference a model summary")
    seasonality_groups: defaultdict[
        tuple[SnapshotPeriodKey, str, str], list[ThemeSeasonalityProfile]
    ] = defaultdict(list)
    for key, seasonality_row in zip(seasonality_keys, seasonality_tuple, strict=True):
        seasonality_groups[(key, seasonality_row.game_theme, seasonality_row.metric_name)].append(
            seasonality_row
        )
    for (
        group_key,
        group_theme,
        _metric_name,
    ), seasonality_group_rows in seasonality_groups.items():
        if len(seasonality_group_rows) != 12:
            raise StorageValidationError("each seasonality profile must contain twelve rows")
        if {row.calendar_month for row in seasonality_group_rows} != set(range(1, 13)):
            raise StorageValidationError(
                "each seasonality profile must contain calendar months one through twelve"
            )
        profile_metadata = {
            (
                row.history_start,
                row.history_month_count,
                row.complete_year_count,
                row.observation_count,
                row.calculated_at,
            )
            for row in seasonality_group_rows
        }
        if len(profile_metadata) != 1:
            raise StorageValidationError("seasonality profile metadata must be consistent")
        profile = seasonality_group_rows[0]
        if profile.complete_year_count * 12 != profile.history_month_count:
            raise StorageValidationError("seasonality complete-year metadata is inconsistent")
        profile_summary = summary_by_identity[_model_theme_identity(group_key, group_theme)]
        if (
            profile_summary.seasonality_history_month_count != profile.history_month_count
            or profile_summary.seasonality_complete_year_count != profile.complete_year_count
        ):
            raise StorageValidationError("seasonality profile metadata must match model summary")
        if sum(row.is_peak_month for row in seasonality_group_rows) != 1:
            raise StorageValidationError("each seasonality profile must have one peak month")
        if sum(row.is_trough_month for row in seasonality_group_rows) != 1:
            raise StorageValidationError("each seasonality profile must have one trough month")
        if not isclose(
            sum(row.seasonal_index for row in seasonality_group_rows) / 12,
            1.0,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise StorageValidationError("each seasonality profile must average approximately one")

    score_keys = tuple(_period_key_from_trend_score(row) for row in scores_tuple)
    score_identities = {
        _model_theme_identity(key, row.game_theme)
        for key, row in zip(score_keys, scores_tuple, strict=True)
    }
    if len(score_identities) != len(scores_tuple):
        raise StorageValidationError("trend scores must have unique identities")
    if any(key not in target_key_set for key in score_keys):
        raise StorageValidationError("trend scores must belong to target periods")
    for key, score_row in zip(score_keys, scores_tuple, strict=True):
        summary = summary_by_identity.get(_model_theme_identity(key, score_row.game_theme))
        if summary is None or not summary.has_6m_history:
            raise StorageValidationError("legacy trend scores require a summary with 6M history")

    score_target_keys = (
        _validate_target_periods(trend_target_periods)
        if trend_target_periods is not None
        else tuple(dict.fromkeys(score_keys))
    )
    if any(key not in target_key_set for key in score_target_keys):
        raise StorageValidationError("trend target periods must belong to model target periods")
    if any(
        not any(
            key == summary_key and summary.has_6m_history
            for summary_key, summary in zip(summary_keys, summaries_tuple, strict=True)
        )
        for key in score_target_keys
    ):
        raise StorageValidationError("trend target periods require 6M summary history")

    timestamps = [
        row.calculated_at
        for rows in (scores_tuple, horizons_tuple, summaries_tuple, seasonality_tuple)
        for row in rows
    ]
    if timestamps and len(set(timestamps)) != 1:
        raise StorageValidationError("all MODEL-002 rows must use one calculated_at timestamp")
    return (
        scores_tuple,
        horizons_tuple,
        summaries_tuple,
        seasonality_tuple,
        target_keys,
        score_target_keys,
    )


def _validate_theme_backtest_range(
    outcomes: Sequence[ThemeLaunchWindowOutcome],
    feature_metrics: Sequence[ThemeBacktestFeatureMetric],
    segment_metrics: Sequence[ThemeBacktestSegmentMetric],
) -> tuple[
    tuple[ThemeLaunchWindowOutcome, ...],
    tuple[ThemeBacktestFeatureMetric, ...],
    tuple[ThemeBacktestSegmentMetric, ...],
    date,
    date,
]:
    """Validate a complete BACKTEST-001 payload without storage access."""

    outcomes_tuple = tuple(outcomes)
    features_tuple = tuple(feature_metrics)
    segments_tuple = tuple(segment_metrics)
    if not features_tuple:
        raise StorageValidationError("backtest feature metrics must not be empty")
    if any(not isinstance(row, ThemeLaunchWindowOutcome) for row in outcomes_tuple):
        raise StorageValidationError("backtest outcomes contain an invalid typed row")
    if any(not isinstance(row, ThemeBacktestFeatureMetric) for row in features_tuple):
        raise StorageValidationError("backtest feature metrics contain an invalid typed row")
    if any(not isinstance(row, ThemeBacktestSegmentMetric) for row in segments_tuple):
        raise StorageValidationError("backtest segment metrics contain an invalid typed row")
    try:
        outcomes_tuple = tuple(replace(row) for row in outcomes_tuple)
        features_tuple = tuple(replace(row) for row in features_tuple)
        segments_tuple = tuple(replace(row) for row in segments_tuple)
    except Exception as error:
        raise StorageValidationError("backtest rows failed validation") from error

    first_feature = features_tuple[0]
    scope_name = first_feature.scope_name
    backtest_start = first_feature.backtest_start
    backtest_end = first_feature.backtest_end
    calculated_timestamps = {row.calculated_at for row in features_tuple}
    if len(calculated_timestamps) != 1:
        raise StorageValidationError("backtest rows must use one calculated_at timestamp")
    if any(
        row.scope_name != scope_name
        or row.cadence != "monthly"
        or row.backtest_start != backtest_start
        or row.backtest_end != backtest_end
        or row.backtest_policy_version != BACKTEST_POLICY_VERSION
        for row in features_tuple
    ):
        raise StorageValidationError("feature metrics must use one range and policy")
    expected_feature_identities = {
        (
            scope_name,
            "monthly",
            backtest_start,
            backtest_end,
            horizon,
            definition.feature_name,
            outcome_name,
            BACKTEST_POLICY_VERSION,
        )
        for horizon in BACKTEST_OUTCOME_HORIZONS
        for definition in FEATURE_DEFINITIONS
        for outcome_name in PRIMARY_OUTCOME_NAMES
    }
    feature_identities = {row.identity for row in features_tuple}
    if (
        len(features_tuple) != len(expected_feature_identities)
        or feature_identities != expected_feature_identities
    ):
        raise StorageValidationError("backtest feature metrics must contain the exact registry")

    outcome_identities = {row.identity for row in outcomes_tuple}
    if len(outcome_identities) != len(outcomes_tuple):
        raise StorageValidationError("backtest outcomes must have unique identities")
    segment_identities = {row.identity for row in segments_tuple}
    if len(segment_identities) != len(segments_tuple):
        raise StorageValidationError("backtest segment metrics must have unique identities")
    for outcome_row in outcomes_tuple:
        if outcome_row.scope_name != scope_name or outcome_row.cadence != "monthly":
            raise StorageValidationError("backtest outcomes have incompatible scope")
        if not backtest_start <= outcome_row.decision_period_start <= backtest_end:
            raise StorageValidationError("backtest outcome decision is outside the requested range")
        if not backtest_start <= outcome_row.outcome_period_start <= backtest_end:
            raise StorageValidationError("backtest outcome period is outside the requested range")
        if outcome_row.calculated_at != next(iter(calculated_timestamps)):
            raise StorageValidationError("backtest rows must use one calculated_at timestamp")
    for segment_row in segments_tuple:
        if (
            segment_row.scope_name != scope_name
            or segment_row.cadence != "monthly"
            or segment_row.backtest_start != backtest_start
            or segment_row.backtest_end != backtest_end
            or segment_row.backtest_policy_version != BACKTEST_POLICY_VERSION
        ):
            raise StorageValidationError("segment metrics must use one range and policy")
        if segment_row.calculated_at != next(iter(calculated_timestamps)):
            raise StorageValidationError("backtest rows must use one calculated_at timestamp")
    return outcomes_tuple, features_tuple, segments_tuple, backtest_start, backtest_end


def _verify_backtest_source_identities(
    connection: duckdb.DuckDBPyConnection,
    outcomes: Sequence[ThemeLaunchWindowOutcome],
) -> None:
    """Ensure every raw row references accepted decision-month source rows."""

    for row in outcomes:
        identity_parameters = [
            row.scope_name,
            row.cadence,
            row.decision_period_start,
            row.decision_period_end,
            row.game_theme,
        ]
        checks = (
            (
                "theme_model_summaries",
                "SELECT 1 FROM theme_model_summaries "
                "WHERE scope_name = ? AND cadence = ? AND period_start = ? "
                "AND period_end = ? AND game_theme = ? AND has_6m_history",
            ),
            (
                "theme_trend_scores",
                "SELECT 1 FROM theme_trend_scores "
                "WHERE scope_name = ? AND cadence = ? AND period_start = ? "
                "AND period_end = ? AND game_theme = ?",
            ),
            (
                "theme_market_structure_metrics",
                "SELECT 1 FROM theme_market_structure_metrics "
                "WHERE scope_name = ? AND cadence = ? AND period_start = ? "
                "AND period_end = ? AND game_theme = ?",
            ),
            (
                "theme_growth_source_metrics",
                "SELECT 1 FROM theme_growth_source_metrics "
                "WHERE scope_name = ? AND cadence = ? AND period_start = ? "
                "AND period_end = ? AND game_theme = ?",
            ),
        )
        for _table_name, query in checks:
            if connection.execute(query, identity_parameters).fetchone() is None:
                raise StorageValidationError("backtest outcome source identity verification failed")


def _verify_backtest_outcome_periods(
    connection: duckdb.DuckDBPyConnection,
    outcomes: Sequence[ThemeLaunchWindowOutcome],
) -> None:
    expected_periods = {
        (row.scope_name, row.cadence, row.outcome_period_start, row.outcome_period_end)
        for row in outcomes
    }
    if not expected_periods:
        return
    available = {
        (str(row[0]), str(row[1]), row[2], row[3])
        for row in connection.execute(
            "SELECT scope_name, cadence, period_start, period_end FROM monthly_market_totals"
        ).fetchall()
    }
    if not expected_periods.issubset(available):
        raise StorageValidationError("backtest outcome month is missing from monthly totals")


def _verify_backtest_readback(
    connection: duckdb.DuckDBPyConnection,
    outcomes: Sequence[ThemeLaunchWindowOutcome],
    features: Sequence[ThemeBacktestFeatureMetric],
    segments: Sequence[ThemeBacktestSegmentMetric],
    *,
    scope_name: str,
    backtest_start: date,
    backtest_end: date,
) -> None:
    raw_rows = connection.execute(
        f"SELECT {_THEME_LAUNCH_WINDOW_OUTCOMES_COLUMNS_SQL} "
        f"FROM {THEME_LAUNCH_WINDOW_OUTCOMES_TABLE} "
        "WHERE scope_name = ? AND cadence = 'monthly' "
        "AND decision_period_start >= ? AND decision_period_end <= ? "
        "ORDER BY decision_period_start, decision_period_end, game_theme, outcome_horizon_months",
        [scope_name, backtest_start, backtest_end],
    ).fetchall()
    actual_outcomes = tuple(_theme_launch_window_outcome_from_database_row(row) for row in raw_rows)
    if set(actual_outcomes) != set(outcomes) or len(actual_outcomes) != len(outcomes):
        raise StorageValidationError("backtest outcome readback verification failed")

    feature_rows = connection.execute(
        f"SELECT {_THEME_BACKTEST_FEATURE_METRICS_COLUMNS_SQL} "
        f"FROM {THEME_BACKTEST_FEATURE_METRICS_TABLE} "
        "WHERE scope_name = ? AND cadence = 'monthly' AND backtest_start = ? AND backtest_end = ? "
        "AND backtest_policy_version = ? "
        "ORDER BY outcome_horizon_months, feature_name, outcome_name",
        [scope_name, backtest_start, backtest_end, BACKTEST_POLICY_VERSION],
    ).fetchall()
    actual_features = tuple(
        _theme_backtest_feature_metric_from_database_row(row) for row in feature_rows
    )
    if set(actual_features) != set(features) or len(actual_features) != len(features):
        raise StorageValidationError("backtest feature readback verification failed")

    segment_rows = connection.execute(
        f"SELECT {_THEME_BACKTEST_SEGMENT_METRICS_COLUMNS_SQL} "
        f"FROM {THEME_BACKTEST_SEGMENT_METRICS_TABLE} "
        "WHERE scope_name = ? AND cadence = 'monthly' AND backtest_start = ? AND backtest_end = ? "
        "AND backtest_policy_version = ? "
        "ORDER BY outcome_horizon_months, segment_name, segment_value, outcome_name",
        [scope_name, backtest_start, backtest_end, BACKTEST_POLICY_VERSION],
    ).fetchall()
    actual_segments = tuple(
        _theme_backtest_segment_metric_from_database_row(row) for row in segment_rows
    )
    if set(actual_segments) != set(segments) or len(actual_segments) != len(segments):
        raise StorageValidationError("backtest segment readback verification failed")
    timestamps = {
        row[0]
        for row in connection.execute(
            f"SELECT calculated_at FROM {THEME_BACKTEST_FEATURE_METRICS_TABLE} "
            "WHERE scope_name = ? AND cadence = 'monthly' "
            "AND backtest_start = ? AND backtest_end = ?",
            [scope_name, backtest_start, backtest_end],
        ).fetchall()
    }
    if timestamps != {features[0].calculated_at}:
        raise StorageValidationError("backtest timestamp readback verification failed")


def _verify_model_summary_source_identities(
    connection: duckdb.DuckDBPyConnection,
    target_keys: Sequence[SnapshotPeriodKey],
    summaries: Sequence[ThemeModelSummary],
) -> None:
    expected: set[tuple[str, str, date, date, str]] = set()
    for key in target_keys:
        rows = connection.execute(
            "SELECT scope_name, cadence, period_start, period_end, game_theme "
            "FROM theme_market_structure_metrics "
            "WHERE scope_name = ? AND cadence = ? AND period_start = ? AND period_end = ?",
            [key.scope_name, key.cadence, key.period_start, key.period_end],
        ).fetchall()
        expected.update((str(row[0]), str(row[1]), row[2], row[3], str(row[4])) for row in rows)
    actual = {
        (row.scope_name, row.cadence, row.period_start, row.period_end, row.game_theme)
        for row in summaries
    }
    if actual != expected:
        raise StorageValidationError("model summaries must match AGG-002 theme identities")


def _period_key_from_theme_metric(row: ThemeMonthlyMetric) -> SnapshotPeriodKey:
    return SnapshotPeriodKey(
        scope_name=row.scope_name,
        cadence="monthly",
        period_start=row.period_start,
        period_end=row.period_end,
    )


def _period_key_from_trend_score(row: ThemeTrendScore) -> SnapshotPeriodKey:
    return SnapshotPeriodKey(
        scope_name=row.scope_name,
        cadence="monthly",
        period_start=row.period_start,
        period_end=row.period_end,
    )


def _period_key_from_model_summary(row: ThemeModelSummary) -> SnapshotPeriodKey:
    return SnapshotPeriodKey(
        scope_name=row.scope_name,
        cadence="monthly",
        period_start=row.period_start,
        period_end=row.period_end,
    )


def _period_key_from_model_horizon(row: ThemeHorizonMetric) -> SnapshotPeriodKey:
    return SnapshotPeriodKey(
        scope_name=row.scope_name,
        cadence="monthly",
        period_start=row.period_start,
        period_end=row.period_end,
    )


def _period_key_from_model_seasonality(row: ThemeSeasonalityProfile) -> SnapshotPeriodKey:
    return SnapshotPeriodKey(
        scope_name=row.scope_name,
        cadence="monthly",
        period_start=row.period_start,
        period_end=row.period_end,
    )


def _model_theme_identity(
    key: SnapshotPeriodKey,
    game_theme: str,
) -> tuple[str, str, date, date, str]:
    return (key.scope_name, key.cadence, key.period_start, key.period_end, game_theme)


def _period_key_from_total(row: MonthlyMarketTotal) -> SnapshotPeriodKey:
    return SnapshotPeriodKey(
        scope_name=row.scope_name,
        cadence="monthly",
        period_start=row.period_start,
        period_end=row.period_end,
    )


def _period_key_from_opportunity_row(
    row: ThemeMarketStructureMetric
    | ThemeGrowthSourceMetric
    | ThemeDimensionMonthlyMetric
    | ThemeRepresentativeGame,
) -> SnapshotPeriodKey:
    return SnapshotPeriodKey(
        scope_name=row.scope_name,
        cadence="monthly",
        period_start=row.period_start,
        period_end=row.period_end,
    )


def _validate_theme_trend_score_range(
    rows: Sequence[ThemeTrendScore],
    *,
    target_periods: Sequence[SnapshotPeriodKey] | None,
) -> tuple[tuple[ThemeTrendScore, ...], tuple[SnapshotPeriodKey, ...]]:
    scores_tuple = tuple(rows)
    if any(not isinstance(row, ThemeTrendScore) for row in scores_tuple):
        raise StorageValidationError("trend scores must be ThemeTrendScore values")
    try:
        scores_tuple = tuple(replace(row) for row in scores_tuple)
    except Exception as error:
        raise StorageValidationError("trend scores failed validation") from error

    row_period_keys = tuple(
        SnapshotPeriodKey(
            scope_name=row.scope_name,
            cadence=row.cadence,  # type: ignore[arg-type]
            period_start=row.period_start,
            period_end=row.period_end,
        )
        for row in scores_tuple
    )
    target_keys = _validate_target_periods(target_periods)
    if target_keys:
        target_key_set = set(target_keys)
        if any(key not in target_key_set for key in row_period_keys):
            raise StorageValidationError("trend scores must belong to target periods")
    period_keys = tuple(dict.fromkeys((*target_keys, *row_period_keys)))
    score_identities = {
        (key, row.game_theme) for key, row in zip(row_period_keys, scores_tuple, strict=True)
    }
    if len(score_identities) != len(scores_tuple):
        raise StorageValidationError("trend scores must have unique identities")
    return scores_tuple, period_keys


def _validate_target_periods(
    target_periods: Sequence[SnapshotPeriodKey] | None,
) -> tuple[SnapshotPeriodKey, ...]:
    if target_periods is None:
        return ()
    values = tuple(target_periods)
    if any(not isinstance(key, SnapshotPeriodKey) or key.cadence != "monthly" for key in values):
        raise StorageValidationError("target periods must be monthly SnapshotPeriodKey values")
    if len(set(values)) != len(values):
        raise StorageValidationError("target periods must have unique identities")
    return values


def _derived_filter_sql(
    *,
    scope_name: str | None,
    cadence: str,
    period_start: date | None,
    period_end: date | None,
    game_theme: str | None = None,
    dimension_type: str | None = None,
    dimension_value: str | None = None,
    evidence_type: str | None = None,
    horizon_month_count: int | None = None,
    metric_name: str | None = None,
    calendar_month: int | None = None,
) -> tuple[str, list[object]]:
    if cadence != "monthly":
        raise StorageValidationError("derived tables only support monthly cadence")
    clauses = ["cadence = ?"]
    parameters: list[object] = [cadence]
    if scope_name is not None:
        clauses.append("scope_name = ?")
        parameters.append(scope_name)
    if period_start is not None:
        clauses.append("period_start >= ?")
        parameters.append(period_start)
    if period_end is not None:
        clauses.append("period_end <= ?")
        parameters.append(period_end)
    if game_theme is not None:
        clauses.append("game_theme = ?")
        parameters.append(game_theme)
    if dimension_type is not None:
        clauses.append("dimension_type = ?")
        parameters.append(dimension_type)
    if dimension_value is not None:
        clauses.append("dimension_value = ?")
        parameters.append(dimension_value)
    if evidence_type is not None:
        clauses.append("evidence_type = ?")
        parameters.append(evidence_type)
    if horizon_month_count is not None:
        clauses.append("horizon_month_count = ?")
        parameters.append(horizon_month_count)
    if metric_name is not None:
        clauses.append("metric_name = ?")
        parameters.append(metric_name)
    if calendar_month is not None:
        clauses.append("calendar_month = ?")
        parameters.append(calendar_month)
    return "WHERE " + " AND ".join(clauses), parameters


def _backtest_filter_sql(
    *,
    scope_name: str | None,
    cadence: str,
    start_column: str,
    end_column: str,
    period_start: date | None,
    period_end: date | None,
    game_theme: str | None = None,
    outcome_horizon_months: int | None = None,
    feature_name: str | None = None,
    feature_group: str | None = None,
    outcome_name: str | None = None,
    segment_name: str | None = None,
    segment_value: str | None = None,
) -> tuple[str, list[object]]:
    if cadence != "monthly":
        raise StorageValidationError("backtest tables only support monthly cadence")
    if start_column not in {"decision_period_start", "backtest_start"}:
        raise StorageValidationError("invalid backtest start filter")
    if end_column not in {"decision_period_end", "backtest_end"}:
        raise StorageValidationError("invalid backtest end filter")
    clauses = ["cadence = ?"]
    parameters: list[object] = [cadence]
    if scope_name is not None:
        clauses.append("scope_name = ?")
        parameters.append(scope_name)
    if period_start is not None:
        clauses.append(f"{start_column} >= ?")
        parameters.append(period_start)
    if period_end is not None:
        clauses.append(f"{end_column} <= ?")
        parameters.append(period_end)
    optional_filters = (
        ("game_theme", game_theme),
        ("outcome_horizon_months", outcome_horizon_months),
        ("feature_name", feature_name),
        ("feature_group", feature_group),
        ("outcome_name", outcome_name),
        ("segment_name", segment_name),
        ("segment_value", segment_value),
    )
    for column_name, value in optional_filters:
        if value is not None:
            clauses.append(f"{column_name} = ?")
            parameters.append(value)
    return "WHERE " + " AND ".join(clauses), parameters


def _rollback(connection: duckdb.DuckDBPyConnection) -> None:
    try:
        connection.execute("ROLLBACK")
    except duckdb.Error:
        pass
