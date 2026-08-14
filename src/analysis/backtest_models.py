"""Typed BACKTEST-001 rows and the preregistered evaluation registry.

The models in this module are internal analytical rows.  They intentionally
depend only on the standard library and the already-approved MODEL-002 enum
values; they do not know about DuckDB, Sensor Tower, Feishu, or workflow
configuration.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from math import isclose, isfinite

from .errors import AggregationValidationError
from .model_v2_models import (
    DIRECTION_VALUES,
    LIFECYCLE_STAGES,
    MODEL_POLICY_VERSION,
    STABILITY_BANDS,
)

BACKTEST_POLICY_VERSION = "BACKTEST001_V1"
BACKTEST_OUTCOME_HORIZONS: tuple[int, ...] = (1, 2, 3)
BACKTEST_TOP_FRACTION = 0.20
BACKTEST_MIN_COHORT_SIZE = 5
BACKTEST_LOW_SAMPLE_ROW_COUNT = 30
BACKTEST_LOW_SAMPLE_COHORT_COUNT = 6
BACKTEST_WILSON_Z = 1.959963984540054

PRIMARY_OUTCOME_NAMES: tuple[str, ...] = (
    "future_downloads_share",
    "future_revenue_usd_share",
    "downloads_share_absolute_change",
    "revenue_usd_share_absolute_change",
)
BACKTEST_PRIMARY_OUTCOMES = PRIMARY_OUTCOME_NAMES


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AggregationValidationError(f"{field_name} must be a non-empty string")
    return value


def _require_raw_label(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise AggregationValidationError(f"{field_name} must be a string")
    return value


def _require_date(value: object, *, field_name: str) -> date:
    if type(value) is not date:
        raise AggregationValidationError(f"{field_name} must be a date")
    return value


def _require_natural_month(period_start: object, period_end: object, *, field_name: str) -> None:
    start = _require_date(period_start, field_name=f"{field_name}_start")
    end = _require_date(period_end, field_name=f"{field_name}_end")
    expected_end = date(
        start.year,
        start.month,
        calendar.monthrange(start.year, start.month)[1],
    )
    if start.day != 1 or end != expected_end:
        raise AggregationValidationError(f"{field_name} must be a natural calendar month")


def month_shift(month_start: date, offset: int) -> date:
    """Shift a natural month start by an integer number of calendar months."""

    month_index = month_start.year * 12 + month_start.month - 1 + offset
    year, zero_month = divmod(month_index, 12)
    return date(year, zero_month + 1, 1)


def natural_month_end(month_start: date) -> date:
    """Return the final day for a natural month start."""

    return date(
        month_start.year,
        month_start.month,
        calendar.monthrange(month_start.year, month_start.month)[1],
    )


def _require_count(value: object, *, field_name: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AggregationValidationError(f"{field_name} must be a non-negative integer")
    if maximum is not None and value > maximum:
        raise AggregationValidationError(f"{field_name} must not exceed {maximum}")
    return value


def _optional_count(value: object, *, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_count(value, field_name=field_name)


def _optional_number(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AggregationValidationError(f"{field_name} must be a number")
    numeric_value = float(value)
    if not isfinite(numeric_value):
        raise AggregationValidationError(f"{field_name} must be finite")
    return numeric_value


def _optional_ratio(value: object, *, field_name: str) -> float | None:
    numeric_value = _optional_number(value, field_name=field_name)
    if numeric_value is not None and not 0 <= numeric_value <= 1:
        raise AggregationValidationError(f"{field_name} must be between 0 and 1")
    return numeric_value


def _require_timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AggregationValidationError(f"{field_name} must be timezone-aware")
    return value


def _validate_optional_stat(
    value: object, *, field_name: str, low: float, high: float
) -> float | None:
    numeric_value = _optional_number(value, field_name=field_name)
    if numeric_value is not None and not low <= numeric_value <= high:
        raise AggregationValidationError(f"{field_name} must be between {low} and {high}")
    return numeric_value


def _validate_count_rate(
    count: int | None,
    rate: float | None,
    *,
    denominator: int,
    count_name: str,
    rate_name: str,
) -> tuple[int | None, float | None]:
    normalized_count = _optional_count(count, field_name=count_name)
    normalized_rate = _optional_ratio(rate, field_name=rate_name)
    if normalized_count is None:
        if normalized_rate is not None:
            raise AggregationValidationError(f"{rate_name} requires {count_name}")
        return None, None
    if normalized_count > denominator:
        raise AggregationValidationError(f"{count_name} must not exceed its denominator")
    if denominator == 0:
        if normalized_count != 0 or normalized_rate is not None:
            raise AggregationValidationError(f"{rate_name} is invalid with zero denominator")
    elif normalized_rate is None or not isclose(
        normalized_rate,
        normalized_count / denominator,
        rel_tol=1e-9,
        abs_tol=1e-12,
    ):
        raise AggregationValidationError(f"{rate_name} does not reconcile with {count_name}")
    return normalized_count, normalized_rate


@dataclass(frozen=True, slots=True)
class BacktestFeatureDefinition:
    """One preregistered continuous feature and its evaluation orientation."""

    feature_name: str
    feature_group: str
    feature_hypothesis: str

    def __post_init__(self) -> None:
        _require_text(self.feature_name, field_name="feature_name")
        _require_text(self.feature_group, field_name="feature_group")
        if self.feature_hypothesis not in {"higher_better", "lower_better"}:
            raise AggregationValidationError("feature_hypothesis is not approved")


@dataclass(frozen=True, slots=True)
class ThemeLaunchWindowOutcome:
    """One leakage-safe decision-month/theme/future-horizon outcome row."""

    scope_name: str
    cadence: str
    decision_period_start: date
    decision_period_end: date
    outcome_horizon_months: int
    outcome_period_start: date
    outcome_period_end: date
    game_theme: str
    backtest_policy_version: str
    model_policy_version: str
    legacy_is_actionable: bool
    legacy_exclusion_reason: str | None
    legacy_confidence_score: float
    legacy_6m_momentum_score: float | None
    legacy_6m_momentum_rank: int | None
    has_6m_history: bool
    has_12m_history: bool
    has_36m_history: bool
    direction_6m: str
    direction_12m: str
    direction_36m: str
    direction_evidence_count_6m: int
    direction_evidence_count_12m: int
    direction_evidence_count_36m: int
    median_normalized_slope_6m: float | None
    median_normalized_slope_12m: float | None
    median_normalized_slope_36m: float | None
    stability_cv_median_6m: float | None
    stability_cv_median_12m: float | None
    stability_cv_median_36m: float | None
    stability_band_6m: str
    stability_band_12m: str
    stability_band_36m: str
    lifecycle_stage: str
    first_active_left_censored: bool
    months_since_first_active: int | None
    decision_product_count: int
    decision_product_share: float
    decision_downloads_sum: float | None
    decision_downloads_share: float | None
    decision_revenue_usd_sum: float | None
    decision_revenue_usd_share: float | None
    decision_downloads_product_hhi: float | None
    decision_revenue_usd_product_hhi: float | None
    decision_publisher_downloads_hhi: float | None
    decision_publisher_revenue_usd_hhi: float | None
    decision_top_500_turnover_rate: float | None
    decision_market_new_entry_share: float | None
    decision_downloads_market_new_entry_share_of_current: float | None
    decision_revenue_usd_market_new_entry_share_of_current: float | None
    decision_downloads_top_10_positive_contribution_share: float | None
    decision_revenue_usd_top_10_positive_contribution_share: float | None
    decision_downloads_expected_seasonal_index: float | None
    decision_revenue_usd_expected_seasonal_index: float | None
    decision_downloads_seasonality_amplitude: float | None
    decision_revenue_usd_seasonality_amplitude: float | None
    future_theme_present: bool
    future_product_count: int
    future_product_share: float
    future_downloads_sum: float | None
    future_downloads_share: float | None
    future_revenue_usd_sum: float | None
    future_revenue_usd_share: float | None
    product_count_absolute_change: float | None
    product_count_relative_change: float | None
    product_share_absolute_change: float | None
    product_share_relative_change: float | None
    downloads_sum_absolute_change: float | None
    downloads_sum_relative_change: float | None
    downloads_share_absolute_change: float | None
    downloads_share_relative_change: float | None
    revenue_usd_sum_absolute_change: float | None
    revenue_usd_sum_relative_change: float | None
    revenue_usd_share_absolute_change: float | None
    revenue_usd_share_relative_change: float | None
    product_share_change_direction: str
    downloads_share_change_direction: str
    revenue_usd_share_change_direction: str
    future_product_share_percentile: float
    future_downloads_share_percentile: float | None
    future_revenue_usd_share_percentile: float | None
    future_product_share_top_quintile: bool | None
    future_downloads_share_top_quintile: bool | None
    future_revenue_usd_share_top_quintile: bool | None
    calculated_at: datetime

    @property
    def identity(self) -> tuple[str, str, date, date, str, int]:
        """Return the raw outcome identity."""

        return (
            self.scope_name,
            self.cadence,
            self.decision_period_start,
            self.decision_period_end,
            self.game_theme,
            self.outcome_horizon_months,
        )

    @property
    def decision_period_key(self) -> tuple[str, str, date, date]:
        """Return the decision-month identity."""

        return (
            self.scope_name,
            self.cadence,
            self.decision_period_start,
            self.decision_period_end,
        )

    def __post_init__(self) -> None:
        _require_text(self.scope_name, field_name="scope_name")
        if self.cadence != "monthly":
            raise AggregationValidationError("cadence must equal monthly")
        _require_natural_month(
            self.decision_period_start,
            self.decision_period_end,
            field_name="decision_period",
        )
        _require_natural_month(
            self.outcome_period_start,
            self.outcome_period_end,
            field_name="outcome_period",
        )
        if self.outcome_horizon_months not in BACKTEST_OUTCOME_HORIZONS:
            raise AggregationValidationError("outcome_horizon_months is not approved")
        expected_outcome = month_shift(self.decision_period_start, self.outcome_horizon_months)
        if self.outcome_period_start != expected_outcome:
            raise AggregationValidationError("outcome period does not match its horizon")
        if not isinstance(self.game_theme, str):
            raise AggregationValidationError("game_theme must be a string")
        if self.backtest_policy_version != BACKTEST_POLICY_VERSION:
            raise AggregationValidationError("backtest_policy_version is not approved")
        if self.model_policy_version != MODEL_POLICY_VERSION:
            raise AggregationValidationError("model_policy_version is not approved")

        if not isinstance(self.legacy_is_actionable, bool):
            raise AggregationValidationError("legacy_is_actionable must be a boolean")
        if self.legacy_exclusion_reason is not None:
            _require_text(self.legacy_exclusion_reason, field_name="legacy_exclusion_reason")
        for history_field_name, history_value in (
            ("has_6m_history", self.has_6m_history),
            ("has_12m_history", self.has_12m_history),
            ("has_36m_history", self.has_36m_history),
            ("first_active_left_censored", self.first_active_left_censored),
            ("future_theme_present", self.future_theme_present),
        ):
            if not isinstance(history_value, bool):
                raise AggregationValidationError(f"{history_field_name} must be a boolean")
        if not self.has_6m_history:
            raise AggregationValidationError("raw outcomes require 6M history")

        _optional_number(self.legacy_confidence_score, field_name="legacy_confidence_score")
        if not 0 <= self.legacy_confidence_score <= 100:
            raise AggregationValidationError("legacy_confidence_score must be between 0 and 100")
        _optional_number(self.legacy_6m_momentum_score, field_name="legacy_6m_momentum_score")
        _optional_count(self.legacy_6m_momentum_rank, field_name="legacy_6m_momentum_rank")
        if self.legacy_6m_momentum_rank is not None and self.legacy_6m_momentum_rank < 1:
            raise AggregationValidationError("legacy_6m_momentum_rank must be positive")
        for direction_field_name, direction_value in (
            ("direction_6m", self.direction_6m),
            ("direction_12m", self.direction_12m),
            ("direction_36m", self.direction_36m),
        ):
            if direction_value not in DIRECTION_VALUES:
                raise AggregationValidationError(f"{direction_field_name} is not approved")
        for stability_field_name, stability_value in (
            ("stability_band_6m", self.stability_band_6m),
            ("stability_band_12m", self.stability_band_12m),
            ("stability_band_36m", self.stability_band_36m),
        ):
            if stability_value not in STABILITY_BANDS:
                raise AggregationValidationError(f"{stability_field_name} is not approved")
        if self.lifecycle_stage not in LIFECYCLE_STAGES:
            raise AggregationValidationError("lifecycle_stage is not approved")
        for evidence_field_name, evidence_value in (
            ("direction_evidence_count_6m", self.direction_evidence_count_6m),
            ("direction_evidence_count_12m", self.direction_evidence_count_12m),
            ("direction_evidence_count_36m", self.direction_evidence_count_36m),
        ):
            _require_count(evidence_value, field_name=evidence_field_name, maximum=3)
        _optional_count(self.months_since_first_active, field_name="months_since_first_active")

        _require_count(self.decision_product_count, field_name="decision_product_count")
        if self.decision_product_count < 1:
            raise AggregationValidationError("decision_product_count must be positive")
        if (
            _optional_ratio(self.decision_product_share, field_name="decision_product_share")
            is None
        ):
            raise AggregationValidationError("decision_product_share must be present")
        for field_name in (
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
        ):
            if field_name.endswith("share") or "share" in field_name or field_name.endswith("rate"):
                _optional_ratio(getattr(self, field_name), field_name=field_name)
            else:
                _optional_number(getattr(self, field_name), field_name=field_name)

        _require_count(self.future_product_count, field_name="future_product_count")
        if self.future_theme_present and self.future_product_count < 1:
            raise AggregationValidationError("present future themes require a product")
        if _optional_ratio(self.future_product_share, field_name="future_product_share") is None:
            raise AggregationValidationError("future_product_share must be present")
        for field_name in (
            "future_downloads_sum",
            "future_downloads_share",
            "future_revenue_usd_sum",
            "future_revenue_usd_share",
        ):
            _optional_number(getattr(self, field_name), field_name=field_name)
        if not self.future_theme_present:
            if any(
                getattr(self, field_name) != 0
                for field_name in (
                    "future_product_count",
                    "future_product_share",
                    "future_downloads_sum",
                    "future_downloads_share",
                    "future_revenue_usd_sum",
                    "future_revenue_usd_share",
                )
            ):
                raise AggregationValidationError("absent future themes must be zero-filled")

        change_fields = (
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
        )
        for field_name in change_fields:
            _optional_number(getattr(self, field_name), field_name=field_name)
        _validate_change_pair(
            self.decision_product_count,
            self.future_product_count,
            self.product_count_absolute_change,
            self.product_count_relative_change,
            field_name="product_count",
        )
        _validate_change_pair(
            self.decision_product_share,
            self.future_product_share,
            self.product_share_absolute_change,
            self.product_share_relative_change,
            field_name="product_share",
        )
        for name, decision, future, absolute, relative in (
            (
                "downloads_sum",
                self.decision_downloads_sum,
                self.future_downloads_sum,
                self.downloads_sum_absolute_change,
                self.downloads_sum_relative_change,
            ),
            (
                "downloads_share",
                self.decision_downloads_share,
                self.future_downloads_share,
                self.downloads_share_absolute_change,
                self.downloads_share_relative_change,
            ),
            (
                "revenue_usd_sum",
                self.decision_revenue_usd_sum,
                self.future_revenue_usd_sum,
                self.revenue_usd_sum_absolute_change,
                self.revenue_usd_sum_relative_change,
            ),
            (
                "revenue_usd_share",
                self.decision_revenue_usd_share,
                self.future_revenue_usd_share,
                self.revenue_usd_share_absolute_change,
                self.revenue_usd_share_relative_change,
            ),
        ):
            _validate_change_pair(decision, future, absolute, relative, field_name=name)

        directions = {
            "product_share_change_direction": self.product_share_change_direction,
            "downloads_share_change_direction": self.downloads_share_change_direction,
            "revenue_usd_share_change_direction": self.revenue_usd_share_change_direction,
        }
        if any(
            value not in {"up", "down", "unchanged", "unavailable"} for value in directions.values()
        ):
            raise AggregationValidationError("change direction is not approved")
        for field_name in (
            "future_product_share_percentile",
            "future_downloads_share_percentile",
            "future_revenue_usd_share_percentile",
        ):
            _optional_ratio(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "future_product_share_top_quintile",
            "future_downloads_share_top_quintile",
            "future_revenue_usd_share_top_quintile",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, bool):
                raise AggregationValidationError(f"{field_name} must be a boolean or NULL")
        _require_timestamp(self.calculated_at, field_name="calculated_at")


def _validate_change_pair(
    decision: float | int | None,
    future: float | int | None,
    absolute: float | None,
    relative: float | None,
    *,
    field_name: str,
) -> None:
    if decision is None or future is None:
        if absolute is not None or relative is not None:
            raise AggregationValidationError(f"{field_name} changes require two numeric values")
        return
    expected_absolute = float(future) - float(decision)
    if absolute is None or not isclose(absolute, expected_absolute, rel_tol=1e-9, abs_tol=1e-12):
        raise AggregationValidationError(f"{field_name} absolute change does not reconcile")
    if float(decision) > 0:
        expected_relative = expected_absolute / float(decision)
        if relative is None or not isclose(
            relative, expected_relative, rel_tol=1e-9, abs_tol=1e-12
        ):
            raise AggregationValidationError(f"{field_name} relative change does not reconcile")
    elif relative is not None:
        raise AggregationValidationError(
            f"{field_name} relative change requires positive decision value"
        )


@dataclass(frozen=True, slots=True)
class ThemeBacktestFeatureMetric:
    """One aggregate continuous-feature/primary-outcome evaluation row."""

    scope_name: str
    cadence: str
    backtest_start: date
    backtest_end: date
    outcome_horizon_months: int
    feature_name: str
    feature_group: str
    feature_hypothesis: str
    outcome_name: str
    backtest_policy_version: str
    candidate_row_count: int
    eligible_row_count: int
    coverage_ratio: float
    decision_month_count: int
    correlation_cohort_count: int
    mean_spearman: float | None
    median_spearman: float | None
    p25_spearman: float | None
    p75_spearman: float | None
    positive_spearman_cohort_count: int | None
    positive_spearman_cohort_ratio: float | None
    positive_spearman_ci_low: float | None
    positive_spearman_ci_high: float | None
    top_quintile_cohort_count: int | None
    top_quintile_selected_count: int | None
    top_quintile_hit_count: int | None
    top_quintile_hit_rate: float | None
    top_quintile_hit_ci_low: float | None
    top_quintile_hit_ci_high: float | None
    future_top_quintile_base_rate: float | None
    top_quintile_lift: float | None
    top_quintile_outcome_mean: float | None
    top_quintile_outcome_median: float | None
    all_eligible_outcome_mean: float | None
    all_eligible_outcome_median: float | None
    top_quintile_positive_change_count: int | None
    top_quintile_positive_change_rate: float | None
    top_quintile_positive_change_ci_low: float | None
    top_quintile_positive_change_ci_high: float | None
    all_positive_change_count: int | None
    all_positive_change_rate: float | None
    all_positive_change_ci_low: float | None
    all_positive_change_ci_high: float | None
    low_sample_warning: bool
    calculated_at: datetime

    @property
    def identity(self) -> tuple[object, ...]:
        return (
            self.scope_name,
            self.cadence,
            self.backtest_start,
            self.backtest_end,
            self.outcome_horizon_months,
            self.feature_name,
            self.outcome_name,
            self.backtest_policy_version,
        )

    def __post_init__(self) -> None:
        _validate_aggregate_identity(
            self.scope_name,
            self.cadence,
            self.backtest_start,
            self.backtest_end,
            self.outcome_horizon_months,
            self.outcome_name,
            self.backtest_policy_version,
        )
        definition = FEATURE_DEFINITION_BY_NAME.get(self.feature_name)
        if definition is None:
            raise AggregationValidationError("feature_name is not approved")
        if (self.feature_group, self.feature_hypothesis) != (
            definition.feature_group,
            definition.feature_hypothesis,
        ):
            raise AggregationValidationError("feature registry metadata does not match")
        for field_name, value in (
            ("candidate_row_count", self.candidate_row_count),
            ("eligible_row_count", self.eligible_row_count),
            ("decision_month_count", self.decision_month_count),
            ("correlation_cohort_count", self.correlation_cohort_count),
        ):
            _require_count(value, field_name=field_name)
        top_quintile_cohort_count = _optional_count(
            self.top_quintile_cohort_count,
            field_name="top_quintile_cohort_count",
        )
        top_quintile_selected_count = _optional_count(
            self.top_quintile_selected_count,
            field_name="top_quintile_selected_count",
        )
        if self.eligible_row_count > self.candidate_row_count:
            raise AggregationValidationError("eligible_row_count exceeds candidate_row_count")
        if self.decision_month_count > self.eligible_row_count:
            raise AggregationValidationError("decision_month_count exceeds eligible_row_count")
        if self.correlation_cohort_count > self.decision_month_count:
            raise AggregationValidationError("correlation cohorts exceed decision months")
        if top_quintile_cohort_count is None:
            if top_quintile_selected_count is not None:
                raise AggregationValidationError(
                    "top-quintile selected count requires valid cohorts"
                )
        else:
            if top_quintile_cohort_count > self.decision_month_count:
                raise AggregationValidationError("top-quintile cohorts exceed decision months")
            if top_quintile_selected_count is None:
                raise AggregationValidationError(
                    "top-quintile cohort count requires a selected count"
                )
            if top_quintile_selected_count > self.eligible_row_count:
                raise AggregationValidationError("top-quintile selection exceeds eligible rows")
        candidate_ratio = (
            0.0
            if self.candidate_row_count == 0
            else self.eligible_row_count / self.candidate_row_count
        )
        if not isclose(self.coverage_ratio, candidate_ratio, rel_tol=1e-9, abs_tol=1e-12):
            raise AggregationValidationError("coverage_ratio does not reconcile")
        _optional_ratio(self.coverage_ratio, field_name="coverage_ratio")
        for field_name in (
            "mean_spearman",
            "median_spearman",
            "p25_spearman",
            "p75_spearman",
        ):
            _validate_optional_stat(
                getattr(self, field_name), field_name=field_name, low=-1, high=1
            )
        positive_count, positive_ratio = _validate_count_rate(
            self.positive_spearman_cohort_count,
            self.positive_spearman_cohort_ratio,
            denominator=self.correlation_cohort_count,
            count_name="positive_spearman_cohort_count",
            rate_name="positive_spearman_cohort_ratio",
        )
        object.__setattr__(self, "positive_spearman_cohort_count", positive_count)
        object.__setattr__(self, "positive_spearman_cohort_ratio", positive_ratio)
        _validate_interval(
            self.positive_spearman_ci_low,
            self.positive_spearman_ci_high,
            field_name="positive_spearman_ci",
        )
        if top_quintile_selected_count is None:
            if any(
                value is not None
                for value in (
                    self.top_quintile_hit_count,
                    self.top_quintile_hit_rate,
                    self.top_quintile_hit_ci_low,
                    self.top_quintile_hit_ci_high,
                    self.future_top_quintile_base_rate,
                    self.top_quintile_lift,
                    self.top_quintile_outcome_mean,
                    self.top_quintile_outcome_median,
                )
            ):
                raise AggregationValidationError("top-quintile statistics require valid cohorts")
        elif self.top_quintile_hit_count is None:
            if any(
                value is not None
                for value in (
                    self.top_quintile_hit_rate,
                    self.top_quintile_hit_ci_low,
                    self.top_quintile_hit_ci_high,
                )
            ):
                raise AggregationValidationError("top-quintile hit rate requires a hit count")
        else:
            hit_count, hit_rate = _validate_count_rate(
                self.top_quintile_hit_count,
                self.top_quintile_hit_rate,
                denominator=top_quintile_selected_count,
                count_name="top_quintile_hit_count",
                rate_name="top_quintile_hit_rate",
            )
            object.__setattr__(self, "top_quintile_hit_count", hit_count)
            object.__setattr__(self, "top_quintile_hit_rate", hit_rate)
        _validate_interval(
            self.top_quintile_hit_ci_low,
            self.top_quintile_hit_ci_high,
            field_name="top_quintile_hit_ci",
        )
        _optional_ratio(
            self.future_top_quintile_base_rate, field_name="future_top_quintile_base_rate"
        )
        _optional_number(self.top_quintile_lift, field_name="top_quintile_lift")
        for field_name in (
            "top_quintile_outcome_mean",
            "top_quintile_outcome_median",
            "all_eligible_outcome_mean",
            "all_eligible_outcome_median",
        ):
            _optional_number(getattr(self, field_name), field_name=field_name)
        if self.outcome_name in {"future_downloads_share", "future_revenue_usd_share"}:
            positive_fields = (
                self.top_quintile_positive_change_count,
                self.top_quintile_positive_change_rate,
                self.top_quintile_positive_change_ci_low,
                self.top_quintile_positive_change_ci_high,
                self.all_positive_change_count,
                self.all_positive_change_rate,
                self.all_positive_change_ci_low,
                self.all_positive_change_ci_high,
            )
            if any(value is not None for value in positive_fields):
                raise AggregationValidationError(
                    "future-level outcomes do not have positive-change fields"
                )
        else:
            if top_quintile_selected_count is None:
                if any(
                    value is not None
                    for value in (
                        self.top_quintile_positive_change_count,
                        self.top_quintile_positive_change_rate,
                        self.top_quintile_positive_change_ci_low,
                        self.top_quintile_positive_change_ci_high,
                    )
                ):
                    raise AggregationValidationError(
                        "top-quintile positive-change statistics require valid cohorts"
                    )
            else:
                _validate_count_rate(
                    self.top_quintile_positive_change_count,
                    self.top_quintile_positive_change_rate,
                    denominator=top_quintile_selected_count,
                    count_name="top_quintile_positive_change_count",
                    rate_name="top_quintile_positive_change_rate",
                )
            _validate_interval(
                self.top_quintile_positive_change_ci_low,
                self.top_quintile_positive_change_ci_high,
                field_name="top_quintile_positive_change_ci",
            )
            _validate_count_rate(
                self.all_positive_change_count,
                self.all_positive_change_rate,
                denominator=self.eligible_row_count,
                count_name="all_positive_change_count",
                rate_name="all_positive_change_rate",
            )
            _validate_interval(
                self.all_positive_change_ci_low,
                self.all_positive_change_ci_high,
                field_name="all_positive_change_ci",
            )
        if not isinstance(self.low_sample_warning, bool):
            raise AggregationValidationError("low_sample_warning must be a boolean")
        _require_timestamp(self.calculated_at, field_name="calculated_at")


@dataclass(frozen=True, slots=True)
class ThemeBacktestSegmentMetric:
    """One aggregate categorical-segment/primary-outcome evaluation row."""

    scope_name: str
    cadence: str
    backtest_start: date
    backtest_end: date
    outcome_horizon_months: int
    segment_name: str
    segment_value: str
    outcome_name: str
    backtest_policy_version: str
    candidate_row_count: int
    eligible_row_count: int
    coverage_ratio: float
    decision_month_count: int
    segment_row_share: float
    outcome_mean: float | None
    outcome_median: float | None
    outcome_p25: float | None
    outcome_p75: float | None
    future_top_quintile_count: int | None
    future_top_quintile_rate: float | None
    future_top_quintile_ci_low: float | None
    future_top_quintile_ci_high: float | None
    future_top_quintile_base_rate: float | None
    future_top_quintile_lift: float | None
    positive_change_count: int | None
    positive_change_rate: float | None
    positive_change_ci_low: float | None
    positive_change_ci_high: float | None
    low_sample_warning: bool
    calculated_at: datetime

    @property
    def identity(self) -> tuple[object, ...]:
        return (
            self.scope_name,
            self.cadence,
            self.backtest_start,
            self.backtest_end,
            self.outcome_horizon_months,
            self.segment_name,
            self.segment_value,
            self.outcome_name,
            self.backtest_policy_version,
        )

    def __post_init__(self) -> None:
        _validate_aggregate_identity(
            self.scope_name,
            self.cadence,
            self.backtest_start,
            self.backtest_end,
            self.outcome_horizon_months,
            self.outcome_name,
            self.backtest_policy_version,
        )
        if self.segment_name not in SEGMENT_NAMES:
            raise AggregationValidationError("segment_name is not approved")
        if self.segment_value not in APPROVED_SEGMENT_VALUES[self.segment_name]:
            raise AggregationValidationError("segment_value is not approved")
        for field_name, value in (
            ("candidate_row_count", self.candidate_row_count),
            ("eligible_row_count", self.eligible_row_count),
            ("decision_month_count", self.decision_month_count),
        ):
            _require_count(value, field_name=field_name)
        if self.eligible_row_count > self.candidate_row_count:
            raise AggregationValidationError("eligible_row_count exceeds candidate_row_count")
        if self.decision_month_count > self.eligible_row_count:
            raise AggregationValidationError("decision_month_count exceeds eligible_row_count")
        _optional_ratio(self.coverage_ratio, field_name="coverage_ratio")
        expected_coverage = (
            0.0
            if self.candidate_row_count == 0
            else self.eligible_row_count / self.candidate_row_count
        )
        if not isclose(self.coverage_ratio, expected_coverage, rel_tol=1e-9, abs_tol=1e-12):
            raise AggregationValidationError("coverage_ratio does not reconcile")
        _optional_ratio(self.segment_row_share, field_name="segment_row_share")
        if self.candidate_row_count == 0 and self.segment_row_share != 0:
            raise AggregationValidationError("segment_row_share must be zero without candidates")
        if self.candidate_row_count > 0 and self.segment_row_share <= 0:
            raise AggregationValidationError("segment_row_share must be positive with candidates")
        for field_name in ("outcome_mean", "outcome_median", "outcome_p25", "outcome_p75"):
            _optional_number(getattr(self, field_name), field_name=field_name)
        _validate_count_rate(
            self.future_top_quintile_count,
            self.future_top_quintile_rate,
            denominator=self.eligible_row_count,
            count_name="future_top_quintile_count",
            rate_name="future_top_quintile_rate",
        )
        _validate_interval(
            self.future_top_quintile_ci_low,
            self.future_top_quintile_ci_high,
            field_name="future_top_quintile_ci",
        )
        _optional_ratio(
            self.future_top_quintile_base_rate, field_name="future_top_quintile_base_rate"
        )
        _optional_number(self.future_top_quintile_lift, field_name="future_top_quintile_lift")
        if self.outcome_name in {"future_downloads_share", "future_revenue_usd_share"}:
            if any(
                value is not None
                for value in (
                    self.positive_change_count,
                    self.positive_change_rate,
                    self.positive_change_ci_low,
                    self.positive_change_ci_high,
                )
            ):
                raise AggregationValidationError(
                    "future-level outcomes do not have positive-change fields"
                )
        else:
            _validate_count_rate(
                self.positive_change_count,
                self.positive_change_rate,
                denominator=self.eligible_row_count,
                count_name="positive_change_count",
                rate_name="positive_change_rate",
            )
            _validate_interval(
                self.positive_change_ci_low,
                self.positive_change_ci_high,
                field_name="positive_change_ci",
            )
        if not isinstance(self.low_sample_warning, bool):
            raise AggregationValidationError("low_sample_warning must be a boolean")
        _require_timestamp(self.calculated_at, field_name="calculated_at")


def _validate_aggregate_identity(
    scope_name: str,
    cadence: str,
    backtest_start: date,
    backtest_end: date,
    outcome_horizon_months: int,
    outcome_name: str,
    policy_version: str,
) -> None:
    _require_text(scope_name, field_name="scope_name")
    if cadence != "monthly":
        raise AggregationValidationError("cadence must equal monthly")
    _require_natural_month(
        backtest_start,
        natural_month_end(backtest_start),
        field_name="backtest_start_month",
    )
    _require_natural_month(
        backtest_end,
        natural_month_end(backtest_end),
        field_name="backtest_end_month",
    )
    if backtest_start > backtest_end:
        raise AggregationValidationError("backtest_start must not exceed backtest_end")
    if outcome_horizon_months not in BACKTEST_OUTCOME_HORIZONS:
        raise AggregationValidationError("outcome_horizon_months is not approved")
    if outcome_name not in PRIMARY_OUTCOME_NAMES:
        raise AggregationValidationError("outcome_name is not approved")
    if policy_version != BACKTEST_POLICY_VERSION:
        raise AggregationValidationError("backtest_policy_version is not approved")


def _validate_interval(low: float | None, high: float | None, *, field_name: str) -> None:
    normalized_low = _optional_ratio(low, field_name=f"{field_name}_low")
    normalized_high = _optional_ratio(high, field_name=f"{field_name}_high")
    if (normalized_low is None) != (normalized_high is None):
        raise AggregationValidationError(f"{field_name} bounds must be both present or NULL")
    if (
        normalized_low is not None
        and normalized_high is not None
        and normalized_low > normalized_high
    ):
        raise AggregationValidationError(f"{field_name} lower bound exceeds upper bound")


@dataclass(frozen=True, slots=True)
class ThemeLaunchWindowBacktestResult:
    """Complete pure BACKTEST-001 output payload."""

    outcomes: tuple[ThemeLaunchWindowOutcome, ...]
    feature_metrics: tuple[ThemeBacktestFeatureMetric, ...]
    segment_metrics: tuple[ThemeBacktestSegmentMetric, ...]


FEATURE_DEFINITIONS: tuple[BacktestFeatureDefinition, ...] = (
    BacktestFeatureDefinition("decision_product_share", "market_size_baseline", "higher_better"),
    BacktestFeatureDefinition("decision_downloads_share", "market_size_baseline", "higher_better"),
    BacktestFeatureDefinition(
        "decision_revenue_usd_share", "market_size_baseline", "higher_better"
    ),
    BacktestFeatureDefinition("legacy_6m_momentum_score", "legacy_baseline", "higher_better"),
    BacktestFeatureDefinition("median_normalized_slope_6m", "model_trend", "higher_better"),
    BacktestFeatureDefinition("median_normalized_slope_12m", "model_trend", "higher_better"),
    BacktestFeatureDefinition("median_normalized_slope_36m", "model_trend", "higher_better"),
    BacktestFeatureDefinition("stability_cv_median_6m", "model_stability", "lower_better"),
    BacktestFeatureDefinition("stability_cv_median_12m", "model_stability", "lower_better"),
    BacktestFeatureDefinition("stability_cv_median_36m", "model_stability", "lower_better"),
    BacktestFeatureDefinition("downloads_product_hhi", "competition", "lower_better"),
    BacktestFeatureDefinition("revenue_usd_product_hhi", "competition", "lower_better"),
    BacktestFeatureDefinition("top_500_turnover_rate", "competition", "higher_better"),
    BacktestFeatureDefinition(
        "downloads_market_new_entry_share_of_current", "new_entry", "higher_better"
    ),
    BacktestFeatureDefinition(
        "revenue_usd_market_new_entry_share_of_current", "new_entry", "higher_better"
    ),
    BacktestFeatureDefinition(
        "downloads_top_10_positive_contribution_share", "growth_breadth", "lower_better"
    ),
    BacktestFeatureDefinition(
        "revenue_usd_top_10_positive_contribution_share", "growth_breadth", "lower_better"
    ),
    BacktestFeatureDefinition("downloads_expected_seasonal_index", "seasonality", "higher_better"),
    BacktestFeatureDefinition(
        "revenue_usd_expected_seasonal_index", "seasonality", "higher_better"
    ),
)
BACKTEST_FEATURE_DEFINITIONS = FEATURE_DEFINITIONS
FEATURE_DEFINITION_BY_NAME = {
    definition.feature_name: definition for definition in FEATURE_DEFINITIONS
}

SEGMENT_NAMES: tuple[str, ...] = (
    "legacy_actionability",
    "direction_6m",
    "direction_12m",
    "direction_36m",
    "stability_band_6m",
    "stability_band_12m",
    "stability_band_36m",
    "lifecycle_stage",
)
BACKTEST_SEGMENT_NAMES = SEGMENT_NAMES
APPROVED_SEGMENT_VALUES: dict[str, tuple[str, ...]] = {
    "legacy_actionability": ("actionable", "non_actionable"),
    "direction_6m": DIRECTION_VALUES,
    "direction_12m": DIRECTION_VALUES,
    "direction_36m": DIRECTION_VALUES,
    "stability_band_6m": STABILITY_BANDS,
    "stability_band_12m": STABILITY_BANDS,
    "stability_band_36m": STABILITY_BANDS,
    "lifecycle_stage": LIFECYCLE_STAGES,
}


__all__ = [
    "APPROVED_SEGMENT_VALUES",
    "BACKTEST_FEATURE_DEFINITIONS",
    "BACKTEST_LOW_SAMPLE_COHORT_COUNT",
    "BACKTEST_LOW_SAMPLE_ROW_COUNT",
    "BACKTEST_MIN_COHORT_SIZE",
    "BACKTEST_OUTCOME_HORIZONS",
    "BACKTEST_POLICY_VERSION",
    "BACKTEST_PRIMARY_OUTCOMES",
    "BACKTEST_SEGMENT_NAMES",
    "BACKTEST_TOP_FRACTION",
    "BACKTEST_WILSON_Z",
    "BacktestFeatureDefinition",
    "FEATURE_DEFINITIONS",
    "FEATURE_DEFINITION_BY_NAME",
    "LIFECYCLE_STAGES",
    "PRIMARY_OUTCOME_NAMES",
    "SEGMENT_NAMES",
    "ThemeBacktestFeatureMetric",
    "ThemeBacktestSegmentMetric",
    "ThemeLaunchWindowBacktestResult",
    "ThemeLaunchWindowOutcome",
    "month_shift",
    "natural_month_end",
]
