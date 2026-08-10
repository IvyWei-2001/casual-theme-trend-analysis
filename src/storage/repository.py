"""Repository operations for the versioned local DuckDB store."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path
from types import TracebackType
from typing import Any, Self, cast

import duckdb

from .connection import open_duckdb_connection
from .errors import (
    RepositoryNotOpenError,
    SchemaNotInitializedError,
    StorageValidationError,
)
from .models import (
    AppMetadataRow,
    MarketSnapshotRow,
    MetadataCacheLookup,
    SnapshotPeriodKey,
    normalize_id_sequence,
    require_timezone_aware,
)
from .schema import (
    APP_METADATA_COLUMNS,
    APP_METADATA_TABLE,
    MARKET_SNAPSHOT_COLUMNS,
    MARKET_SNAPSHOTS_TABLE,
    initialize_schema,
)

_APP_METADATA_COLUMNS_SQL = ", ".join(APP_METADATA_COLUMNS)
_APP_METADATA_PLACEHOLDERS_SQL = ", ".join("?" for _ in APP_METADATA_COLUMNS)
_MARKET_SNAPSHOT_COLUMNS_SQL = ", ".join(MARKET_SNAPSHOT_COLUMNS)
_MARKET_SNAPSHOT_PLACEHOLDERS_SQL = ", ".join("?" for _ in MARKET_SNAPSHOT_COLUMNS)

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


class DuckDBRepository:
    """Open, initialize, and query the local analytical DuckDB store."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._schema_initialized = False

    def open(self) -> duckdb.DuckDBPyConnection:
        """Open the configured database without creating business tables."""

        if self._connection is None:
            self._connection = open_duckdb_connection(self.database_path)
            self._schema_initialized = False
        return self._connection

    def close(self) -> None:
        """Close the connection if it is open; repeated calls are safe."""

        if self._connection is not None:
            self._connection.close()
            self._connection = None
        self._schema_initialized = False

    def initialize_schema(self) -> None:
        """Explicitly create or verify the supported schema version."""

        connection = self._require_open_connection()
        initialize_schema(connection)
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
        normalized_ids = normalize_id_sequence(unified_app_ids)
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
        return {
            app_id: rows_by_id[app_id]
            for app_id in normalized_ids
            if app_id in rows_by_id
        }

    def lookup_metadata_cache(
        self,
        unified_app_ids: Sequence[object],
        *,
        as_of: datetime,
        max_age_days: int | float = 14,
    ) -> MetadataCacheLookup:
        """Classify cached metadata as fresh, stale, or missing locally."""

        normalized_ids = normalize_id_sequence(unified_app_ids)
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

    def _require_storage_connection(self) -> duckdb.DuckDBPyConnection:
        """Return a connection for package-internal export operations."""

        return self._require_initialized_connection()

    def _require_open_connection(self) -> duckdb.DuckDBPyConnection:
        if self._connection is None:
            raise RepositoryNotOpenError()
        return self._connection

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
            raise StorageValidationError(
                "all market snapshot rows must share request provenance"
            )

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


def _market_snapshot_from_database_row(row: Sequence[object]) -> MarketSnapshotRow:
    values = dict(zip(MARKET_SNAPSHOT_COLUMNS, row, strict=True))
    return MarketSnapshotRow(**cast(Any, values))


def _app_metadata_from_database_row(row: Sequence[object]) -> AppMetadataRow:
    values = dict(zip(APP_METADATA_COLUMNS, row, strict=True))
    return AppMetadataRow(**cast(Any, values))


def _rollback(connection: duckdb.DuckDBPyConnection) -> None:
    try:
        connection.execute("ROLLBACK")
    except duckdb.Error:
        pass
