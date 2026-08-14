"""Versioned DuckDB schema for source and derived analytical rows."""

# SQL constraint declarations intentionally keep each column definition
# together; the schema contract supplies the authoritative explicit order.
# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Iterable

import duckdb

from .errors import SchemaInitializationError, UnsupportedSchemaVersionError

CURRENT_SCHEMA_VERSION = 6

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
THEME_HORIZON_METRICS_TABLE = "theme_horizon_metrics"
THEME_MODEL_SUMMARIES_TABLE = "theme_model_summaries"
THEME_SEASONALITY_PROFILES_TABLE = "theme_seasonality_profiles"
THEME_LAUNCH_WINDOW_OUTCOMES_TABLE = "theme_launch_window_outcomes"
THEME_BACKTEST_FEATURE_METRICS_TABLE = "theme_backtest_feature_metrics"
THEME_BACKTEST_SEGMENT_METRICS_TABLE = "theme_backtest_segment_metrics"

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
THEME_HORIZON_METRICS_COLUMNS: tuple[str, ...] = (
    "scope_name",
    "cadence",
    "period_start",
    "period_end",
    "game_theme",
    "horizon_month_count",
    "metric_name",
    "window_start",
    "expected_month_count",
    "metric_coverage_count",
    "active_month_count",
    "is_complete",
    "first_value",
    "latest_value",
    "mean_value",
    "median_value",
    "minimum_value",
    "maximum_value",
    "absolute_change",
    "relative_change",
    "linear_slope",
    "normalized_slope",
    "r_squared",
    "latest_to_mean_ratio",
    "transition_count",
    "transition_coverage_count",
    "positive_change_count",
    "negative_change_count",
    "unchanged_change_count",
    "positive_change_ratio",
    "standard_deviation",
    "coefficient_of_variation",
    "maximum_drawdown",
    "months_since_peak",
    "calculated_at",
)
THEME_MODEL_SUMMARIES_COLUMNS: tuple[str, ...] = (
    "scope_name",
    "cadence",
    "period_start",
    "period_end",
    "game_theme",
    "model_policy_version",
    "history_start",
    "history_month_count",
    "first_active_month",
    "first_active_left_censored",
    "months_since_first_active",
    "active_months_to_date",
    "has_6m_history",
    "has_12m_history",
    "has_36m_history",
    "active_months_6m",
    "active_months_12m",
    "active_months_36m",
    "direction_6m",
    "direction_12m",
    "direction_36m",
    "direction_evidence_count_6m",
    "direction_evidence_count_12m",
    "direction_evidence_count_36m",
    "median_normalized_slope_6m",
    "median_normalized_slope_12m",
    "median_normalized_slope_36m",
    "median_r_squared_6m",
    "median_r_squared_12m",
    "median_r_squared_36m",
    "stability_cv_median_6m",
    "stability_cv_median_12m",
    "stability_cv_median_36m",
    "stability_band_6m",
    "stability_band_12m",
    "stability_band_36m",
    "lifecycle_stage",
    "seasonality_history_month_count",
    "seasonality_complete_year_count",
    "downloads_peak_calendar_month",
    "downloads_trough_calendar_month",
    "downloads_seasonality_amplitude",
    "revenue_usd_peak_calendar_month",
    "revenue_usd_trough_calendar_month",
    "revenue_usd_seasonality_amplitude",
    "calculated_at",
)
THEME_SEASONALITY_PROFILES_COLUMNS: tuple[str, ...] = (
    "scope_name",
    "cadence",
    "period_start",
    "period_end",
    "game_theme",
    "metric_name",
    "calendar_month",
    "history_start",
    "history_month_count",
    "complete_year_count",
    "observation_count",
    "seasonal_index",
    "index_deviation",
    "is_peak_month",
    "is_trough_month",
    "calculated_at",
)
THEME_LAUNCH_WINDOW_OUTCOMES_COLUMNS: tuple[str, ...] = (
    "scope_name",
    "cadence",
    "decision_period_start",
    "decision_period_end",
    "outcome_horizon_months",
    "outcome_period_start",
    "outcome_period_end",
    "game_theme",
    "backtest_policy_version",
    "model_policy_version",
    "legacy_is_actionable",
    "legacy_exclusion_reason",
    "legacy_confidence_score",
    "legacy_6m_momentum_score",
    "legacy_6m_momentum_rank",
    "has_6m_history",
    "has_12m_history",
    "has_36m_history",
    "direction_6m",
    "direction_12m",
    "direction_36m",
    "direction_evidence_count_6m",
    "direction_evidence_count_12m",
    "direction_evidence_count_36m",
    "median_normalized_slope_6m",
    "median_normalized_slope_12m",
    "median_normalized_slope_36m",
    "stability_cv_median_6m",
    "stability_cv_median_12m",
    "stability_cv_median_36m",
    "stability_band_6m",
    "stability_band_12m",
    "stability_band_36m",
    "lifecycle_stage",
    "first_active_left_censored",
    "months_since_first_active",
    "decision_product_count",
    "decision_product_share",
    "decision_downloads_sum",
    "decision_downloads_share",
    "decision_revenue_usd_sum",
    "decision_revenue_usd_share",
    "decision_downloads_product_hhi",
    "decision_revenue_usd_product_hhi",
    "decision_publisher_downloads_hhi",
    "decision_publisher_revenue_usd_hhi",
    "decision_top_500_turnover_rate",
    "decision_market_new_entry_share",
    "decision_downloads_market_new_entry_share_of_current",
    "decision_revenue_usd_market_new_entry_share_of_current",
    "decision_downloads_top_10_positive_contribution_share",
    "decision_revenue_usd_top_10_positive_contribution_share",
    "decision_downloads_expected_seasonal_index",
    "decision_revenue_usd_expected_seasonal_index",
    "decision_downloads_seasonality_amplitude",
    "decision_revenue_usd_seasonality_amplitude",
    "future_theme_present",
    "future_product_count",
    "future_product_share",
    "future_downloads_sum",
    "future_downloads_share",
    "future_revenue_usd_sum",
    "future_revenue_usd_share",
    "product_count_absolute_change",
    "product_count_relative_change",
    "product_share_absolute_change",
    "product_share_relative_change",
    "downloads_sum_absolute_change",
    "downloads_sum_relative_change",
    "downloads_share_absolute_change",
    "downloads_share_relative_change",
    "revenue_usd_sum_absolute_change",
    "revenue_usd_sum_relative_change",
    "revenue_usd_share_absolute_change",
    "revenue_usd_share_relative_change",
    "product_share_change_direction",
    "downloads_share_change_direction",
    "revenue_usd_share_change_direction",
    "future_product_share_percentile",
    "future_downloads_share_percentile",
    "future_revenue_usd_share_percentile",
    "future_product_share_top_quintile",
    "future_downloads_share_top_quintile",
    "future_revenue_usd_share_top_quintile",
    "calculated_at",
)
THEME_BACKTEST_FEATURE_METRICS_COLUMNS: tuple[str, ...] = (
    "scope_name",
    "cadence",
    "backtest_start",
    "backtest_end",
    "outcome_horizon_months",
    "feature_name",
    "feature_group",
    "feature_hypothesis",
    "outcome_name",
    "backtest_policy_version",
    "candidate_row_count",
    "eligible_row_count",
    "coverage_ratio",
    "decision_month_count",
    "correlation_cohort_count",
    "mean_spearman",
    "median_spearman",
    "p25_spearman",
    "p75_spearman",
    "positive_spearman_cohort_count",
    "positive_spearman_cohort_ratio",
    "positive_spearman_ci_low",
    "positive_spearman_ci_high",
    "top_quintile_cohort_count",
    "top_quintile_selected_count",
    "top_quintile_hit_count",
    "top_quintile_hit_rate",
    "top_quintile_hit_ci_low",
    "top_quintile_hit_ci_high",
    "future_top_quintile_base_rate",
    "top_quintile_lift",
    "top_quintile_outcome_mean",
    "top_quintile_outcome_median",
    "all_eligible_outcome_mean",
    "all_eligible_outcome_median",
    "top_quintile_positive_change_count",
    "top_quintile_positive_change_rate",
    "top_quintile_positive_change_ci_low",
    "top_quintile_positive_change_ci_high",
    "all_positive_change_count",
    "all_positive_change_rate",
    "all_positive_change_ci_low",
    "all_positive_change_ci_high",
    "low_sample_warning",
    "calculated_at",
)
THEME_BACKTEST_SEGMENT_METRICS_COLUMNS: tuple[str, ...] = (
    "scope_name",
    "cadence",
    "backtest_start",
    "backtest_end",
    "outcome_horizon_months",
    "segment_name",
    "segment_value",
    "outcome_name",
    "backtest_policy_version",
    "candidate_row_count",
    "eligible_row_count",
    "coverage_ratio",
    "decision_month_count",
    "segment_row_share",
    "outcome_mean",
    "outcome_median",
    "outcome_p25",
    "outcome_p75",
    "future_top_quintile_count",
    "future_top_quintile_rate",
    "future_top_quintile_ci_low",
    "future_top_quintile_ci_high",
    "future_top_quintile_base_rate",
    "future_top_quintile_lift",
    "positive_change_count",
    "positive_change_rate",
    "positive_change_ci_low",
    "positive_change_ci_high",
    "low_sample_warning",
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
    CHECK (downloads_current_coverage_count <= current_product_count),
    CHECK (revenue_usd_current_coverage_count <= current_product_count),
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
    evidence_rank INTEGER NOT NULL CHECK (evidence_rank BETWEEN 1 AND 3),
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

_CREATE_THEME_HORIZON_METRICS_SQL = """
CREATE TABLE IF NOT EXISTS theme_horizon_metrics (
    scope_name VARCHAR NOT NULL,
    cadence VARCHAR NOT NULL CHECK (cadence = 'monthly'),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    game_theme VARCHAR NOT NULL,
    horizon_month_count INTEGER NOT NULL CHECK (horizon_month_count IN (6, 12, 36)),
    metric_name VARCHAR NOT NULL CHECK (
        metric_name IN (
            'product_count',
            'product_share',
            'downloads_sum',
            'downloads_share',
            'revenue_usd_sum',
            'revenue_usd_share'
        )
    ),
    window_start DATE NOT NULL,
    expected_month_count INTEGER NOT NULL CHECK (expected_month_count = horizon_month_count),
    metric_coverage_count INTEGER NOT NULL CHECK (
        metric_coverage_count >= 0 AND metric_coverage_count <= horizon_month_count
    ),
    active_month_count INTEGER NOT NULL CHECK (
        active_month_count >= 0 AND active_month_count <= horizon_month_count
    ),
    is_complete BOOLEAN NOT NULL CHECK (is_complete = (metric_coverage_count = expected_month_count)),
    first_value DOUBLE NULL,
    latest_value DOUBLE NULL,
    mean_value DOUBLE NULL,
    median_value DOUBLE NULL,
    minimum_value DOUBLE NULL,
    maximum_value DOUBLE NULL,
    absolute_change DOUBLE NULL,
    relative_change DOUBLE NULL,
    linear_slope DOUBLE NULL,
    normalized_slope DOUBLE NULL,
    r_squared DOUBLE NULL,
    latest_to_mean_ratio DOUBLE NULL,
    transition_count INTEGER NOT NULL CHECK (transition_count = horizon_month_count - 1),
    transition_coverage_count INTEGER NOT NULL CHECK (
        transition_coverage_count >= 0 AND transition_coverage_count <= transition_count
    ),
    positive_change_count INTEGER NOT NULL CHECK (positive_change_count >= 0),
    negative_change_count INTEGER NOT NULL CHECK (negative_change_count >= 0),
    unchanged_change_count INTEGER NOT NULL CHECK (unchanged_change_count >= 0),
    positive_change_ratio DOUBLE NULL CHECK (
        positive_change_ratio IS NULL OR (positive_change_ratio >= 0 AND positive_change_ratio <= 1)
    ),
    standard_deviation DOUBLE NULL CHECK (standard_deviation IS NULL OR standard_deviation >= 0),
    coefficient_of_variation DOUBLE NULL CHECK (
        coefficient_of_variation IS NULL OR coefficient_of_variation >= 0
    ),
    maximum_drawdown DOUBLE NULL CHECK (
        maximum_drawdown IS NULL OR (maximum_drawdown >= 0 AND maximum_drawdown <= 1)
    ),
    months_since_peak INTEGER NULL CHECK (
        months_since_peak IS NULL
        OR (months_since_peak >= 0 AND months_since_peak <= horizon_month_count - 1)
    ),
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (
        scope_name,
        cadence,
        period_start,
        period_end,
        game_theme,
        horizon_month_count,
        metric_name
    ),
    CHECK (period_start <= period_end),
    CHECK (
        positive_change_count + negative_change_count + unchanged_change_count
        = transition_coverage_count
    )
)
"""

_CREATE_THEME_MODEL_SUMMARIES_SQL = """
CREATE TABLE IF NOT EXISTS theme_model_summaries (
    scope_name VARCHAR NOT NULL,
    cadence VARCHAR NOT NULL CHECK (cadence = 'monthly'),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    game_theme VARCHAR NOT NULL,
    model_policy_version VARCHAR NOT NULL CHECK (model_policy_version = 'MODEL002_V1'),
    history_start DATE NOT NULL,
    history_month_count INTEGER NOT NULL CHECK (history_month_count >= 1),
    first_active_month DATE NULL,
    first_active_left_censored BOOLEAN NOT NULL,
    months_since_first_active INTEGER NULL CHECK (months_since_first_active >= 0),
    active_months_to_date INTEGER NOT NULL CHECK (
        active_months_to_date >= 0 AND active_months_to_date <= history_month_count
    ),
    has_6m_history BOOLEAN NOT NULL,
    has_12m_history BOOLEAN NOT NULL,
    has_36m_history BOOLEAN NOT NULL,
    active_months_6m INTEGER NULL CHECK (active_months_6m IS NULL OR (active_months_6m >= 0 AND active_months_6m <= 6)),
    active_months_12m INTEGER NULL CHECK (active_months_12m IS NULL OR (active_months_12m >= 0 AND active_months_12m <= 12)),
    active_months_36m INTEGER NULL CHECK (active_months_36m IS NULL OR (active_months_36m >= 0 AND active_months_36m <= 36)),
    direction_6m VARCHAR NOT NULL CHECK (direction_6m IN ('up', 'down', 'flat', 'mixed', 'insufficient_history')),
    direction_12m VARCHAR NOT NULL CHECK (direction_12m IN ('up', 'down', 'flat', 'mixed', 'insufficient_history')),
    direction_36m VARCHAR NOT NULL CHECK (direction_36m IN ('up', 'down', 'flat', 'mixed', 'insufficient_history')),
    direction_evidence_count_6m INTEGER NOT NULL CHECK (direction_evidence_count_6m BETWEEN 0 AND 3),
    direction_evidence_count_12m INTEGER NOT NULL CHECK (direction_evidence_count_12m BETWEEN 0 AND 3),
    direction_evidence_count_36m INTEGER NOT NULL CHECK (direction_evidence_count_36m BETWEEN 0 AND 3),
    median_normalized_slope_6m DOUBLE NULL,
    median_normalized_slope_12m DOUBLE NULL,
    median_normalized_slope_36m DOUBLE NULL,
    median_r_squared_6m DOUBLE NULL,
    median_r_squared_12m DOUBLE NULL,
    median_r_squared_36m DOUBLE NULL,
    stability_cv_median_6m DOUBLE NULL CHECK (stability_cv_median_6m IS NULL OR stability_cv_median_6m >= 0),
    stability_cv_median_12m DOUBLE NULL CHECK (stability_cv_median_12m IS NULL OR stability_cv_median_12m >= 0),
    stability_cv_median_36m DOUBLE NULL CHECK (stability_cv_median_36m IS NULL OR stability_cv_median_36m >= 0),
    stability_band_6m VARCHAR NOT NULL CHECK (stability_band_6m IN ('stable', 'variable', 'volatile', 'insufficient_history')),
    stability_band_12m VARCHAR NOT NULL CHECK (stability_band_12m IN ('stable', 'variable', 'volatile', 'insufficient_history')),
    stability_band_36m VARCHAR NOT NULL CHECK (stability_band_36m IN ('stable', 'variable', 'volatile', 'insufficient_history')),
    lifecycle_stage VARCHAR NOT NULL CHECK (lifecycle_stage IN ('insufficient_history', 'emerging', 'accelerating', 'growing', 'mature', 'recovering', 'declining', 'mixed')),
    seasonality_history_month_count INTEGER NULL CHECK (seasonality_history_month_count IN (24, 36)),
    seasonality_complete_year_count INTEGER NULL CHECK (seasonality_complete_year_count BETWEEN 2 AND 3),
    downloads_peak_calendar_month INTEGER NULL CHECK (downloads_peak_calendar_month BETWEEN 1 AND 12),
    downloads_trough_calendar_month INTEGER NULL CHECK (downloads_trough_calendar_month BETWEEN 1 AND 12),
    downloads_seasonality_amplitude DOUBLE NULL CHECK (downloads_seasonality_amplitude IS NULL OR downloads_seasonality_amplitude >= 0),
    revenue_usd_peak_calendar_month INTEGER NULL CHECK (revenue_usd_peak_calendar_month BETWEEN 1 AND 12),
    revenue_usd_trough_calendar_month INTEGER NULL CHECK (revenue_usd_trough_calendar_month BETWEEN 1 AND 12),
    revenue_usd_seasonality_amplitude DOUBLE NULL CHECK (revenue_usd_seasonality_amplitude IS NULL OR revenue_usd_seasonality_amplitude >= 0),
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (scope_name, cadence, period_start, period_end, game_theme),
    CHECK (period_start <= period_end),
    CHECK (seasonality_history_month_count IS NULL OR seasonality_complete_year_count IS NOT NULL),
    CHECK (seasonality_history_month_count IS NOT NULL OR seasonality_complete_year_count IS NULL),
    CHECK (
        seasonality_history_month_count IS NULL
        OR seasonality_complete_year_count * 12 = seasonality_history_month_count
    )
)
"""

_CREATE_THEME_SEASONALITY_PROFILES_SQL = """
CREATE TABLE IF NOT EXISTS theme_seasonality_profiles (
    scope_name VARCHAR NOT NULL,
    cadence VARCHAR NOT NULL CHECK (cadence = 'monthly'),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    game_theme VARCHAR NOT NULL,
    metric_name VARCHAR NOT NULL CHECK (
        metric_name IN (
            'product_count',
            'product_share',
            'downloads_sum',
            'downloads_share',
            'revenue_usd_sum',
            'revenue_usd_share'
        )
    ),
    calendar_month INTEGER NOT NULL CHECK (calendar_month BETWEEN 1 AND 12),
    history_start DATE NOT NULL,
    history_month_count INTEGER NOT NULL CHECK (history_month_count IN (24, 36)),
    complete_year_count INTEGER NOT NULL CHECK (
        complete_year_count BETWEEN 2 AND 3
        AND complete_year_count * 12 = history_month_count
    ),
    observation_count INTEGER NOT NULL CHECK (
        observation_count >= 2 AND observation_count <= complete_year_count
    ),
    seasonal_index DOUBLE NOT NULL CHECK (seasonal_index >= 0),
    index_deviation DOUBLE NOT NULL,
    is_peak_month BOOLEAN NOT NULL,
    is_trough_month BOOLEAN NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (
        scope_name,
        cadence,
        period_start,
        period_end,
        game_theme,
        metric_name,
        calendar_month
    ),
    CHECK (period_start <= period_end)
)
"""

_CREATE_THEME_LAUNCH_WINDOW_OUTCOMES_SQL = """
CREATE TABLE IF NOT EXISTS theme_launch_window_outcomes (
    scope_name VARCHAR NOT NULL,
    cadence VARCHAR NOT NULL CHECK (cadence = 'monthly'),
    decision_period_start DATE NOT NULL,
    decision_period_end DATE NOT NULL,
    outcome_horizon_months INTEGER NOT NULL CHECK (outcome_horizon_months IN (1, 2, 3)),
    outcome_period_start DATE NOT NULL,
    outcome_period_end DATE NOT NULL,
    game_theme VARCHAR NOT NULL,
    backtest_policy_version VARCHAR NOT NULL CHECK (backtest_policy_version = 'BACKTEST001_V1'),
    model_policy_version VARCHAR NOT NULL CHECK (model_policy_version = 'MODEL002_V1'),
    legacy_is_actionable BOOLEAN NOT NULL,
    legacy_exclusion_reason VARCHAR NULL,
    legacy_confidence_score DOUBLE NOT NULL CHECK (legacy_confidence_score BETWEEN 0 AND 100),
    legacy_6m_momentum_score DOUBLE NULL,
    legacy_6m_momentum_rank INTEGER NULL CHECK (legacy_6m_momentum_rank IS NULL OR legacy_6m_momentum_rank >= 1),
    has_6m_history BOOLEAN NOT NULL CHECK (has_6m_history),
    has_12m_history BOOLEAN NOT NULL,
    has_36m_history BOOLEAN NOT NULL,
    direction_6m VARCHAR NOT NULL CHECK (direction_6m IN ('up', 'down', 'flat', 'mixed', 'insufficient_history')),
    direction_12m VARCHAR NOT NULL CHECK (direction_12m IN ('up', 'down', 'flat', 'mixed', 'insufficient_history')),
    direction_36m VARCHAR NOT NULL CHECK (direction_36m IN ('up', 'down', 'flat', 'mixed', 'insufficient_history')),
    direction_evidence_count_6m INTEGER NOT NULL CHECK (direction_evidence_count_6m BETWEEN 0 AND 3),
    direction_evidence_count_12m INTEGER NOT NULL CHECK (direction_evidence_count_12m BETWEEN 0 AND 3),
    direction_evidence_count_36m INTEGER NOT NULL CHECK (direction_evidence_count_36m BETWEEN 0 AND 3),
    median_normalized_slope_6m DOUBLE NULL,
    median_normalized_slope_12m DOUBLE NULL,
    median_normalized_slope_36m DOUBLE NULL,
    stability_cv_median_6m DOUBLE NULL CHECK (stability_cv_median_6m IS NULL OR stability_cv_median_6m >= 0),
    stability_cv_median_12m DOUBLE NULL CHECK (stability_cv_median_12m IS NULL OR stability_cv_median_12m >= 0),
    stability_cv_median_36m DOUBLE NULL CHECK (stability_cv_median_36m IS NULL OR stability_cv_median_36m >= 0),
    stability_band_6m VARCHAR NOT NULL CHECK (stability_band_6m IN ('stable', 'variable', 'volatile', 'insufficient_history')),
    stability_band_12m VARCHAR NOT NULL CHECK (stability_band_12m IN ('stable', 'variable', 'volatile', 'insufficient_history')),
    stability_band_36m VARCHAR NOT NULL CHECK (stability_band_36m IN ('stable', 'variable', 'volatile', 'insufficient_history')),
    lifecycle_stage VARCHAR NOT NULL CHECK (lifecycle_stage IN ('insufficient_history', 'emerging', 'accelerating', 'growing', 'mature', 'recovering', 'declining', 'mixed')),
    first_active_left_censored BOOLEAN NOT NULL,
    months_since_first_active INTEGER NULL CHECK (months_since_first_active IS NULL OR months_since_first_active >= 0),
    decision_product_count INTEGER NOT NULL CHECK (decision_product_count >= 1),
    decision_product_share DOUBLE NOT NULL CHECK (decision_product_share BETWEEN 0 AND 1),
    decision_downloads_sum DOUBLE NULL,
    decision_downloads_share DOUBLE NULL CHECK (decision_downloads_share IS NULL OR decision_downloads_share BETWEEN 0 AND 1),
    decision_revenue_usd_sum DOUBLE NULL,
    decision_revenue_usd_share DOUBLE NULL CHECK (decision_revenue_usd_share IS NULL OR decision_revenue_usd_share BETWEEN 0 AND 1),
    decision_downloads_product_hhi DOUBLE NULL CHECK (decision_downloads_product_hhi IS NULL OR decision_downloads_product_hhi BETWEEN 0 AND 1),
    decision_revenue_usd_product_hhi DOUBLE NULL CHECK (decision_revenue_usd_product_hhi IS NULL OR decision_revenue_usd_product_hhi BETWEEN 0 AND 1),
    decision_publisher_downloads_hhi DOUBLE NULL CHECK (decision_publisher_downloads_hhi IS NULL OR decision_publisher_downloads_hhi BETWEEN 0 AND 1),
    decision_publisher_revenue_usd_hhi DOUBLE NULL CHECK (decision_publisher_revenue_usd_hhi IS NULL OR decision_publisher_revenue_usd_hhi BETWEEN 0 AND 1),
    decision_top_500_turnover_rate DOUBLE NULL CHECK (decision_top_500_turnover_rate IS NULL OR decision_top_500_turnover_rate BETWEEN 0 AND 1),
    decision_market_new_entry_share DOUBLE NULL CHECK (decision_market_new_entry_share IS NULL OR decision_market_new_entry_share BETWEEN 0 AND 1),
    decision_downloads_market_new_entry_share_of_current DOUBLE NULL CHECK (decision_downloads_market_new_entry_share_of_current IS NULL OR decision_downloads_market_new_entry_share_of_current BETWEEN 0 AND 1),
    decision_revenue_usd_market_new_entry_share_of_current DOUBLE NULL CHECK (decision_revenue_usd_market_new_entry_share_of_current IS NULL OR decision_revenue_usd_market_new_entry_share_of_current BETWEEN 0 AND 1),
    decision_downloads_top_10_positive_contribution_share DOUBLE NULL CHECK (decision_downloads_top_10_positive_contribution_share IS NULL OR decision_downloads_top_10_positive_contribution_share BETWEEN 0 AND 1),
    decision_revenue_usd_top_10_positive_contribution_share DOUBLE NULL CHECK (decision_revenue_usd_top_10_positive_contribution_share IS NULL OR decision_revenue_usd_top_10_positive_contribution_share BETWEEN 0 AND 1),
    decision_downloads_expected_seasonal_index DOUBLE NULL CHECK (decision_downloads_expected_seasonal_index IS NULL OR decision_downloads_expected_seasonal_index >= 0),
    decision_revenue_usd_expected_seasonal_index DOUBLE NULL CHECK (decision_revenue_usd_expected_seasonal_index IS NULL OR decision_revenue_usd_expected_seasonal_index >= 0),
    decision_downloads_seasonality_amplitude DOUBLE NULL CHECK (decision_downloads_seasonality_amplitude IS NULL OR decision_downloads_seasonality_amplitude >= 0),
    decision_revenue_usd_seasonality_amplitude DOUBLE NULL CHECK (decision_revenue_usd_seasonality_amplitude IS NULL OR decision_revenue_usd_seasonality_amplitude >= 0),
    future_theme_present BOOLEAN NOT NULL,
    future_product_count INTEGER NOT NULL CHECK (future_product_count >= 0),
    future_product_share DOUBLE NOT NULL CHECK (future_product_share BETWEEN 0 AND 1),
    future_downloads_sum DOUBLE NULL,
    future_downloads_share DOUBLE NULL CHECK (future_downloads_share IS NULL OR future_downloads_share BETWEEN 0 AND 1),
    future_revenue_usd_sum DOUBLE NULL,
    future_revenue_usd_share DOUBLE NULL CHECK (future_revenue_usd_share IS NULL OR future_revenue_usd_share BETWEEN 0 AND 1),
    product_count_absolute_change DOUBLE NULL,
    product_count_relative_change DOUBLE NULL,
    product_share_absolute_change DOUBLE NULL,
    product_share_relative_change DOUBLE NULL,
    downloads_sum_absolute_change DOUBLE NULL,
    downloads_sum_relative_change DOUBLE,
    downloads_share_absolute_change DOUBLE NULL,
    downloads_share_relative_change DOUBLE NULL,
    revenue_usd_sum_absolute_change DOUBLE NULL,
    revenue_usd_sum_relative_change DOUBLE NULL,
    revenue_usd_share_absolute_change DOUBLE NULL,
    revenue_usd_share_relative_change DOUBLE NULL,
    product_share_change_direction VARCHAR NOT NULL CHECK (product_share_change_direction IN ('up', 'down', 'unchanged', 'unavailable')),
    downloads_share_change_direction VARCHAR NOT NULL CHECK (downloads_share_change_direction IN ('up', 'down', 'unchanged', 'unavailable')),
    revenue_usd_share_change_direction VARCHAR NOT NULL CHECK (revenue_usd_share_change_direction IN ('up', 'down', 'unchanged', 'unavailable')),
    future_product_share_percentile DOUBLE NOT NULL CHECK (future_product_share_percentile BETWEEN 0 AND 1),
    future_downloads_share_percentile DOUBLE NULL CHECK (future_downloads_share_percentile IS NULL OR future_downloads_share_percentile BETWEEN 0 AND 1),
    future_revenue_usd_share_percentile DOUBLE NULL CHECK (future_revenue_usd_share_percentile IS NULL OR future_revenue_usd_share_percentile BETWEEN 0 AND 1),
    future_product_share_top_quintile BOOLEAN NULL,
    future_downloads_share_top_quintile BOOLEAN NULL,
    future_revenue_usd_share_top_quintile BOOLEAN NULL,
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (scope_name, cadence, decision_period_start, decision_period_end, game_theme, outcome_horizon_months),
    CHECK (decision_period_start <= decision_period_end),
    CHECK (outcome_period_start <= outcome_period_end),
    CHECK (future_theme_present OR (future_product_count = 0 AND future_product_share = 0 AND future_downloads_sum = 0 AND future_downloads_share = 0 AND future_revenue_usd_sum = 0 AND future_revenue_usd_share = 0))
)
"""

_CREATE_THEME_BACKTEST_FEATURE_METRICS_SQL = """
CREATE TABLE IF NOT EXISTS theme_backtest_feature_metrics (
    scope_name VARCHAR NOT NULL,
    cadence VARCHAR NOT NULL CHECK (cadence = 'monthly'),
    backtest_start DATE NOT NULL,
    backtest_end DATE NOT NULL,
    outcome_horizon_months INTEGER NOT NULL CHECK (outcome_horizon_months IN (1, 2, 3)),
    feature_name VARCHAR NOT NULL,
    feature_group VARCHAR NOT NULL,
    feature_hypothesis VARCHAR NOT NULL CHECK (feature_hypothesis IN ('higher_better', 'lower_better')),
    outcome_name VARCHAR NOT NULL CHECK (outcome_name IN ('future_downloads_share', 'future_revenue_usd_share', 'downloads_share_absolute_change', 'revenue_usd_share_absolute_change')),
    backtest_policy_version VARCHAR NOT NULL CHECK (backtest_policy_version = 'BACKTEST001_V1'),
    candidate_row_count INTEGER NOT NULL CHECK (candidate_row_count >= 0),
    eligible_row_count INTEGER NOT NULL CHECK (eligible_row_count >= 0 AND eligible_row_count <= candidate_row_count),
    coverage_ratio DOUBLE NOT NULL CHECK (coverage_ratio BETWEEN 0 AND 1),
    decision_month_count INTEGER NOT NULL CHECK (decision_month_count >= 0 AND decision_month_count <= eligible_row_count),
    correlation_cohort_count INTEGER NOT NULL CHECK (correlation_cohort_count >= 0 AND correlation_cohort_count <= decision_month_count),
    mean_spearman DOUBLE NULL CHECK (mean_spearman IS NULL OR mean_spearman BETWEEN -1 AND 1),
    median_spearman DOUBLE NULL CHECK (median_spearman IS NULL OR median_spearman BETWEEN -1 AND 1),
    p25_spearman DOUBLE NULL CHECK (p25_spearman IS NULL OR p25_spearman BETWEEN -1 AND 1),
    p75_spearman DOUBLE NULL CHECK (p75_spearman IS NULL OR p75_spearman BETWEEN -1 AND 1),
    positive_spearman_cohort_count INTEGER NULL CHECK (positive_spearman_cohort_count IS NULL OR positive_spearman_cohort_count <= correlation_cohort_count),
    positive_spearman_cohort_ratio DOUBLE NULL CHECK (positive_spearman_cohort_ratio IS NULL OR positive_spearman_cohort_ratio BETWEEN 0 AND 1),
    positive_spearman_ci_low DOUBLE NULL CHECK (positive_spearman_ci_low IS NULL OR positive_spearman_ci_low BETWEEN 0 AND 1),
    positive_spearman_ci_high DOUBLE NULL CHECK (positive_spearman_ci_high IS NULL OR positive_spearman_ci_high BETWEEN 0 AND 1),
    top_quintile_cohort_count INTEGER NULL CHECK (top_quintile_cohort_count IS NULL OR top_quintile_cohort_count >= 0),
    top_quintile_selected_count INTEGER NULL CHECK (top_quintile_selected_count IS NULL OR (top_quintile_selected_count >= 0 AND top_quintile_selected_count <= eligible_row_count)),
    top_quintile_hit_count INTEGER NULL CHECK (top_quintile_hit_count IS NULL OR top_quintile_hit_count <= top_quintile_selected_count),
    top_quintile_hit_rate DOUBLE NULL CHECK (top_quintile_hit_rate IS NULL OR top_quintile_hit_rate BETWEEN 0 AND 1),
    top_quintile_hit_ci_low DOUBLE NULL CHECK (top_quintile_hit_ci_low IS NULL OR top_quintile_hit_ci_low BETWEEN 0 AND 1),
    top_quintile_hit_ci_high DOUBLE NULL CHECK (top_quintile_hit_ci_high IS NULL OR top_quintile_hit_ci_high BETWEEN 0 AND 1),
    future_top_quintile_base_rate DOUBLE NULL CHECK (future_top_quintile_base_rate IS NULL OR future_top_quintile_base_rate BETWEEN 0 AND 1),
    top_quintile_lift DOUBLE NULL,
    top_quintile_outcome_mean DOUBLE NULL,
    top_quintile_outcome_median DOUBLE NULL,
    all_eligible_outcome_mean DOUBLE NULL,
    all_eligible_outcome_median DOUBLE NULL,
    top_quintile_positive_change_count INTEGER NULL,
    top_quintile_positive_change_rate DOUBLE NULL CHECK (top_quintile_positive_change_rate IS NULL OR top_quintile_positive_change_rate BETWEEN 0 AND 1),
    top_quintile_positive_change_ci_low DOUBLE NULL CHECK (top_quintile_positive_change_ci_low IS NULL OR top_quintile_positive_change_ci_low BETWEEN 0 AND 1),
    top_quintile_positive_change_ci_high DOUBLE NULL CHECK (top_quintile_positive_change_ci_high IS NULL OR top_quintile_positive_change_ci_high BETWEEN 0 AND 1),
    all_positive_change_count INTEGER NULL,
    all_positive_change_rate DOUBLE NULL CHECK (all_positive_change_rate IS NULL OR all_positive_change_rate BETWEEN 0 AND 1),
    all_positive_change_ci_low DOUBLE NULL CHECK (all_positive_change_ci_low IS NULL OR all_positive_change_ci_low BETWEEN 0 AND 1),
    all_positive_change_ci_high DOUBLE NULL CHECK (all_positive_change_ci_high IS NULL OR all_positive_change_ci_high BETWEEN 0 AND 1),
    low_sample_warning BOOLEAN NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (scope_name, cadence, backtest_start, backtest_end, outcome_horizon_months, feature_name, outcome_name, backtest_policy_version),
    CHECK (backtest_start <= backtest_end)
)
"""

_CREATE_THEME_BACKTEST_SEGMENT_METRICS_SQL = """
CREATE TABLE IF NOT EXISTS theme_backtest_segment_metrics (
    scope_name VARCHAR NOT NULL,
    cadence VARCHAR NOT NULL CHECK (cadence = 'monthly'),
    backtest_start DATE NOT NULL,
    backtest_end DATE NOT NULL,
    outcome_horizon_months INTEGER NOT NULL CHECK (outcome_horizon_months IN (1, 2, 3)),
    segment_name VARCHAR NOT NULL CHECK (segment_name IN ('legacy_actionability', 'direction_6m', 'direction_12m', 'direction_36m', 'stability_band_6m', 'stability_band_12m', 'stability_band_36m', 'lifecycle_stage')),
    segment_value VARCHAR NOT NULL,
    outcome_name VARCHAR NOT NULL CHECK (outcome_name IN ('future_downloads_share', 'future_revenue_usd_share', 'downloads_share_absolute_change', 'revenue_usd_share_absolute_change')),
    backtest_policy_version VARCHAR NOT NULL CHECK (backtest_policy_version = 'BACKTEST001_V1'),
    candidate_row_count INTEGER NOT NULL CHECK (candidate_row_count >= 0),
    eligible_row_count INTEGER NOT NULL CHECK (eligible_row_count >= 0 AND eligible_row_count <= candidate_row_count),
    coverage_ratio DOUBLE NOT NULL CHECK (coverage_ratio BETWEEN 0 AND 1),
    decision_month_count INTEGER NOT NULL CHECK (decision_month_count >= 0 AND decision_month_count <= eligible_row_count),
    segment_row_share DOUBLE NOT NULL CHECK (segment_row_share BETWEEN 0 AND 1),
    outcome_mean DOUBLE NULL,
    outcome_median DOUBLE NULL,
    outcome_p25 DOUBLE NULL,
    outcome_p75 DOUBLE NULL,
    future_top_quintile_count INTEGER NULL CHECK (future_top_quintile_count IS NULL OR future_top_quintile_count <= eligible_row_count),
    future_top_quintile_rate DOUBLE NULL CHECK (future_top_quintile_rate IS NULL OR future_top_quintile_rate BETWEEN 0 AND 1),
    future_top_quintile_ci_low DOUBLE NULL CHECK (future_top_quintile_ci_low IS NULL OR future_top_quintile_ci_low BETWEEN 0 AND 1),
    future_top_quintile_ci_high DOUBLE NULL CHECK (future_top_quintile_ci_high IS NULL OR future_top_quintile_ci_high BETWEEN 0 AND 1),
    future_top_quintile_base_rate DOUBLE NULL CHECK (future_top_quintile_base_rate IS NULL OR future_top_quintile_base_rate BETWEEN 0 AND 1),
    future_top_quintile_lift DOUBLE NULL,
    positive_change_count INTEGER NULL,
    positive_change_rate DOUBLE NULL CHECK (positive_change_rate IS NULL OR positive_change_rate BETWEEN 0 AND 1),
    positive_change_ci_low DOUBLE NULL CHECK (positive_change_ci_low IS NULL OR positive_change_ci_low BETWEEN 0 AND 1),
    positive_change_ci_high DOUBLE NULL CHECK (positive_change_ci_high IS NULL OR positive_change_ci_high BETWEEN 0 AND 1),
    low_sample_warning BOOLEAN NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (scope_name, cadence, backtest_start, backtest_end, outcome_horizon_months, segment_name, segment_value, outcome_name, backtest_policy_version),
    CHECK (backtest_start <= backtest_end)
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
_V5_TABLE_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        THEME_HORIZON_METRICS_TABLE,
        _CREATE_THEME_HORIZON_METRICS_SQL,
        THEME_HORIZON_METRICS_COLUMNS,
    ),
    (
        THEME_MODEL_SUMMARIES_TABLE,
        _CREATE_THEME_MODEL_SUMMARIES_SQL,
        THEME_MODEL_SUMMARIES_COLUMNS,
    ),
    (
        THEME_SEASONALITY_PROFILES_TABLE,
        _CREATE_THEME_SEASONALITY_PROFILES_SQL,
        THEME_SEASONALITY_PROFILES_COLUMNS,
    ),
)
_V6_TABLE_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        THEME_LAUNCH_WINDOW_OUTCOMES_TABLE,
        _CREATE_THEME_LAUNCH_WINDOW_OUTCOMES_SQL,
        THEME_LAUNCH_WINDOW_OUTCOMES_COLUMNS,
    ),
    (
        THEME_BACKTEST_FEATURE_METRICS_TABLE,
        _CREATE_THEME_BACKTEST_FEATURE_METRICS_SQL,
        THEME_BACKTEST_FEATURE_METRICS_COLUMNS,
    ),
    (
        THEME_BACKTEST_SEGMENT_METRICS_TABLE,
        _CREATE_THEME_BACKTEST_SEGMENT_METRICS_SQL,
        THEME_BACKTEST_SEGMENT_METRICS_COLUMNS,
    ),
)
_TABLE_DEFINITIONS = (
    *_TABLE_DEFINITIONS,
    *_V3_TABLE_DEFINITIONS,
    *_V4_TABLE_DEFINITIONS,
    *_V5_TABLE_DEFINITIONS,
    *_V6_TABLE_DEFINITIONS,
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

        _assert_table_definitions(connection, _V4_TABLE_DEFINITIONS)

        if newest_version < 5:
            _apply_version_five(connection)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                [5],
            )

        _assert_table_definitions(connection, _V5_TABLE_DEFINITIONS)

        if newest_version < 6:
            _apply_version_six(connection)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
                [6],
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
    _assert_table_definitions(connection, _table_definitions_for_version(newest_version))


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


def _apply_version_five(connection: duckdb.DuckDBPyConnection) -> None:
    for _table_name, create_sql, _columns in _V5_TABLE_DEFINITIONS:
        connection.execute(create_sql)


def _apply_version_six(connection: duckdb.DuckDBPyConnection) -> None:
    for _table_name, create_sql, _columns in _V6_TABLE_DEFINITIONS:
        connection.execute(create_sql)


def _assert_required_tables(connection: duckdb.DuckDBPyConnection) -> None:
    _assert_table_definitions(connection, _TABLE_DEFINITIONS)


def _table_definitions_for_version(
    schema_version: int,
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Return only tables guaranteed by an existing schema version."""

    definitions: tuple[tuple[str, str, tuple[str, ...]], ...] = ()
    for minimum_version, version_definitions in (
        (1, _V1_TABLE_DEFINITIONS),
        (2, _V2_TABLE_DEFINITIONS),
        (3, _V3_TABLE_DEFINITIONS),
        (4, _V4_TABLE_DEFINITIONS),
        (5, _V5_TABLE_DEFINITIONS),
        (6, _V6_TABLE_DEFINITIONS),
    ):
        if schema_version >= minimum_version:
            definitions += version_definitions
    return definitions


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
