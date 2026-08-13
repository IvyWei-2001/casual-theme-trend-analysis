"""Versioned DuckDB schema for source and derived analytical rows."""

# SQL constraint declarations intentionally keep each column definition
# together; the schema contract supplies the authoritative explicit order.
# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Iterable

import duckdb

from .errors import SchemaInitializationError, UnsupportedSchemaVersionError

CURRENT_SCHEMA_VERSION = 4

SCHEMA_MIGRATIONS_TABLE = "schema_migrations"
APP_METADATA_TABLE = "app_metadata"
MARKET_SNAPSHOTS_TABLE = "market_snapshots"
MONTHLY_MARKET_TOTALS_TABLE = "monthly_market_totals"
THEME_MONTHLY_METRICS_TABLE = "theme_monthly_metrics"
THEME_TREND_SCORES_TABLE = "theme_trend_scores"
THEME_MARKET_STRUCTURE_METRICS_TABLE = "theme_market_structure_metrics"
THEME_GROWTH_SOURCE_METRICS_TABLE = "theme_growth_source_metrics"
THEME_DIMENSION_MONTHLY_METRICS_TABLE = "theme_dimension_monthly_metrics"
THEME_REPRESENTATIVE_GAMES_TABLE = "theme_representative_games"

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
THEME_TREND_SCORES_COLUMNS: tuple[str, ...] = (
    "scope_name",
    "cadence",
    "period_start",
    "period_end",
    "game_theme",
    "window_start",
    "window_month_count",
    "active_months_6m",
    "latest_product_count",
    "is_actionable",
    "exclusion_reason",
    "latest_product_share",
    "latest_units_absolute_share",
    "latest_revenue_absolute_share",
    "latest_new_entry_share",
    "latest_median_rank",
    "latest_publisher_count",
    "latest_top_publisher_product_share",
    "product_share_gain_3m",
    "units_absolute_share_gain_3m",
    "revenue_absolute_share_gain_3m",
    "product_share_acceleration",
    "units_absolute_share_acceleration",
    "revenue_absolute_share_acceleration",
    "recent3_new_entry_share",
    "median_rank_improvement",
    "publisher_count_gain_3m",
    "units_absolute_overindex",
    "revenue_absolute_overindex",
    "recent3_units_coverage_ratio",
    "recent3_revenue_coverage_ratio",
    "latest_publisher_coverage_ratio",
    "growth_score",
    "acceleration_score",
    "new_product_score",
    "concentration_penalty",
    "base_trend_score",
    "confidence_score",
    "trend_score",
    "trend_rank",
    "calculated_at",
)
THEME_MARKET_STRUCTURE_METRICS_COLUMNS: tuple[str, ...] = (
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
    "downloads_coverage_count",
    "downloads_coverage_ratio",
    "downloads_sum",
    "downloads_share",
    "downloads_mean_per_covered_product",
    "downloads_median_per_covered_product",
    "downloads_top_1_product_share",
    "downloads_top_3_product_share",
    "downloads_top_10_product_share",
    "downloads_product_hhi",
    "revenue_usd_coverage_count",
    "revenue_usd_coverage_ratio",
    "revenue_usd_sum",
    "revenue_usd_share",
    "revenue_usd_mean_per_covered_product",
    "revenue_usd_median_per_covered_product",
    "revenue_usd_top_1_product_share",
    "revenue_usd_top_3_product_share",
    "revenue_usd_top_10_product_share",
    "revenue_usd_product_hhi",
    "publisher_coverage_count",
    "publisher_coverage_ratio",
    "publisher_count",
    "top_1_publisher_product_share",
    "top_3_publisher_product_share",
    "publisher_product_hhi",
    "publisher_downloads_coverage_count",
    "publisher_downloads_coverage_ratio",
    "top_1_publisher_downloads_share",
    "top_3_publisher_downloads_share",
    "publisher_downloads_hhi",
    "publisher_revenue_usd_coverage_count",
    "publisher_revenue_usd_coverage_ratio",
    "top_1_publisher_revenue_usd_share",
    "top_3_publisher_revenue_usd_share",
    "publisher_revenue_usd_hhi",
    "release_date_ww_coverage_count",
    "release_date_ww_coverage_ratio",
    "release_date_ww_valid_age_count",
    "release_date_ww_future_count",
    "median_product_age_days",
    "downloads_top_10_median_product_age_days",
    "revenue_usd_top_10_median_product_age_days",
    "calculated_at",
)
THEME_GROWTH_SOURCE_METRICS_COLUMNS: tuple[str, ...] = (
    "scope_name",
    "cadence",
    "period_start",
    "period_end",
    "game_theme",
    "has_previous_month",
    "previous_product_count",
    "current_product_count",
    "product_count_change",
    "market_new_entry_count",
    "market_returning_product_count",
    "theme_entry_count",
    "theme_exit_count",
    "continuing_theme_product_count",
    "market_new_entry_share",
    "theme_entry_share",
    "market_new_entry_top_100_count",
    "market_new_entry_top_100_rate",
    "market_new_entry_top_500_count",
    "market_new_entry_top_500_rate",
    "top_100_current_count",
    "top_100_previous_count",
    "top_100_entry_count",
    "top_100_exit_count",
    "top_100_retained_count",
    "top_100_turnover_rate",
    "top_500_current_count",
    "top_500_previous_count",
    "top_500_entry_count",
    "top_500_exit_count",
    "top_500_retained_count",
    "top_500_turnover_rate",
    "downloads_top_10_current_count",
    "downloads_top_10_retained_count",
    "downloads_top_10_retention_rate",
    "revenue_usd_top_10_current_count",
    "revenue_usd_top_10_retained_count",
    "revenue_usd_top_10_retention_rate",
    "downloads_current_coverage_count",
    "downloads_previous_coverage_count",
    "downloads_decomposition_complete",
    "downloads_current_sum",
    "downloads_previous_sum",
    "downloads_mom_change",
    "downloads_mom_growth_rate",
    "downloads_market_new_entry_sum",
    "downloads_market_new_entry_share_of_current",
    "downloads_theme_entry_contribution",
    "downloads_continuing_contribution",
    "downloads_theme_exit_contribution",
    "downloads_positive_contribution_sum",
    "downloads_negative_contribution_sum",
    "downloads_positive_contributor_count",
    "downloads_negative_contributor_count",
    "downloads_unchanged_contributor_count",
    "downloads_market_new_entry_positive_contribution_share",
    "downloads_continuing_positive_contribution_share",
    "downloads_top_1_positive_contribution_share",
    "downloads_top_3_positive_contribution_share",
    "downloads_top_10_positive_contribution_share",
    "revenue_usd_current_coverage_count",
    "revenue_usd_previous_coverage_count",
    "revenue_usd_decomposition_complete",
    "revenue_usd_current_sum",
    "revenue_usd_previous_sum",
    "revenue_usd_mom_change",
    "revenue_usd_mom_growth_rate",
    "revenue_usd_market_new_entry_sum",
    "revenue_usd_market_new_entry_share_of_current",
    "revenue_usd_theme_entry_contribution",
    "revenue_usd_continuing_contribution",
    "revenue_usd_theme_exit_contribution",
    "revenue_usd_positive_contribution_sum",
    "revenue_usd_negative_contribution_sum",
    "revenue_usd_positive_contributor_count",
    "revenue_usd_negative_contributor_count",
    "revenue_usd_unchanged_contributor_count",
    "revenue_usd_market_new_entry_positive_contribution_share",
    "revenue_usd_continuing_positive_contribution_share",
    "revenue_usd_top_1_positive_contribution_share",
    "revenue_usd_top_3_positive_contribution_share",
    "revenue_usd_top_10_positive_contribution_share",
    "calculated_at",
)
THEME_DIMENSION_MONTHLY_METRICS_COLUMNS: tuple[str, ...] = (
    "scope_name",
    "cadence",
    "period_start",
    "period_end",
    "game_theme",
    "dimension_type",
    "dimension_value",
    "product_count",
    "product_share_within_theme",
    "product_share_within_market",
    "top_100_count",
    "top_500_count",
    "average_rank",
    "median_rank",
    "downloads_coverage_count",
    "downloads_sum",
    "downloads_share_within_theme",
    "downloads_share_within_market",
    "downloads_mean_per_covered_product",
    "downloads_median_per_covered_product",
    "downloads_top_1_product_share",
    "revenue_usd_coverage_count",
    "revenue_usd_sum",
    "revenue_usd_share_within_theme",
    "revenue_usd_share_within_market",
    "revenue_usd_mean_per_covered_product",
    "revenue_usd_median_per_covered_product",
    "revenue_usd_top_1_product_share",
    "has_previous_month",
    "market_new_entry_count",
    "market_new_entry_share",
    "market_new_entry_top_100_count",
    "market_new_entry_top_100_rate",
    "market_new_entry_top_500_count",
    "market_new_entry_top_500_rate",
    "publisher_coverage_count",
    "publisher_count",
    "top_1_publisher_product_share",
    "calculated_at",
)
THEME_REPRESENTATIVE_GAMES_COLUMNS: tuple[str, ...] = (
    "scope_name",
    "cadence",
    "period_start",
    "period_end",
    "game_theme",
    "evidence_type",
    "evidence_rank",
    "source_app_id",
    "unified_app_id",
    "game_name",
    "publisher_display_name",
    "game_subgenre",
    "game_product_model",
    "game_art_style",
    "game_setting",
    "release_date_ww",
    "rank_position",
    "previous_rank_position",
    "downloads",
    "previous_downloads",
    "downloads_change",
    "revenue_usd",
    "previous_revenue_usd",
    "revenue_usd_change",
    "is_market_new_entry",
    "is_theme_entry",
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

_CREATE_THEME_TREND_SCORES_SQL = """
CREATE TABLE IF NOT EXISTS theme_trend_scores (
    scope_name VARCHAR NOT NULL,
    cadence VARCHAR NOT NULL CHECK (cadence = 'monthly'),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    game_theme VARCHAR NOT NULL,
    window_start DATE NOT NULL,
    window_month_count INTEGER NOT NULL CHECK (window_month_count = 6),
    active_months_6m INTEGER NOT NULL CHECK (active_months_6m >= 0 AND active_months_6m <= 6),
    latest_product_count INTEGER NOT NULL CHECK (latest_product_count >= 0),
    is_actionable BOOLEAN NOT NULL,
    exclusion_reason VARCHAR NULL,
    latest_product_share DOUBLE NOT NULL CHECK (
        latest_product_share >= 0 AND latest_product_share <= 1
    ),
    latest_units_absolute_share DOUBLE NULL CHECK (
        latest_units_absolute_share IS NULL
        OR (latest_units_absolute_share >= 0 AND latest_units_absolute_share <= 1)
    ),
    latest_revenue_absolute_share DOUBLE NULL CHECK (
        latest_revenue_absolute_share IS NULL
        OR (latest_revenue_absolute_share >= 0 AND latest_revenue_absolute_share <= 1)
    ),
    latest_new_entry_share DOUBLE NULL CHECK (
        latest_new_entry_share IS NULL
        OR (latest_new_entry_share >= 0 AND latest_new_entry_share <= 1)
    ),
    latest_median_rank DOUBLE NOT NULL,
    latest_publisher_count INTEGER NOT NULL CHECK (latest_publisher_count >= 0),
    latest_top_publisher_product_share DOUBLE NULL CHECK (
        latest_top_publisher_product_share IS NULL
        OR (
            latest_top_publisher_product_share >= 0
            AND latest_top_publisher_product_share <= 1
        )
    ),
    product_share_gain_3m DOUBLE NOT NULL,
    units_absolute_share_gain_3m DOUBLE NULL,
    revenue_absolute_share_gain_3m DOUBLE NULL,
    product_share_acceleration DOUBLE NOT NULL,
    units_absolute_share_acceleration DOUBLE NULL,
    revenue_absolute_share_acceleration DOUBLE NULL,
    recent3_new_entry_share DOUBLE NULL CHECK (
        recent3_new_entry_share IS NULL
        OR (recent3_new_entry_share >= 0 AND recent3_new_entry_share <= 1)
    ),
    median_rank_improvement DOUBLE NULL,
    publisher_count_gain_3m DOUBLE NULL,
    units_absolute_overindex DOUBLE NULL,
    revenue_absolute_overindex DOUBLE NULL,
    recent3_units_coverage_ratio DOUBLE NOT NULL CHECK (
        recent3_units_coverage_ratio >= 0 AND recent3_units_coverage_ratio <= 1
    ),
    recent3_revenue_coverage_ratio DOUBLE NOT NULL CHECK (
        recent3_revenue_coverage_ratio >= 0 AND recent3_revenue_coverage_ratio <= 1
    ),
    latest_publisher_coverage_ratio DOUBLE NOT NULL CHECK (
        latest_publisher_coverage_ratio >= 0 AND latest_publisher_coverage_ratio <= 1
    ),
    growth_score DOUBLE NULL CHECK (
        growth_score IS NULL OR (growth_score >= 0 AND growth_score <= 100)
    ),
    acceleration_score DOUBLE NULL CHECK (
        acceleration_score IS NULL OR (acceleration_score >= 0 AND acceleration_score <= 100)
    ),
    new_product_score DOUBLE NULL CHECK (
        new_product_score IS NULL OR (new_product_score >= 0 AND new_product_score <= 100)
    ),
    concentration_penalty DOUBLE NULL CHECK (
        concentration_penalty IS NULL
        OR (concentration_penalty >= 0 AND concentration_penalty <= 100)
    ),
    base_trend_score DOUBLE NULL CHECK (
        base_trend_score IS NULL OR (base_trend_score >= 0 AND base_trend_score <= 100)
    ),
    confidence_score DOUBLE NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 100),
    trend_score DOUBLE NULL CHECK (
        trend_score IS NULL OR (trend_score >= 0 AND trend_score <= 100)
    ),
    trend_rank INTEGER NULL CHECK (trend_rank IS NULL OR trend_rank >= 1),
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (scope_name, cadence, period_start, period_end, game_theme),
    CHECK (period_start <= period_end),
    CHECK (window_start <= period_start),
    CHECK (
        is_actionable
        OR (
            growth_score IS NULL
            AND acceleration_score IS NULL
            AND new_product_score IS NULL
            AND concentration_penalty IS NULL
            AND base_trend_score IS NULL
            AND trend_score IS NULL
            AND trend_rank IS NULL
        )
    ),
    CHECK (
        NOT is_actionable
        OR (
            growth_score IS NOT NULL
            AND acceleration_score IS NOT NULL
            AND new_product_score IS NOT NULL
            AND concentration_penalty IS NOT NULL
            AND base_trend_score IS NOT NULL
            AND trend_score IS NOT NULL
            AND trend_rank IS NOT NULL
        )
    ),
    CHECK (is_actionable OR exclusion_reason IS NOT NULL),
    CHECK (NOT is_actionable OR exclusion_reason IS NULL)
)
"""

_CREATE_THEME_MARKET_STRUCTURE_METRICS_SQL = """
CREATE TABLE IF NOT EXISTS theme_market_structure_metrics (
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
    downloads_coverage_count INTEGER NOT NULL CHECK (downloads_coverage_count >= 0),
    downloads_coverage_ratio DOUBLE NOT NULL CHECK (downloads_coverage_ratio >= 0 AND downloads_coverage_ratio <= 1),
    downloads_sum DOUBLE NULL,
    downloads_share DOUBLE NULL CHECK (downloads_share IS NULL OR (downloads_share >= 0 AND downloads_share <= 1)),
    downloads_mean_per_covered_product DOUBLE NULL,
    downloads_median_per_covered_product DOUBLE NULL,
    downloads_top_1_product_share DOUBLE NULL CHECK (downloads_top_1_product_share IS NULL OR (downloads_top_1_product_share >= 0 AND downloads_top_1_product_share <= 1)),
    downloads_top_3_product_share DOUBLE NULL CHECK (downloads_top_3_product_share IS NULL OR (downloads_top_3_product_share >= 0 AND downloads_top_3_product_share <= 1)),
    downloads_top_10_product_share DOUBLE NULL CHECK (downloads_top_10_product_share IS NULL OR (downloads_top_10_product_share >= 0 AND downloads_top_10_product_share <= 1)),
    downloads_product_hhi DOUBLE NULL CHECK (downloads_product_hhi IS NULL OR (downloads_product_hhi >= 0 AND downloads_product_hhi <= 1)),
    revenue_usd_coverage_count INTEGER NOT NULL CHECK (revenue_usd_coverage_count >= 0),
    revenue_usd_coverage_ratio DOUBLE NOT NULL CHECK (revenue_usd_coverage_ratio >= 0 AND revenue_usd_coverage_ratio <= 1),
    revenue_usd_sum DOUBLE NULL,
    revenue_usd_share DOUBLE NULL CHECK (revenue_usd_share IS NULL OR (revenue_usd_share >= 0 AND revenue_usd_share <= 1)),
    revenue_usd_mean_per_covered_product DOUBLE NULL,
    revenue_usd_median_per_covered_product DOUBLE NULL,
    revenue_usd_top_1_product_share DOUBLE NULL CHECK (revenue_usd_top_1_product_share IS NULL OR (revenue_usd_top_1_product_share >= 0 AND revenue_usd_top_1_product_share <= 1)),
    revenue_usd_top_3_product_share DOUBLE NULL CHECK (revenue_usd_top_3_product_share IS NULL OR (revenue_usd_top_3_product_share >= 0 AND revenue_usd_top_3_product_share <= 1)),
    revenue_usd_top_10_product_share DOUBLE NULL CHECK (revenue_usd_top_10_product_share IS NULL OR (revenue_usd_top_10_product_share >= 0 AND revenue_usd_top_10_product_share <= 1)),
    revenue_usd_product_hhi DOUBLE NULL CHECK (revenue_usd_product_hhi IS NULL OR (revenue_usd_product_hhi >= 0 AND revenue_usd_product_hhi <= 1)),
    publisher_coverage_count INTEGER NOT NULL CHECK (publisher_coverage_count >= 0),
    publisher_coverage_ratio DOUBLE NOT NULL CHECK (publisher_coverage_ratio >= 0 AND publisher_coverage_ratio <= 1),
    publisher_count INTEGER NOT NULL CHECK (publisher_count >= 0),
    top_1_publisher_product_share DOUBLE NULL CHECK (top_1_publisher_product_share IS NULL OR (top_1_publisher_product_share >= 0 AND top_1_publisher_product_share <= 1)),
    top_3_publisher_product_share DOUBLE NULL CHECK (top_3_publisher_product_share IS NULL OR (top_3_publisher_product_share >= 0 AND top_3_publisher_product_share <= 1)),
    publisher_product_hhi DOUBLE NULL CHECK (publisher_product_hhi IS NULL OR (publisher_product_hhi >= 0 AND publisher_product_hhi <= 1)),
    publisher_downloads_coverage_count INTEGER NOT NULL CHECK (publisher_downloads_coverage_count >= 0),
    publisher_downloads_coverage_ratio DOUBLE NOT NULL CHECK (publisher_downloads_coverage_ratio >= 0 AND publisher_downloads_coverage_ratio <= 1),
    top_1_publisher_downloads_share DOUBLE NULL CHECK (top_1_publisher_downloads_share IS NULL OR (top_1_publisher_downloads_share >= 0 AND top_1_publisher_downloads_share <= 1)),
    top_3_publisher_downloads_share DOUBLE NULL CHECK (top_3_publisher_downloads_share IS NULL OR (top_3_publisher_downloads_share >= 0 AND top_3_publisher_downloads_share <= 1)),
    publisher_downloads_hhi DOUBLE NULL CHECK (publisher_downloads_hhi IS NULL OR (publisher_downloads_hhi >= 0 AND publisher_downloads_hhi <= 1)),
    publisher_revenue_usd_coverage_count INTEGER NOT NULL CHECK (publisher_revenue_usd_coverage_count >= 0),
    publisher_revenue_usd_coverage_ratio DOUBLE NOT NULL CHECK (publisher_revenue_usd_coverage_ratio >= 0 AND publisher_revenue_usd_coverage_ratio <= 1),
    top_1_publisher_revenue_usd_share DOUBLE NULL CHECK (top_1_publisher_revenue_usd_share IS NULL OR (top_1_publisher_revenue_usd_share >= 0 AND top_1_publisher_revenue_usd_share <= 1)),
    top_3_publisher_revenue_usd_share DOUBLE NULL CHECK (top_3_publisher_revenue_usd_share IS NULL OR (top_3_publisher_revenue_usd_share >= 0 AND top_3_publisher_revenue_usd_share <= 1)),
    publisher_revenue_usd_hhi DOUBLE NULL CHECK (publisher_revenue_usd_hhi IS NULL OR (publisher_revenue_usd_hhi >= 0 AND publisher_revenue_usd_hhi <= 1)),
    release_date_ww_coverage_count INTEGER NOT NULL CHECK (release_date_ww_coverage_count >= 0),
    release_date_ww_coverage_ratio DOUBLE NOT NULL CHECK (release_date_ww_coverage_ratio >= 0 AND release_date_ww_coverage_ratio <= 1),
    release_date_ww_valid_age_count INTEGER NOT NULL CHECK (release_date_ww_valid_age_count >= 0),
    release_date_ww_future_count INTEGER NOT NULL CHECK (release_date_ww_future_count >= 0),
    median_product_age_days DOUBLE NULL,
    downloads_top_10_median_product_age_days DOUBLE NULL,
    revenue_usd_top_10_median_product_age_days DOUBLE NULL,
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (scope_name, cadence, period_start, period_end, game_theme),
    CHECK (period_start <= period_end),
    CHECK (top_100_count <= product_count),
    CHECK (top_500_count <= product_count),
    CHECK (publisher_coverage_count <= product_count),
    CHECK (publisher_count <= publisher_coverage_count),
    CHECK (downloads_coverage_count <= product_count),
    CHECK (revenue_usd_coverage_count <= product_count),
    CHECK (publisher_downloads_coverage_count <= product_count),
    CHECK (publisher_revenue_usd_coverage_count <= product_count),
    CHECK (release_date_ww_coverage_count <= product_count),
    CHECK (release_date_ww_valid_age_count + release_date_ww_future_count = release_date_ww_coverage_count),
    CHECK ((downloads_coverage_count = 0 AND downloads_sum IS NULL) OR (downloads_coverage_count > 0 AND downloads_sum IS NOT NULL)),
    CHECK ((revenue_usd_coverage_count = 0 AND revenue_usd_sum IS NULL) OR (revenue_usd_coverage_count > 0 AND revenue_usd_sum IS NOT NULL)),
    CHECK ((publisher_downloads_coverage_count = 0 AND top_1_publisher_downloads_share IS NULL AND top_3_publisher_downloads_share IS NULL AND publisher_downloads_hhi IS NULL) OR publisher_downloads_coverage_count > 0),
    CHECK ((publisher_revenue_usd_coverage_count = 0 AND top_1_publisher_revenue_usd_share IS NULL AND top_3_publisher_revenue_usd_share IS NULL AND publisher_revenue_usd_hhi IS NULL) OR publisher_revenue_usd_coverage_count > 0)
)
"""

_CREATE_THEME_GROWTH_SOURCE_METRICS_SQL = """
CREATE TABLE IF NOT EXISTS theme_growth_source_metrics (
    scope_name VARCHAR NOT NULL,
    cadence VARCHAR NOT NULL CHECK (cadence = 'monthly'),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    game_theme VARCHAR NOT NULL,
    has_previous_month BOOLEAN NOT NULL,
    previous_product_count INTEGER NULL,
    current_product_count INTEGER NOT NULL CHECK (current_product_count > 0),
    product_count_change INTEGER NULL,
    market_new_entry_count INTEGER NULL,
    market_returning_product_count INTEGER NULL,
    theme_entry_count INTEGER NULL,
    theme_exit_count INTEGER NULL,
    continuing_theme_product_count INTEGER NULL,
    market_new_entry_share DOUBLE NULL CHECK (market_new_entry_share IS NULL OR (market_new_entry_share >= 0 AND market_new_entry_share <= 1)),
    theme_entry_share DOUBLE NULL CHECK (theme_entry_share IS NULL OR (theme_entry_share >= 0 AND theme_entry_share <= 1)),
    market_new_entry_top_100_count INTEGER NULL,
    market_new_entry_top_100_rate DOUBLE NULL CHECK (market_new_entry_top_100_rate IS NULL OR (market_new_entry_top_100_rate >= 0 AND market_new_entry_top_100_rate <= 1)),
    market_new_entry_top_500_count INTEGER NULL,
    market_new_entry_top_500_rate DOUBLE NULL CHECK (market_new_entry_top_500_rate IS NULL OR (market_new_entry_top_500_rate >= 0 AND market_new_entry_top_500_rate <= 1)),
    top_100_current_count INTEGER NOT NULL CHECK (top_100_current_count >= 0),
    top_100_previous_count INTEGER NULL,
    top_100_entry_count INTEGER NULL,
    top_100_exit_count INTEGER NULL,
    top_100_retained_count INTEGER NULL,
    top_100_turnover_rate DOUBLE NULL CHECK (top_100_turnover_rate IS NULL OR (top_100_turnover_rate >= 0 AND top_100_turnover_rate <= 1)),
    top_500_current_count INTEGER NOT NULL CHECK (top_500_current_count >= 0),
    top_500_previous_count INTEGER NULL,
    top_500_entry_count INTEGER NULL,
    top_500_exit_count INTEGER NULL,
    top_500_retained_count INTEGER NULL,
    top_500_turnover_rate DOUBLE NULL CHECK (top_500_turnover_rate IS NULL OR (top_500_turnover_rate >= 0 AND top_500_turnover_rate <= 1)),
    downloads_top_10_current_count INTEGER NOT NULL CHECK (downloads_top_10_current_count >= 0),
    downloads_top_10_retained_count INTEGER NULL,
    downloads_top_10_retention_rate DOUBLE NULL CHECK (downloads_top_10_retention_rate IS NULL OR (downloads_top_10_retention_rate >= 0 AND downloads_top_10_retention_rate <= 1)),
    revenue_usd_top_10_current_count INTEGER NOT NULL CHECK (revenue_usd_top_10_current_count >= 0),
    revenue_usd_top_10_retained_count INTEGER NULL,
    revenue_usd_top_10_retention_rate DOUBLE NULL CHECK (revenue_usd_top_10_retention_rate IS NULL OR (revenue_usd_top_10_retention_rate >= 0 AND revenue_usd_top_10_retention_rate <= 1)),
    downloads_current_coverage_count INTEGER NOT NULL CHECK (downloads_current_coverage_count >= 0),
    downloads_previous_coverage_count INTEGER NULL,
    downloads_decomposition_complete BOOLEAN NULL,
    downloads_current_sum DOUBLE NULL,
    downloads_previous_sum DOUBLE NULL,
    downloads_mom_change DOUBLE NULL,
    downloads_mom_growth_rate DOUBLE NULL CHECK (downloads_mom_growth_rate IS NULL OR isfinite(downloads_mom_growth_rate)),
    downloads_market_new_entry_sum DOUBLE NULL,
    downloads_market_new_entry_share_of_current DOUBLE NULL CHECK (downloads_market_new_entry_share_of_current IS NULL OR (downloads_market_new_entry_share_of_current >= 0 AND downloads_market_new_entry_share_of_current <= 1)),
    downloads_theme_entry_contribution DOUBLE NULL,
    downloads_continuing_contribution DOUBLE NULL,
    downloads_theme_exit_contribution DOUBLE NULL,
    downloads_positive_contribution_sum DOUBLE NULL,
    downloads_negative_contribution_sum DOUBLE NULL,
    downloads_positive_contributor_count INTEGER NULL,
    downloads_negative_contributor_count INTEGER NULL,
    downloads_unchanged_contributor_count INTEGER NULL,
    downloads_market_new_entry_positive_contribution_share DOUBLE NULL CHECK (downloads_market_new_entry_positive_contribution_share IS NULL OR (downloads_market_new_entry_positive_contribution_share >= 0 AND downloads_market_new_entry_positive_contribution_share <= 1)),
    downloads_continuing_positive_contribution_share DOUBLE NULL CHECK (downloads_continuing_positive_contribution_share IS NULL OR (downloads_continuing_positive_contribution_share >= 0 AND downloads_continuing_positive_contribution_share <= 1)),
    downloads_top_1_positive_contribution_share DOUBLE NULL CHECK (downloads_top_1_positive_contribution_share IS NULL OR (downloads_top_1_positive_contribution_share >= 0 AND downloads_top_1_positive_contribution_share <= 1)),
    downloads_top_3_positive_contribution_share DOUBLE NULL CHECK (downloads_top_3_positive_contribution_share IS NULL OR (downloads_top_3_positive_contribution_share >= 0 AND downloads_top_3_positive_contribution_share <= 1)),
    downloads_top_10_positive_contribution_share DOUBLE NULL CHECK (downloads_top_10_positive_contribution_share IS NULL OR (downloads_top_10_positive_contribution_share >= 0 AND downloads_top_10_positive_contribution_share <= 1)),
    revenue_usd_current_coverage_count INTEGER NOT NULL CHECK (revenue_usd_current_coverage_count >= 0),
    revenue_usd_previous_coverage_count INTEGER NULL,
    revenue_usd_decomposition_complete BOOLEAN NULL,
    revenue_usd_current_sum DOUBLE NULL,
    revenue_usd_previous_sum DOUBLE NULL,
    revenue_usd_mom_change DOUBLE NULL,
    revenue_usd_mom_growth_rate DOUBLE NULL CHECK (revenue_usd_mom_growth_rate IS NULL OR isfinite(revenue_usd_mom_growth_rate)),
    revenue_usd_market_new_entry_sum DOUBLE NULL,
    revenue_usd_market_new_entry_share_of_current DOUBLE NULL CHECK (revenue_usd_market_new_entry_share_of_current IS NULL OR (revenue_usd_market_new_entry_share_of_current >= 0 AND revenue_usd_market_new_entry_share_of_current <= 1)),
    revenue_usd_theme_entry_contribution DOUBLE NULL,
    revenue_usd_continuing_contribution DOUBLE NULL,
    revenue_usd_theme_exit_contribution DOUBLE NULL,
    revenue_usd_positive_contribution_sum DOUBLE NULL,
    revenue_usd_negative_contribution_sum DOUBLE NULL,
    revenue_usd_positive_contributor_count INTEGER NULL,
    revenue_usd_negative_contributor_count INTEGER NULL,
    revenue_usd_unchanged_contributor_count INTEGER NULL,
    revenue_usd_market_new_entry_positive_contribution_share DOUBLE NULL CHECK (revenue_usd_market_new_entry_positive_contribution_share IS NULL OR (revenue_usd_market_new_entry_positive_contribution_share >= 0 AND revenue_usd_market_new_entry_positive_contribution_share <= 1)),
    revenue_usd_continuing_positive_contribution_share DOUBLE NULL CHECK (revenue_usd_continuing_positive_contribution_share IS NULL OR (revenue_usd_continuing_positive_contribution_share >= 0 AND revenue_usd_continuing_positive_contribution_share <= 1)),
    revenue_usd_top_1_positive_contribution_share DOUBLE NULL CHECK (revenue_usd_top_1_positive_contribution_share IS NULL OR (revenue_usd_top_1_positive_contribution_share >= 0 AND revenue_usd_top_1_positive_contribution_share <= 1)),
    revenue_usd_top_3_positive_contribution_share DOUBLE NULL CHECK (revenue_usd_top_3_positive_contribution_share IS NULL OR (revenue_usd_top_3_positive_contribution_share >= 0 AND revenue_usd_top_3_positive_contribution_share <= 1)),
    revenue_usd_top_10_positive_contribution_share DOUBLE NULL CHECK (revenue_usd_top_10_positive_contribution_share IS NULL OR (revenue_usd_top_10_positive_contribution_share >= 0 AND revenue_usd_top_10_positive_contribution_share <= 1)),
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (scope_name, cadence, period_start, period_end, game_theme),
    CHECK (period_start <= period_end),
    CHECK (top_100_current_count <= current_product_count),
    CHECK (top_500_current_count <= current_product_count),
    CHECK (downloads_top_10_current_count <= current_product_count),
    CHECK (revenue_usd_top_10_current_count <= current_product_count),
    CHECK ((downloads_current_coverage_count = 0 AND downloads_current_sum IS NULL) OR (downloads_current_coverage_count > 0 AND downloads_current_sum IS NOT NULL)),
    CHECK ((revenue_usd_current_coverage_count = 0 AND revenue_usd_current_sum IS NULL) OR (revenue_usd_current_coverage_count > 0 AND revenue_usd_current_sum IS NOT NULL))
)
"""

_CREATE_THEME_DIMENSION_MONTHLY_METRICS_SQL = """
CREATE TABLE IF NOT EXISTS theme_dimension_monthly_metrics (
    scope_name VARCHAR NOT NULL,
    cadence VARCHAR NOT NULL CHECK (cadence = 'monthly'),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    game_theme VARCHAR NOT NULL,
    dimension_type VARCHAR NOT NULL CHECK (dimension_type IN ('game_subgenre', 'game_product_model', 'game_art_style', 'game_setting')),
    dimension_value VARCHAR NOT NULL,
    product_count INTEGER NOT NULL CHECK (product_count > 0),
    product_share_within_theme DOUBLE NOT NULL CHECK (product_share_within_theme >= 0 AND product_share_within_theme <= 1),
    product_share_within_market DOUBLE NOT NULL CHECK (product_share_within_market >= 0 AND product_share_within_market <= 1),
    top_100_count INTEGER NOT NULL CHECK (top_100_count >= 0),
    top_500_count INTEGER NOT NULL CHECK (top_500_count >= 0),
    average_rank DOUBLE NOT NULL,
    median_rank DOUBLE NOT NULL,
    downloads_coverage_count INTEGER NOT NULL CHECK (downloads_coverage_count >= 0),
    downloads_sum DOUBLE NULL,
    downloads_share_within_theme DOUBLE NULL CHECK (downloads_share_within_theme IS NULL OR (downloads_share_within_theme >= 0 AND downloads_share_within_theme <= 1)),
    downloads_share_within_market DOUBLE NULL CHECK (downloads_share_within_market IS NULL OR (downloads_share_within_market >= 0 AND downloads_share_within_market <= 1)),
    downloads_mean_per_covered_product DOUBLE NULL,
    downloads_median_per_covered_product DOUBLE NULL,
    downloads_top_1_product_share DOUBLE NULL CHECK (downloads_top_1_product_share IS NULL OR (downloads_top_1_product_share >= 0 AND downloads_top_1_product_share <= 1)),
    revenue_usd_coverage_count INTEGER NOT NULL CHECK (revenue_usd_coverage_count >= 0),
    revenue_usd_sum DOUBLE NULL,
    revenue_usd_share_within_theme DOUBLE NULL CHECK (revenue_usd_share_within_theme IS NULL OR (revenue_usd_share_within_theme >= 0 AND revenue_usd_share_within_theme <= 1)),
    revenue_usd_share_within_market DOUBLE NULL CHECK (revenue_usd_share_within_market IS NULL OR (revenue_usd_share_within_market >= 0 AND revenue_usd_share_within_market <= 1)),
    revenue_usd_mean_per_covered_product DOUBLE NULL,
    revenue_usd_median_per_covered_product DOUBLE NULL,
    revenue_usd_top_1_product_share DOUBLE NULL CHECK (revenue_usd_top_1_product_share IS NULL OR (revenue_usd_top_1_product_share >= 0 AND revenue_usd_top_1_product_share <= 1)),
    has_previous_month BOOLEAN NOT NULL,
    market_new_entry_count INTEGER NULL,
    market_new_entry_share DOUBLE NULL CHECK (market_new_entry_share IS NULL OR (market_new_entry_share >= 0 AND market_new_entry_share <= 1)),
    market_new_entry_top_100_count INTEGER NULL,
    market_new_entry_top_100_rate DOUBLE NULL CHECK (market_new_entry_top_100_rate IS NULL OR (market_new_entry_top_100_rate >= 0 AND market_new_entry_top_100_rate <= 1)),
    market_new_entry_top_500_count INTEGER NULL,
    market_new_entry_top_500_rate DOUBLE NULL CHECK (market_new_entry_top_500_rate IS NULL OR (market_new_entry_top_500_rate >= 0 AND market_new_entry_top_500_rate <= 1)),
    publisher_coverage_count INTEGER NOT NULL CHECK (publisher_coverage_count >= 0),
    publisher_count INTEGER NOT NULL CHECK (publisher_count >= 0),
    top_1_publisher_product_share DOUBLE NULL CHECK (top_1_publisher_product_share IS NULL OR (top_1_publisher_product_share >= 0 AND top_1_publisher_product_share <= 1)),
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (scope_name, cadence, period_start, period_end, game_theme, dimension_type, dimension_value),
    CHECK (period_start <= period_end),
    CHECK (top_100_count <= product_count),
    CHECK (top_500_count <= product_count),
    CHECK (downloads_coverage_count <= product_count),
    CHECK (revenue_usd_coverage_count <= product_count),
    CHECK (publisher_coverage_count <= product_count),
    CHECK (publisher_count <= publisher_coverage_count),
    CHECK ((downloads_coverage_count = 0 AND downloads_sum IS NULL) OR (downloads_coverage_count > 0 AND downloads_sum IS NOT NULL)),
    CHECK ((revenue_usd_coverage_count = 0 AND revenue_usd_sum IS NULL) OR (revenue_usd_coverage_count > 0 AND revenue_usd_sum IS NOT NULL))
)
"""

_CREATE_THEME_REPRESENTATIVE_GAMES_SQL = """
CREATE TABLE IF NOT EXISTS theme_representative_games (
    scope_name VARCHAR NOT NULL,
    cadence VARCHAR NOT NULL CHECK (cadence = 'monthly'),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    game_theme VARCHAR NOT NULL,
    evidence_type VARCHAR NOT NULL CHECK (evidence_type IN ('downloads_leader', 'revenue_leader', 'market_new_entry_downloads_leader', 'market_new_entry_revenue_leader', 'downloads_growth_leader', 'revenue_growth_leader')),
    evidence_rank INTEGER NOT NULL CHECK (evidence_rank > 0),
    source_app_id VARCHAR NOT NULL,
    unified_app_id VARCHAR NOT NULL,
    game_name VARCHAR NULL,
    publisher_display_name VARCHAR NULL,
    game_subgenre VARCHAR NULL,
    game_product_model VARCHAR NULL,
    game_art_style VARCHAR NULL,
    game_setting VARCHAR NULL,
    release_date_ww DATE NULL,
    rank_position INTEGER NOT NULL CHECK (rank_position > 0),
    previous_rank_position INTEGER NULL,
    downloads DOUBLE NULL,
    previous_downloads DOUBLE NULL,
    downloads_change DOUBLE NULL,
    revenue_usd DOUBLE NULL,
    previous_revenue_usd DOUBLE NULL,
    revenue_usd_change DOUBLE NULL,
    is_market_new_entry BOOLEAN NULL,
    is_theme_entry BOOLEAN NULL,
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (scope_name, cadence, period_start, period_end, game_theme, evidence_type, evidence_rank),
    CHECK (period_start <= period_end),
    CHECK (previous_rank_position IS NULL OR previous_rank_position > 0)
)
"""

_V1_TABLE_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (SCHEMA_MIGRATIONS_TABLE, _CREATE_SCHEMA_MIGRATIONS_SQL, SCHEMA_MIGRATIONS_COLUMNS),
    (APP_METADATA_TABLE, _CREATE_APP_METADATA_SQL, APP_METADATA_COLUMNS),
    (MARKET_SNAPSHOTS_TABLE, _CREATE_MARKET_SNAPSHOTS_SQL, MARKET_SNAPSHOT_COLUMNS),
)
_V2_TABLE_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        MONTHLY_MARKET_TOTALS_TABLE,
        _CREATE_MONTHLY_MARKET_TOTALS_SQL,
        MONTHLY_MARKET_TOTALS_COLUMNS,
    ),
    (
        THEME_MONTHLY_METRICS_TABLE,
        _CREATE_THEME_MONTHLY_METRICS_SQL,
        THEME_MONTHLY_METRICS_COLUMNS,
    ),
)
_TABLE_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    *_V1_TABLE_DEFINITIONS,
    *_V2_TABLE_DEFINITIONS,
)
_V3_TABLE_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        THEME_TREND_SCORES_TABLE,
        _CREATE_THEME_TREND_SCORES_SQL,
        THEME_TREND_SCORES_COLUMNS,
    ),
)
_V4_TABLE_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        THEME_MARKET_STRUCTURE_METRICS_TABLE,
        _CREATE_THEME_MARKET_STRUCTURE_METRICS_SQL,
        THEME_MARKET_STRUCTURE_METRICS_COLUMNS,
    ),
    (
        THEME_GROWTH_SOURCE_METRICS_TABLE,
        _CREATE_THEME_GROWTH_SOURCE_METRICS_SQL,
        THEME_GROWTH_SOURCE_METRICS_COLUMNS,
    ),
    (
        THEME_DIMENSION_MONTHLY_METRICS_TABLE,
        _CREATE_THEME_DIMENSION_MONTHLY_METRICS_SQL,
        THEME_DIMENSION_MONTHLY_METRICS_COLUMNS,
    ),
    (
        THEME_REPRESENTATIVE_GAMES_TABLE,
        _CREATE_THEME_REPRESENTATIVE_GAMES_SQL,
        THEME_REPRESENTATIVE_GAMES_COLUMNS,
    ),
)
_TABLE_DEFINITIONS = (
    *_TABLE_DEFINITIONS,
    *_V3_TABLE_DEFINITIONS,
    *_V4_TABLE_DEFINITIONS,
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

        _assert_table_definitions(connection, _V2_TABLE_DEFINITIONS)

        if newest_version < 3:
            _apply_version_three(connection)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                [3],
            )

        _assert_table_definitions(connection, _V3_TABLE_DEFINITIONS)

        if newest_version < 4:
            _apply_version_four(connection)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                [4],
            )

        _assert_required_tables(connection)

        connection.execute("COMMIT")
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except duckdb.Error:
            pass
        raise


def verify_read_only_schema(connection: duckdb.DuckDBPyConnection) -> None:
    """Verify a compatible existing schema without migrations or writes."""

    _assert_table_columns(connection, SCHEMA_MIGRATIONS_TABLE, SCHEMA_MIGRATIONS_COLUMNS)
    newest_version = _get_newest_schema_version(connection)
    if newest_version > CURRENT_SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(newest_version, CURRENT_SCHEMA_VERSION)
    if newest_version < 1:
        raise SchemaInitializationError("database schema has no supported migrations")
    _assert_table_definitions(connection, _V1_TABLE_DEFINITIONS)


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


def _apply_version_three(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(_CREATE_THEME_TREND_SCORES_SQL)


def _apply_version_four(connection: duckdb.DuckDBPyConnection) -> None:
    for _table_name, create_sql, _columns in _V4_TABLE_DEFINITIONS:
        connection.execute(create_sql)


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
