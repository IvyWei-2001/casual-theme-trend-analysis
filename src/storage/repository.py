"""Repository operations for the versioned local DuckDB store."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from math import isfinite
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self, cast

import duckdb

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
    THEME_DIMENSION_MONTHLY_METRICS_COLUMNS,
    THEME_DIMENSION_MONTHLY_METRICS_TABLE,
    THEME_GROWTH_SOURCE_METRICS_COLUMNS,
    THEME_GROWTH_SOURCE_METRICS_TABLE,
    THEME_MARKET_STRUCTURE_METRICS_COLUMNS,
    THEME_MARKET_STRUCTURE_METRICS_TABLE,
    THEME_MONTHLY_METRICS_COLUMNS,
    THEME_MONTHLY_METRICS_TABLE,
    THEME_REPRESENTATIVE_GAMES_COLUMNS,
    THEME_REPRESENTATIVE_GAMES_TABLE,
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
    if any(
        row.evidence_rank > DEFAULT_REPRESENTATIVE_GAME_LIMIT
        for row in representative_tuple
    ):
        raise StorageValidationError(
            "representative evidence ranks must not exceed "
            f"{DEFAULT_REPRESENTATIVE_GAME_LIMIT}"
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


def _period_key_from_theme_metric(row: ThemeMonthlyMetric) -> SnapshotPeriodKey:
    return SnapshotPeriodKey(
        scope_name=row.scope_name,
        cadence="monthly",
        period_start=row.period_start,
        period_end=row.period_end,
    )


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
    return "WHERE " + " AND ".join(clauses), parameters


def _rollback(connection: duckdb.DuckDBPyConnection) -> None:
    try:
        connection.execute("ROLLBACK")
    except duckdb.Error:
        pass
