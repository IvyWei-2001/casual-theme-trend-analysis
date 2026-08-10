"""Versioned DuckDB schema for source and derived analytical rows."""

from __future__ import annotations

from collections.abc import Iterable

import duckdb

from .errors import SchemaInitializationError, UnsupportedSchemaVersionError

CURRENT_SCHEMA_VERSION = 2

SCHEMA_MIGRATIONS_TABLE = "schema_migrations"
APP_METADATA_TABLE = "app_metadata"
MARKET_SNAPSHOTS_TABLE = "market_snapshots"
MONTHLY_MARKET_TOTALS_TABLE = "monthly_market_totals"
THEME_MONTHLY_METRICS_TABLE = "theme_monthly_metrics"

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
MONTHLY_MARKET_TOTALS_COLUMNS: tuple[str, ...] = (
    "scope_name",
    "cadence",
    "period_start",
    "period_end",
    "snapshot_count",
    "theme_present_count",
    "theme_missing_count",
    "metadata_coverage_count",
    "units_absolute_coverage_count",
    "units_absolute_sum",
    "revenue_absolute_coverage_count",
    "revenue_absolute_sum",
    "calculated_at",
)
THEME_MONTHLY_METRICS_COLUMNS: tuple[str, ...] = (
    "scope_name",
    "cadence",
    "period_start",
    "period_end",
    "game_theme",
    "product_count",
    "product_share",
    "top_100_count",
    "top_500_count",
    "average_rank",
    "median_rank",
    "units_absolute_coverage_count",
    "units_absolute_sum",
    "units_absolute_share",
    "revenue_absolute_coverage_count",
    "revenue_absolute_sum",
    "revenue_absolute_share",
    "has_previous_month",
    "new_entry_count",
    "returning_product_count",
    "new_entry_share",
    "publisher_coverage_count",
    "publisher_count",
    "top_publisher_product_share",
    "calculated_at",
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

_CREATE_MONTHLY_MARKET_TOTALS_SQL = """
CREATE TABLE IF NOT EXISTS monthly_market_totals (
    scope_name VARCHAR NOT NULL,
    cadence VARCHAR NOT NULL CHECK (cadence = 'monthly'),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    snapshot_count INTEGER NOT NULL CHECK (snapshot_count >= 0),
    theme_present_count INTEGER NOT NULL CHECK (theme_present_count >= 0),
    theme_missing_count INTEGER NOT NULL CHECK (theme_missing_count >= 0),
    metadata_coverage_count INTEGER NOT NULL CHECK (metadata_coverage_count >= 0),
    units_absolute_coverage_count INTEGER NOT NULL CHECK (
        units_absolute_coverage_count >= 0
    ),
    units_absolute_sum DOUBLE NULL,
    revenue_absolute_coverage_count INTEGER NOT NULL CHECK (
        revenue_absolute_coverage_count >= 0
    ),
    revenue_absolute_sum DOUBLE NULL,
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (scope_name, cadence, period_start, period_end),
    CHECK (period_start <= period_end),
    CHECK (theme_present_count + theme_missing_count = snapshot_count),
    CHECK (metadata_coverage_count <= snapshot_count),
    CHECK (units_absolute_coverage_count <= snapshot_count),
    CHECK (revenue_absolute_coverage_count <= snapshot_count),
    CHECK (
        (units_absolute_coverage_count = 0 AND units_absolute_sum IS NULL)
        OR (units_absolute_coverage_count > 0 AND units_absolute_sum IS NOT NULL)
    ),
    CHECK (
        (revenue_absolute_coverage_count = 0 AND revenue_absolute_sum IS NULL)
        OR (revenue_absolute_coverage_count > 0 AND revenue_absolute_sum IS NOT NULL)
    )
)
"""

_CREATE_THEME_MONTHLY_METRICS_SQL = """
CREATE TABLE IF NOT EXISTS theme_monthly_metrics (
    scope_name VARCHAR NOT NULL,
    cadence VARCHAR NOT NULL CHECK (cadence = 'monthly'),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    game_theme VARCHAR NOT NULL,
    product_count INTEGER NOT NULL CHECK (product_count > 0),
    product_share DOUBLE NOT NULL CHECK (product_share >= 0 AND product_share <= 1),
    top_100_count INTEGER NOT NULL CHECK (top_100_count >= 0),
    top_500_count INTEGER NOT NULL CHECK (top_500_count >= 0),
    average_rank DOUBLE NOT NULL,
    median_rank DOUBLE NOT NULL,
    units_absolute_coverage_count INTEGER NOT NULL CHECK (
        units_absolute_coverage_count >= 0
    ),
    units_absolute_sum DOUBLE NULL,
    units_absolute_share DOUBLE NULL,
    revenue_absolute_coverage_count INTEGER NOT NULL CHECK (
        revenue_absolute_coverage_count >= 0
    ),
    revenue_absolute_sum DOUBLE NULL,
    revenue_absolute_share DOUBLE NULL,
    has_previous_month BOOLEAN NOT NULL,
    new_entry_count INTEGER NULL,
    returning_product_count INTEGER NULL,
    new_entry_share DOUBLE NULL,
    publisher_coverage_count INTEGER NOT NULL CHECK (publisher_coverage_count >= 0),
    publisher_count INTEGER NOT NULL CHECK (publisher_count >= 0),
    top_publisher_product_share DOUBLE NULL,
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (scope_name, cadence, period_start, period_end, game_theme),
    CHECK (period_start <= period_end),
    CHECK (top_100_count <= product_count),
    CHECK (top_500_count <= product_count),
    CHECK (publisher_coverage_count <= product_count),
    CHECK (publisher_count <= publisher_coverage_count),
    CHECK (units_absolute_coverage_count <= product_count),
    CHECK (revenue_absolute_coverage_count <= product_count),
    CHECK (
        (units_absolute_coverage_count = 0 AND units_absolute_sum IS NULL)
        OR (units_absolute_coverage_count > 0 AND units_absolute_sum IS NOT NULL)
    ),
    CHECK (
        (revenue_absolute_coverage_count = 0 AND revenue_absolute_sum IS NULL)
        OR (revenue_absolute_coverage_count > 0 AND revenue_absolute_sum IS NOT NULL)
    ),
    CHECK (
        units_absolute_share IS NULL
        OR (units_absolute_share >= 0 AND units_absolute_share <= 1)
    ),
    CHECK (
        revenue_absolute_share IS NULL
        OR (revenue_absolute_share >= 0 AND revenue_absolute_share <= 1)
    ),
    CHECK (new_entry_count IS NULL OR new_entry_count >= 0),
    CHECK (returning_product_count IS NULL OR returning_product_count >= 0),
    CHECK (new_entry_share IS NULL OR (new_entry_share >= 0 AND new_entry_share <= 1)),
    CHECK (
        top_publisher_product_share IS NULL
        OR (top_publisher_product_share >= 0 AND top_publisher_product_share <= 1)
    ),
    CHECK (
        (publisher_coverage_count = 0 AND top_publisher_product_share IS NULL)
        OR (publisher_coverage_count > 0 AND top_publisher_product_share IS NOT NULL)
    ),
    CHECK (
        has_previous_month
        OR (
            new_entry_count IS NULL
            AND returning_product_count IS NULL
            AND new_entry_share IS NULL
        )
    ),
    CHECK (
        NOT has_previous_month
        OR (
            new_entry_count IS NOT NULL
            AND returning_product_count IS NOT NULL
            AND new_entry_count + returning_product_count = product_count
        )
    )
)
"""

_V1_TABLE_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (SCHEMA_MIGRATIONS_TABLE, _CREATE_SCHEMA_MIGRATIONS_SQL, SCHEMA_MIGRATIONS_COLUMNS),
    (APP_METADATA_TABLE, _CREATE_APP_METADATA_SQL, APP_METADATA_COLUMNS),
    (MARKET_SNAPSHOTS_TABLE, _CREATE_MARKET_SNAPSHOTS_SQL, MARKET_SNAPSHOT_COLUMNS),
)
_V2_TABLE_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    MONTHLY_MARKET_TOTALS_TABLE,
    _CREATE_MONTHLY_MARKET_TOTALS_SQL,
    MONTHLY_MARKET_TOTALS_COLUMNS,
), (
    THEME_MONTHLY_METRICS_TABLE,
    _CREATE_THEME_MONTHLY_METRICS_SQL,
    THEME_MONTHLY_METRICS_COLUMNS,
),
_TABLE_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    *_V1_TABLE_DEFINITIONS,
    *_V2_TABLE_DEFINITIONS,
)


def initialize_schema(connection: duckdb.DuckDBPyConnection) -> None:
    """Create or sequentially migrate the supported schema without rebuilding tables."""

    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute(_CREATE_SCHEMA_MIGRATIONS_SQL)
        _assert_table_columns(connection, SCHEMA_MIGRATIONS_TABLE, SCHEMA_MIGRATIONS_COLUMNS)

        newest_version = _get_newest_schema_version(connection)
        if newest_version > CURRENT_SCHEMA_VERSION:
            raise UnsupportedSchemaVersionError(newest_version, CURRENT_SCHEMA_VERSION)

        if newest_version < 1:
            _apply_version_one(connection)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                [1],
            )

        _assert_table_definitions(connection, _V1_TABLE_DEFINITIONS)

        if newest_version < 2:
            _apply_version_two(connection)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                [2],
            )

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


def _apply_version_one(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(_CREATE_APP_METADATA_SQL)
    connection.execute(_CREATE_MARKET_SNAPSHOTS_SQL)


def _apply_version_two(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(_CREATE_MONTHLY_MARKET_TOTALS_SQL)
    connection.execute(_CREATE_THEME_MONTHLY_METRICS_SQL)


def _assert_required_tables(connection: duckdb.DuckDBPyConnection) -> None:
    _assert_table_definitions(connection, _TABLE_DEFINITIONS)


def _assert_table_definitions(
    connection: duckdb.DuckDBPyConnection,
    definitions: Iterable[tuple[str, str, tuple[str, ...]]],
) -> None:
    for table_name, _create_sql, expected_columns in definitions:
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
