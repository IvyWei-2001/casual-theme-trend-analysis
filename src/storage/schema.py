"""Versioned DuckDB schema for market snapshots and metadata cache rows."""

from __future__ import annotations

from collections.abc import Iterable

import duckdb

from .errors import SchemaInitializationError, UnsupportedSchemaVersionError

CURRENT_SCHEMA_VERSION = 1

SCHEMA_MIGRATIONS_TABLE = "schema_migrations"
APP_METADATA_TABLE = "app_metadata"
MARKET_SNAPSHOTS_TABLE = "market_snapshots"

SCHEMA_MIGRATIONS_COLUMNS: tuple[str, ...] = ("version", "applied_at")
APP_METADATA_COLUMNS: tuple[str, ...] = (
    "unified_app_id",
    "name",
    "publisher_display_name",
    "publisher_resolution_source",
    "android_app_id",
    "ios_app_id",
    "fetched_at",
)
MARKET_SNAPSHOT_COLUMNS: tuple[str, ...] = (
    "scope_name",
    "cadence",
    "period_start",
    "period_end",
    "rank_position",
    "source_app_id",
    "unified_app_id",
    "scope_country",
    "device_type",
    "category",
    "data_model",
    "source_date",
    "source_country",
    "current_units_value",
    "units_absolute",
    "comparison_units_value",
    "units_delta",
    "units_transformed_delta",
    "current_revenue_value",
    "revenue_absolute",
    "comparison_revenue_value",
    "revenue_delta",
    "revenue_transformed_delta",
    "absolute",
    "delta",
    "transformed_delta",
    "game_theme",
    "game_genre",
    "game_subgenre",
    "game_product_model",
    "game_art_style",
    "game_setting",
    "earliest_release_date",
    "release_date_ww",
    "publisher_country",
    "most_popular_country_by_revenue",
    "is_unified_source_value",
    "collected_at",
)

_CREATE_SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL
)
"""

_CREATE_APP_METADATA_SQL = """
CREATE TABLE IF NOT EXISTS app_metadata (
    unified_app_id VARCHAR PRIMARY KEY,
    name VARCHAR NULL,
    publisher_display_name VARCHAR NULL,
    publisher_resolution_source VARCHAR NOT NULL CHECK (
        publisher_resolution_source IN (
            'android_publisher_ids',
            'publisher_name',
            'itunes_publisher_ids',
            'unavailable'
        )
    ),
    android_app_id VARCHAR NULL,
    ios_app_id VARCHAR NULL,
    fetched_at TIMESTAMPTZ NOT NULL
)
"""

_CREATE_MARKET_SNAPSHOTS_SQL = """
CREATE TABLE IF NOT EXISTS market_snapshots (
    scope_name VARCHAR NOT NULL,
    cadence VARCHAR NOT NULL CHECK (cadence IN ('monthly', 'weekly')),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    rank_position INTEGER NOT NULL CHECK (rank_position > 0),
    source_app_id VARCHAR NOT NULL,
    unified_app_id VARCHAR NOT NULL,
    scope_country VARCHAR NOT NULL,
    device_type VARCHAR NOT NULL,
    category INTEGER NOT NULL CHECK (category > 0),
    data_model VARCHAR NOT NULL,
    source_date TIMESTAMPTZ NOT NULL,
    source_country VARCHAR NULL,
    current_units_value DOUBLE NULL,
    units_absolute DOUBLE NULL,
    comparison_units_value DOUBLE NULL,
    units_delta DOUBLE NULL,
    units_transformed_delta DOUBLE NULL,
    current_revenue_value DOUBLE NULL,
    revenue_absolute DOUBLE NULL,
    comparison_revenue_value DOUBLE NULL,
    revenue_delta DOUBLE NULL,
    revenue_transformed_delta DOUBLE NULL,
    absolute DOUBLE NULL,
    delta DOUBLE NULL,
    transformed_delta DOUBLE NULL,
    game_theme VARCHAR NULL,
    game_genre VARCHAR NULL,
    game_subgenre VARCHAR NULL,
    game_product_model VARCHAR NULL,
    game_art_style VARCHAR NULL,
    game_setting VARCHAR NULL,
    earliest_release_date DATE NULL,
    release_date_ww DATE NULL,
    publisher_country VARCHAR NULL,
    most_popular_country_by_revenue VARCHAR NULL,
    is_unified_source_value VARCHAR NULL,
    collected_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (scope_name, cadence, period_start, period_end, unified_app_id),
    UNIQUE (scope_name, cadence, period_start, period_end, rank_position),
    CHECK (period_start <= period_end)
)
"""

_TABLE_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (SCHEMA_MIGRATIONS_TABLE, _CREATE_SCHEMA_MIGRATIONS_SQL, SCHEMA_MIGRATIONS_COLUMNS),
    (APP_METADATA_TABLE, _CREATE_APP_METADATA_SQL, APP_METADATA_COLUMNS),
    (MARKET_SNAPSHOTS_TABLE, _CREATE_MARKET_SNAPSHOTS_SQL, MARKET_SNAPSHOT_COLUMNS),
)


def initialize_schema(connection: duckdb.DuckDBPyConnection) -> None:
    """Create or verify schema version 1 without destructive migration."""

    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(_CREATE_SCHEMA_MIGRATIONS_SQL)
        _assert_table_columns(connection, SCHEMA_MIGRATIONS_TABLE, SCHEMA_MIGRATIONS_COLUMNS)

        newest_version = _get_newest_schema_version(connection)
        if newest_version > CURRENT_SCHEMA_VERSION:
            raise UnsupportedSchemaVersionError(newest_version, CURRENT_SCHEMA_VERSION)

        if newest_version < CURRENT_SCHEMA_VERSION:
            connection.execute(_CREATE_APP_METADATA_SQL)
            connection.execute(_CREATE_MARKET_SNAPSHOTS_SQL)
            _assert_required_tables(connection)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                [CURRENT_SCHEMA_VERSION],
            )
        else:
            _assert_required_tables(connection)

        connection.execute("COMMIT")
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except duckdb.Error:
            pass
        raise


def _get_newest_schema_version(connection: duckdb.DuckDBPyConnection) -> int:
    result = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()
    if result is None or result[0] is None:
        return 0
    return int(result[0])


def _assert_required_tables(connection: duckdb.DuckDBPyConnection) -> None:
    for table_name, _create_sql, expected_columns in _TABLE_DEFINITIONS:
        _assert_table_columns(connection, table_name, expected_columns)


def _assert_table_columns(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    expected_columns: Iterable[str],
) -> None:
    rows = connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    actual_columns = tuple(str(row[1]) for row in rows)
    expected = tuple(expected_columns)
    if actual_columns != expected:
        raise SchemaInitializationError(
            f"table {table_name!r} has incompatible columns; "
            f"expected {expected!r}, found {actual_columns!r}"
        )
