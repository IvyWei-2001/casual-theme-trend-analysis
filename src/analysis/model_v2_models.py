"""Typed rows produced by the MODEL-002 evidence model.

The classes in this module are internal analytical models.  They deliberately
contain no Sensor Tower, Feishu, configuration, or storage dependencies so the
calculation layer can be exercised with synthetic rows.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite

from .errors import AggregationValidationError

HORIZON_MONTH_COUNTS: tuple[int, ...] = (6, 12, 36)
MODEL_POLICY_VERSION = "MODEL002_V1"
HORIZON_METRIC_NAMES: tuple[str, ...] = (
    "product_count",
    "product_share",
    "downloads_sum",
    "downloads_share",
    "revenue_usd_sum",
    "revenue_usd_share",
)
SHARE_METRIC_NAMES: tuple[str, ...] = (
    "product_share",
    "downloads_share",
    "revenue_usd_share",
)
DIRECTION_VALUES: tuple[str, ...] = (
    "up",
    "down",
    "flat",
    "mixed",
    "insufficient_history",
)
STABILITY_BANDS: tuple[str, ...] = (
    "stable",
    "variable",
    "volatile",
    "insufficient_history",
)
LIFECYCLE_STAGES: tuple[str, ...] = (
    "insufficient_history",
    "emerging",
    "accelerating",
    "growing",
    "mature",
    "recovering",
    "declining",
    "mixed",
)


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


def _require_timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AggregationValidationError(f"{field_name} must be timezone-aware")
    return value


def _require_count(value: object, *, field_name: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AggregationValidationError(f"{field_name} must be a non-negative integer")
    if maximum is not None and value > maximum:
        raise AggregationValidationError(f"{field_name} must not exceed {maximum}")
    return value


def _optional_count(value: object, *, field_name: str, maximum: int | None = None) -> int | None:
    if value is None:
        return None
    return _require_count(value, field_name=field_name, maximum=maximum)


def _require_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AggregationValidationError(f"{field_name} must be a number")
    numeric_value = float(value)
    if not isfinite(numeric_value):
        raise AggregationValidationError(f"{field_name} must be finite")
    return numeric_value


def _optional_number(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    return _require_number(value, field_name=field_name)


def _require_natural_month(period_start: object, period_end: object, *, field_name: str) -> None:
    start = _require_date(period_start, field_name=f"{field_name}_start")
    end = _require_date(period_end, field_name=f"{field_name}_end")
    if start.day != 1 or end != date(
        start.year,
        start.month,
        calendar.monthrange(start.year, start.month)[1],
    ):
        raise AggregationValidationError(f"{field_name} must be a natural calendar month")


def _month_shift(month_start: date, offset: int) -> date:
    month_index = month_start.year * 12 + month_start.month - 1 + offset
    year, month_zero_based = divmod(month_index, 12)
    return date(year, month_zero_based + 1, 1)


def _validate_finite_optional_fields(
    values: tuple[tuple[str, object], ...],
) -> dict[str, float | None]:
    return {
        field_name: _optional_number(value, field_name=field_name)
        for field_name, value in values
    }


@dataclass(frozen=True, slots=True)
class ThemeHorizonMetric:
    """One descriptive and trend-evidence row for one metric and horizon."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    horizon_month_count: int
    metric_name: str
    window_start: date
    expected_month_count: int
    metric_coverage_count: int
    active_month_count: int
    is_complete: bool
    first_value: float | None
    latest_value: float | None
    mean_value: float | None
    median_value: float | None
    minimum_value: float | None
    maximum_value: float | None
    absolute_change: float | None
    relative_change: float | None
    linear_slope: float | None
    normalized_slope: float | None
    r_squared: float | None
    latest_to_mean_ratio: float | None
    transition_count: int
    transition_coverage_count: int
    positive_change_count: int
    negative_change_count: int
    unchanged_change_count: int
    positive_change_ratio: float | None
    standard_deviation: float | None
    coefficient_of_variation: float | None
    maximum_drawdown: float | None
    months_since_peak: int | None
    calculated_at: datetime

    @property
    def period_key(self) -> tuple[str, str, date, date, str, int, str]:
        """Return the complete long-form identity."""

        return (
            self.scope_name,
            self.cadence,
            self.period_start,
            self.period_end,
            self.game_theme,
            self.horizon_month_count,
            self.metric_name,
        )

    def __post_init__(self) -> None:
        _require_text(self.scope_name, field_name="scope_name")
        if self.cadence != "monthly":
            raise AggregationValidationError("cadence must equal monthly")
        _require_natural_month(self.period_start, self.period_end, field_name="period")
        _require_raw_label(self.game_theme, field_name="game_theme")
        if self.horizon_month_count not in HORIZON_MONTH_COUNTS:
            raise AggregationValidationError("horizon_month_count is not supported")
        if self.metric_name not in HORIZON_METRIC_NAMES:
            raise AggregationValidationError("metric_name is not supported")
        window_start = _require_date(self.window_start, field_name="window_start")
        if window_start != _month_shift(self.period_start, -(self.horizon_month_count - 1)):
            raise AggregationValidationError("window_start does not match the horizon")

        horizon = self.horizon_month_count
        expected = _require_count(
            self.expected_month_count,
            field_name="expected_month_count",
            maximum=horizon,
        )
        if expected != horizon:
            raise AggregationValidationError("expected_month_count must equal horizon")
        coverage = _require_count(
            self.metric_coverage_count,
            field_name="metric_coverage_count",
            maximum=horizon,
        )
        _require_count(self.active_month_count, field_name="active_month_count", maximum=horizon)
        if not isinstance(self.is_complete, bool):
            raise AggregationValidationError("is_complete must be a boolean")
        if self.is_complete != (coverage == horizon):
            raise AggregationValidationError("is_complete must match metric coverage")

        descriptive = _validate_finite_optional_fields(
            (
                ("first_value", self.first_value),
                ("latest_value", self.latest_value),
                ("mean_value", self.mean_value),
                ("median_value", self.median_value),
                ("minimum_value", self.minimum_value),
                ("maximum_value", self.maximum_value),
                ("standard_deviation", self.standard_deviation),
            )
        )
        if coverage == 0 and any(value is not None for value in descriptive.values()):
            raise AggregationValidationError("descriptive values must be NULL with zero coverage")
        if coverage > 0 and any(
            descriptive[field_name] is None
            for field_name in (
                "mean_value",
                "median_value",
                "minimum_value",
                "maximum_value",
                "standard_deviation",
            )
        ):
            raise AggregationValidationError("covered descriptive values are required")

        complete_only = _validate_finite_optional_fields(
            (
                ("absolute_change", self.absolute_change),
                ("relative_change", self.relative_change),
                ("linear_slope", self.linear_slope),
                ("normalized_slope", self.normalized_slope),
                ("r_squared", self.r_squared),
                ("latest_to_mean_ratio", self.latest_to_mean_ratio),
                ("coefficient_of_variation", self.coefficient_of_variation),
                ("maximum_drawdown", self.maximum_drawdown),
            )
        )
        if not self.is_complete and any(value is not None for value in complete_only.values()):
            raise AggregationValidationError("complete-series evidence requires complete coverage")
        if self.is_complete:
            if self.first_value is None or self.latest_value is None:
                raise AggregationValidationError("complete-series endpoints are required")
            if self.mean_value is None or self.standard_deviation is None:
                raise AggregationValidationError("complete-series descriptive values are required")

        transition_count = _require_count(
            self.transition_count,
            field_name="transition_count",
            maximum=horizon - 1,
        )
        if transition_count != horizon - 1:
            raise AggregationValidationError("transition_count must equal horizon minus one")
        transition_coverage = _require_count(
            self.transition_coverage_count,
            field_name="transition_coverage_count",
            maximum=transition_count,
        )
        positive = _require_count(
            self.positive_change_count,
            field_name="positive_change_count",
            maximum=transition_coverage,
        )
        negative = _require_count(
            self.negative_change_count,
            field_name="negative_change_count",
            maximum=transition_coverage,
        )
        unchanged = _require_count(
            self.unchanged_change_count,
            field_name="unchanged_change_count",
            maximum=transition_coverage,
        )
        if positive + negative + unchanged != transition_coverage:
            raise AggregationValidationError("transition category counts do not reconcile")
        positive_ratio = _optional_number(
            self.positive_change_ratio,
            field_name="positive_change_ratio",
        )
        if positive_ratio is not None and not 0 <= positive_ratio <= 1:
            raise AggregationValidationError("positive_change_ratio must be between 0 and 1")
        if transition_coverage == 0 and positive_ratio is not None:
            raise AggregationValidationError("positive_change_ratio must be NULL without coverage")
        if transition_coverage > 0 and positive_ratio is None:
            raise AggregationValidationError("positive_change_ratio is required with coverage")

        coefficient = complete_only["coefficient_of_variation"]
        if coefficient is not None and coefficient < 0:
            raise AggregationValidationError("coefficient_of_variation must be non-negative")
        drawdown = complete_only["maximum_drawdown"]
        if drawdown is not None and not 0 <= drawdown <= 1:
            raise AggregationValidationError("maximum_drawdown must be between 0 and 1")
        months_since_peak = _optional_count(
            self.months_since_peak,
            field_name="months_since_peak",
            maximum=horizon - 1,
        )
        if self.is_complete and months_since_peak is None:
            raise AggregationValidationError("months_since_peak is required for complete series")
        if self.is_complete and self.maximum_drawdown is None:
            raise AggregationValidationError("maximum_drawdown is required for complete series")

        for field_name, value in descriptive.items():
            object.__setattr__(self, field_name, value)
        for field_name, value in complete_only.items():
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "positive_change_ratio", positive_ratio)
        object.__setattr__(self, "months_since_peak", months_since_peak)


@dataclass(frozen=True, slots=True)
class ThemeModelSummary:
    """One explainable model-evidence index for one theme and target month."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    model_policy_version: str
    history_start: date
    history_month_count: int
    first_active_month: date | None
    first_active_left_censored: bool
    months_since_first_active: int | None
    active_months_to_date: int
    has_6m_history: bool
    has_12m_history: bool
    has_36m_history: bool
    active_months_6m: int | None
    active_months_12m: int | None
    active_months_36m: int | None
    direction_6m: str
    direction_12m: str
    direction_36m: str
    direction_evidence_count_6m: int
    direction_evidence_count_12m: int
    direction_evidence_count_36m: int
    median_normalized_slope_6m: float | None
    median_normalized_slope_12m: float | None
    median_normalized_slope_36m: float | None
    median_r_squared_6m: float | None
    median_r_squared_12m: float | None
    median_r_squared_36m: float | None
    stability_cv_median_6m: float | None
    stability_cv_median_12m: float | None
    stability_cv_median_36m: float | None
    stability_band_6m: str
    stability_band_12m: str
    stability_band_36m: str
    lifecycle_stage: str
    seasonality_history_month_count: int | None
    seasonality_complete_year_count: int | None
    downloads_peak_calendar_month: int | None
    downloads_trough_calendar_month: int | None
    downloads_seasonality_amplitude: float | None
    revenue_usd_peak_calendar_month: int | None
    revenue_usd_trough_calendar_month: int | None
    revenue_usd_seasonality_amplitude: float | None
    calculated_at: datetime

    @property
    def period_key(self) -> tuple[str, str, date, date, str]:
        """Return the summary identity."""

        return (
            self.scope_name,
            self.cadence,
            self.period_start,
            self.period_end,
            self.game_theme,
        )

    def __post_init__(self) -> None:
        _require_text(self.scope_name, field_name="scope_name")
        if self.cadence != "monthly":
            raise AggregationValidationError("cadence must equal monthly")
        _require_natural_month(self.period_start, self.period_end, field_name="period")
        _require_raw_label(self.game_theme, field_name="game_theme")
        if self.model_policy_version != MODEL_POLICY_VERSION:
            raise AggregationValidationError(
                f"model_policy_version must equal {MODEL_POLICY_VERSION}"
            )
        history_start = _require_date(self.history_start, field_name="history_start")
        if history_start.day != 1 or history_start > self.period_start:
            raise AggregationValidationError("history_start must begin no later than the target")
        history_count = _require_count(self.history_month_count, field_name="history_month_count")
        if history_count < 1:
            raise AggregationValidationError("history_month_count must be positive")
        if self.period_start != _month_shift(history_start, history_count - 1):
            raise AggregationValidationError(
                "history_month_count does not match the summary period"
            )
        _require_count(
            self.active_months_to_date,
            field_name="active_months_to_date",
            maximum=history_count,
        )

        first_active = self.first_active_month
        if first_active is not None:
            _require_date(first_active, field_name="first_active_month")
            if (
                first_active.day != 1
                or first_active < history_start
                or first_active > self.period_start
            ):
                raise AggregationValidationError(
                    "first_active_month is outside the available history"
                )
        if not isinstance(self.first_active_left_censored, bool):
            raise AggregationValidationError("first_active_left_censored must be a boolean")
        months_since_active = _optional_count(
            self.months_since_first_active,
            field_name="months_since_first_active",
        )
        if first_active is None:
            if self.first_active_left_censored or months_since_active is not None:
                raise AggregationValidationError(
                    "missing first active month has inconsistent evidence"
                )
        elif self.first_active_left_censored != (first_active == history_start):
            raise AggregationValidationError("left-censoring does not match first active month")
        if first_active is not None and months_since_active != _month_distance(
            first_active, self.period_start
        ):
            raise AggregationValidationError(
                "months_since_first_active does not match the summary period"
            )

        flags = (self.has_6m_history, self.has_12m_history, self.has_36m_history)
        if any(not isinstance(value, bool) for value in flags):
            raise AggregationValidationError("horizon availability fields must be booleans")
        for horizon, active_months, has_history, field_name in zip(
            HORIZON_MONTH_COUNTS,
            (self.active_months_6m, self.active_months_12m, self.active_months_36m),
            flags,
            ("active_months_6m", "active_months_12m", "active_months_36m"),
            strict=True,
        ):
            normalized = _optional_count(active_months, field_name=field_name, maximum=horizon)
            if has_history and normalized is None:
                raise AggregationValidationError(f"{field_name} is required with horizon history")
            object.__setattr__(self, field_name, normalized)

        for field_name, value in (
            ("direction_6m", self.direction_6m),
            ("direction_12m", self.direction_12m),
            ("direction_36m", self.direction_36m),
        ):
            if value not in DIRECTION_VALUES:
                raise AggregationValidationError(f"{field_name} is not an approved direction")
        for field_name, value in (
            ("stability_band_6m", self.stability_band_6m),
            ("stability_band_12m", self.stability_band_12m),
            ("stability_band_36m", self.stability_band_36m),
        ):
            if value not in STABILITY_BANDS:
                raise AggregationValidationError(f"{field_name} is not an approved stability band")
        if self.lifecycle_stage not in LIFECYCLE_STAGES:
            raise AggregationValidationError("lifecycle_stage is not an approved value")

        for field_name, evidence_value in (
            ("direction_evidence_count_6m", self.direction_evidence_count_6m),
            ("direction_evidence_count_12m", self.direction_evidence_count_12m),
            ("direction_evidence_count_36m", self.direction_evidence_count_36m),
        ):
            _require_count(
                evidence_value,
                field_name=field_name,
                maximum=len(SHARE_METRIC_NAMES),
            )

        optional_numbers = _validate_finite_optional_fields(
            (
                ("median_normalized_slope_6m", self.median_normalized_slope_6m),
                ("median_normalized_slope_12m", self.median_normalized_slope_12m),
                ("median_normalized_slope_36m", self.median_normalized_slope_36m),
                ("median_r_squared_6m", self.median_r_squared_6m),
                ("median_r_squared_12m", self.median_r_squared_12m),
                ("median_r_squared_36m", self.median_r_squared_36m),
                ("stability_cv_median_6m", self.stability_cv_median_6m),
                ("stability_cv_median_12m", self.stability_cv_median_12m),
                ("stability_cv_median_36m", self.stability_cv_median_36m),
                ("downloads_seasonality_amplitude", self.downloads_seasonality_amplitude),
                ("revenue_usd_seasonality_amplitude", self.revenue_usd_seasonality_amplitude),
            )
        )
        for field_name in (
            "stability_cv_median_6m",
            "stability_cv_median_12m",
            "stability_cv_median_36m",
            "downloads_seasonality_amplitude",
            "revenue_usd_seasonality_amplitude",
        ):
            numeric_value = optional_numbers[field_name]
            if numeric_value is not None and numeric_value < 0:
                raise AggregationValidationError(f"{field_name} must be non-negative")
        for field_name in (
            "downloads_peak_calendar_month",
            "downloads_trough_calendar_month",
            "revenue_usd_peak_calendar_month",
            "revenue_usd_trough_calendar_month",
        ):
            month_value = _optional_count(
                getattr(self, field_name), field_name=field_name, maximum=12
            )
            if month_value is not None and month_value == 0:
                raise AggregationValidationError(f"{field_name} must be between 1 and 12")
            object.__setattr__(self, field_name, month_value)

        seasonality_count = _optional_count(
            self.seasonality_history_month_count,
            field_name="seasonality_history_month_count",
            maximum=36,
        )
        complete_year_count = _optional_count(
            self.seasonality_complete_year_count,
            field_name="seasonality_complete_year_count",
            maximum=3,
        )
        if seasonality_count is not None and seasonality_count not in (24, 36):
            raise AggregationValidationError("seasonality history must be 24 or 36 months")
        if seasonality_count is None and complete_year_count is not None:
            raise AggregationValidationError("seasonality year count requires seasonality history")
        if seasonality_count is not None and complete_year_count is None:
            raise AggregationValidationError("seasonality year count is required with history")

        for field_name, optional_value in optional_numbers.items():
            object.__setattr__(self, field_name, optional_value)
        object.__setattr__(self, "history_start", history_start)
        object.__setattr__(self, "months_since_first_active", months_since_active)
        object.__setattr__(self, "seasonality_history_month_count", seasonality_count)
        object.__setattr__(self, "seasonality_complete_year_count", complete_year_count)


@dataclass(frozen=True, slots=True)
class ThemeSeasonalityProfile:
    """One calendar-month row in a leakage-safe block-normalized profile."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    metric_name: str
    calendar_month: int
    history_start: date
    history_month_count: int
    complete_year_count: int
    observation_count: int
    seasonal_index: float
    index_deviation: float
    is_peak_month: bool
    is_trough_month: bool
    calculated_at: datetime

    @property
    def period_key(self) -> tuple[str, str, date, date, str, str, int]:
        """Return the complete profile identity."""

        return (
            self.scope_name,
            self.cadence,
            self.period_start,
            self.period_end,
            self.game_theme,
            self.metric_name,
            self.calendar_month,
        )

    def __post_init__(self) -> None:
        _require_text(self.scope_name, field_name="scope_name")
        if self.cadence != "monthly":
            raise AggregationValidationError("cadence must equal monthly")
        _require_natural_month(self.period_start, self.period_end, field_name="period")
        _require_raw_label(self.game_theme, field_name="game_theme")
        if self.metric_name not in HORIZON_METRIC_NAMES:
            raise AggregationValidationError("metric_name is not supported")
        calendar_month = _require_count(
            self.calendar_month,
            field_name="calendar_month",
            maximum=12,
        )
        if calendar_month < 1:
            raise AggregationValidationError("calendar_month must be between 1 and 12")
        history_start = _require_date(self.history_start, field_name="history_start")
        if history_start.day != 1:
            raise AggregationValidationError("history_start must be the first day of a month")
        history_month_count = _require_count(
            self.history_month_count,
            field_name="history_month_count",
            maximum=36,
        )
        if history_month_count not in (24, 36):
            raise AggregationValidationError("seasonality history must be 24 or 36 months")
        complete_year_count = _require_count(
            self.complete_year_count,
            field_name="complete_year_count",
            maximum=3,
        )
        if complete_year_count < 2 or complete_year_count > history_month_count // 12:
            raise AggregationValidationError("complete_year_count is outside the profile history")
        observation_count = _require_count(
            self.observation_count,
            field_name="observation_count",
        )
        if observation_count != complete_year_count:
            raise AggregationValidationError("one observation is required per valid year block")
        seasonal_index = _require_number(self.seasonal_index, field_name="seasonal_index")
        if seasonal_index < 0:
            raise AggregationValidationError("seasonal_index must be non-negative")
        index_deviation = _require_number(self.index_deviation, field_name="index_deviation")
        if index_deviation != seasonal_index - 1:
            raise AggregationValidationError("index_deviation must equal seasonal_index minus one")
        if not isinstance(self.is_peak_month, bool) or not isinstance(self.is_trough_month, bool):
            raise AggregationValidationError("seasonality peak and trough fields must be booleans")
        _require_timestamp(self.calculated_at, field_name="calculated_at")
        object.__setattr__(self, "history_start", history_start)
        object.__setattr__(self, "seasonal_index", seasonal_index)
        object.__setattr__(self, "index_deviation", index_deviation)


@dataclass(frozen=True, slots=True)
class ThemeModelResult:
    """Complete pure MODEL-002 result for one supplied history range."""

    horizon_metrics: tuple[ThemeHorizonMetric, ...]
    model_summaries: tuple[ThemeModelSummary, ...]
    seasonality_profiles: tuple[ThemeSeasonalityProfile, ...]


__all__ = [
    "DIRECTION_VALUES",
    "HORIZON_METRIC_NAMES",
    "HORIZON_MONTH_COUNTS",
    "LIFECYCLE_STAGES",
    "MODEL_POLICY_VERSION",
    "SHARE_METRIC_NAMES",
    "STABILITY_BANDS",
    "ThemeHorizonMetric",
    "ThemeModelResult",
    "ThemeModelSummary",
    "ThemeSeasonalityProfile",
]


def _month_distance(start: date, end: date) -> int:
    """Return the number of calendar-month boundaries between month starts."""

    return (end.year - start.year) * 12 + end.month - start.month
