"""Typed rows produced by the explainable monthly theme trend score."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite

from .errors import AggregationValidationError


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AggregationValidationError(f"{field_name} must be a non-empty string")
    return value


def _require_date(value: object, *, field_name: str) -> date:
    if type(value) is not date:
        raise AggregationValidationError(f"{field_name} must be a date")
    return value


def _require_count(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AggregationValidationError(
            f"{field_name} must be a non-negative integer"
        )
    return value


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


def _validate_share(value: object, *, field_name: str) -> float | None:
    numeric_value = _optional_number(value, field_name=field_name)
    if numeric_value is not None and not 0 <= numeric_value <= 1:
        raise AggregationValidationError(f"{field_name} must be between 0 and 1")
    return numeric_value


def _validate_score(value: object, *, field_name: str) -> float | None:
    numeric_value = _optional_number(value, field_name=field_name)
    if numeric_value is not None and not 0 <= numeric_value <= 100:
        raise AggregationValidationError(f"{field_name} must be between 0 and 100")
    return numeric_value


def _require_timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AggregationValidationError(f"{field_name} must be timezone-aware")
    return value


def _month_shift(month_start: date, offset: int) -> date:
    month_index = month_start.year * 12 + month_start.month - 1 + offset
    year, month_zero_based = divmod(month_index, 12)
    return date(year, month_zero_based + 1, 1)


def _natural_month_end(month_start: date) -> date:
    return date(
        month_start.year,
        month_start.month,
        calendar.monthrange(month_start.year, month_start.month)[1],
    )


@dataclass(frozen=True, slots=True)
class ThemeTrendScore:
    """One six-month explainable score for a raw Game Theme label."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    window_start: date
    window_month_count: int
    active_months_6m: int
    latest_product_count: int
    is_actionable: bool
    exclusion_reason: str | None
    latest_product_share: float
    latest_units_absolute_share: float | None
    latest_revenue_absolute_share: float | None
    latest_new_entry_share: float | None
    latest_median_rank: float
    latest_publisher_count: int
    latest_top_publisher_product_share: float | None
    product_share_gain_3m: float
    units_absolute_share_gain_3m: float | None
    revenue_absolute_share_gain_3m: float | None
    product_share_acceleration: float
    units_absolute_share_acceleration: float | None
    revenue_absolute_share_acceleration: float | None
    recent3_new_entry_share: float | None
    median_rank_improvement: float | None
    publisher_count_gain_3m: float | None
    units_absolute_overindex: float | None
    revenue_absolute_overindex: float | None
    recent3_units_coverage_ratio: float
    recent3_revenue_coverage_ratio: float
    latest_publisher_coverage_ratio: float
    growth_score: float | None
    acceleration_score: float | None
    new_product_score: float | None
    concentration_penalty: float | None
    base_trend_score: float | None
    confidence_score: float
    trend_score: float | None
    trend_rank: int | None
    calculated_at: datetime

    @property
    def period_key(self) -> tuple[str, str, date, date]:
        """Return the score's target-month identity."""

        return (self.scope_name, self.cadence, self.period_start, self.period_end)

    def __post_init__(self) -> None:
        _require_text(self.scope_name, field_name="scope_name")
        if self.cadence != "monthly":
            raise AggregationValidationError("cadence must equal monthly")

        period_start = _require_date(self.period_start, field_name="period_start")
        period_end = _require_date(self.period_end, field_name="period_end")
        window_start = _require_date(self.window_start, field_name="window_start")
        if period_end != _natural_month_end(period_start) or period_start.day != 1:
            raise AggregationValidationError("trend target period must be a natural month")
        if window_start != _month_shift(period_start, -5):
            raise AggregationValidationError("window_start must begin five months before target")
        if self.window_month_count != 6:
            raise AggregationValidationError("window_month_count must equal 6")

        if not isinstance(self.game_theme, str):
            raise AggregationValidationError("game_theme must be a string")
        active_months = _require_count(self.active_months_6m, field_name="active_months_6m")
        latest_product_count = _require_count(
            self.latest_product_count,
            field_name="latest_product_count",
        )
        _require_count(
            self.latest_publisher_count,
            field_name="latest_publisher_count",
        )
        if active_months > 6:
            raise AggregationValidationError("active_months_6m must not exceed 6")

        if not isinstance(self.is_actionable, bool):
            raise AggregationValidationError("is_actionable must be a boolean")
        if self.exclusion_reason is not None:
            _require_text(self.exclusion_reason, field_name="exclusion_reason")

        latest_product_share = _validate_share(
            self.latest_product_share,
            field_name="latest_product_share",
        )
        if latest_product_share is None:
            raise AggregationValidationError("latest_product_share must be present")
        latest_units_share = _validate_share(
            self.latest_units_absolute_share,
            field_name="latest_units_absolute_share",
        )
        latest_revenue_share = _validate_share(
            self.latest_revenue_absolute_share,
            field_name="latest_revenue_absolute_share",
        )
        latest_new_entry_share = _validate_share(
            self.latest_new_entry_share,
            field_name="latest_new_entry_share",
        )
        latest_median_rank = _require_number(
            self.latest_median_rank,
            field_name="latest_median_rank",
        )
        latest_top_publisher_share = _validate_share(
            self.latest_top_publisher_product_share,
            field_name="latest_top_publisher_product_share",
        )

        product_gain = _require_number(
            self.product_share_gain_3m,
            field_name="product_share_gain_3m",
        )
        units_gain = _optional_number(
            self.units_absolute_share_gain_3m,
            field_name="units_absolute_share_gain_3m",
        )
        revenue_gain = _optional_number(
            self.revenue_absolute_share_gain_3m,
            field_name="revenue_absolute_share_gain_3m",
        )
        product_acceleration = _require_number(
            self.product_share_acceleration,
            field_name="product_share_acceleration",
        )
        units_acceleration = _optional_number(
            self.units_absolute_share_acceleration,
            field_name="units_absolute_share_acceleration",
        )
        revenue_acceleration = _optional_number(
            self.revenue_absolute_share_acceleration,
            field_name="revenue_absolute_share_acceleration",
        )
        recent3_new_entry_share = _validate_share(
            self.recent3_new_entry_share,
            field_name="recent3_new_entry_share",
        )
        median_rank_improvement = _optional_number(
            self.median_rank_improvement,
            field_name="median_rank_improvement",
        )
        publisher_count_gain = _optional_number(
            self.publisher_count_gain_3m,
            field_name="publisher_count_gain_3m",
        )
        units_overindex = _optional_number(
            self.units_absolute_overindex,
            field_name="units_absolute_overindex",
        )
        revenue_overindex = _optional_number(
            self.revenue_absolute_overindex,
            field_name="revenue_absolute_overindex",
        )

        recent3_units_coverage = _validate_share(
            self.recent3_units_coverage_ratio,
            field_name="recent3_units_coverage_ratio",
        )
        recent3_revenue_coverage = _validate_share(
            self.recent3_revenue_coverage_ratio,
            field_name="recent3_revenue_coverage_ratio",
        )
        latest_publisher_coverage = _validate_share(
            self.latest_publisher_coverage_ratio,
            field_name="latest_publisher_coverage_ratio",
        )
        if (
            recent3_units_coverage is None
            or recent3_revenue_coverage is None
            or latest_publisher_coverage is None
        ):
            raise AggregationValidationError("coverage ratios must be present")

        growth_score = _validate_score(self.growth_score, field_name="growth_score")
        acceleration_score = _validate_score(
            self.acceleration_score,
            field_name="acceleration_score",
        )
        new_product_score = _validate_score(
            self.new_product_score,
            field_name="new_product_score",
        )
        concentration_penalty = _validate_score(
            self.concentration_penalty,
            field_name="concentration_penalty",
        )
        base_trend_score = _validate_score(
            self.base_trend_score,
            field_name="base_trend_score",
        )
        confidence_score = _validate_score(
            self.confidence_score,
            field_name="confidence_score",
        )
        if confidence_score is None:
            raise AggregationValidationError("confidence_score must be present")
        trend_score = _validate_score(self.trend_score, field_name="trend_score")
        if self.trend_rank is not None:
            if (
                isinstance(self.trend_rank, bool)
                or not isinstance(self.trend_rank, int)
                or self.trend_rank < 1
            ):
                raise AggregationValidationError("trend_rank must be a positive integer")

        component_values = (
            growth_score,
            acceleration_score,
            new_product_score,
            concentration_penalty,
            base_trend_score,
            trend_score,
        )
        if self.is_actionable:
            if self.game_theme in {"", "Unknown", "N/A"}:
                raise AggregationValidationError(
                    "actionable rows cannot use excluded source labels"
                )
            if latest_product_count < 5:
                raise AggregationValidationError(
                    "actionable rows require at least five latest products"
                )
            if active_months < 3:
                raise AggregationValidationError(
                    "actionable rows require at least three active months"
                )
            if recent3_new_entry_share is None:
                raise AggregationValidationError(
                    "actionable rows require recent3_new_entry_share"
                )
            if self.exclusion_reason is not None or any(
                value is None for value in component_values
            ):
                raise AggregationValidationError(
                    "actionable rows require all component and final scores"
                )
            if self.trend_rank is None:
                raise AggregationValidationError("actionable rows require trend_rank")
        else:
            if self.exclusion_reason is None:
                raise AggregationValidationError(
                    "non-actionable rows require exclusion_reason"
                )
            if any(value is not None for value in component_values) or self.trend_rank is not None:
                raise AggregationValidationError(
                    "non-actionable rows require NULL component scores and rank"
                )

        _require_timestamp(self.calculated_at, field_name="calculated_at")
        object.__setattr__(self, "latest_product_share", latest_product_share)
        object.__setattr__(self, "latest_units_absolute_share", latest_units_share)
        object.__setattr__(self, "latest_revenue_absolute_share", latest_revenue_share)
        object.__setattr__(self, "latest_new_entry_share", latest_new_entry_share)
        object.__setattr__(self, "latest_median_rank", latest_median_rank)
        object.__setattr__(self, "latest_top_publisher_product_share", latest_top_publisher_share)
        object.__setattr__(self, "product_share_gain_3m", product_gain)
        object.__setattr__(self, "units_absolute_share_gain_3m", units_gain)
        object.__setattr__(self, "revenue_absolute_share_gain_3m", revenue_gain)
        object.__setattr__(self, "product_share_acceleration", product_acceleration)
        object.__setattr__(self, "units_absolute_share_acceleration", units_acceleration)
        object.__setattr__(self, "revenue_absolute_share_acceleration", revenue_acceleration)
        object.__setattr__(self, "recent3_new_entry_share", recent3_new_entry_share)
        object.__setattr__(self, "median_rank_improvement", median_rank_improvement)
        object.__setattr__(self, "publisher_count_gain_3m", publisher_count_gain)
        object.__setattr__(self, "units_absolute_overindex", units_overindex)
        object.__setattr__(self, "revenue_absolute_overindex", revenue_overindex)
        object.__setattr__(self, "recent3_units_coverage_ratio", recent3_units_coverage)
        object.__setattr__(self, "recent3_revenue_coverage_ratio", recent3_revenue_coverage)
        object.__setattr__(self, "latest_publisher_coverage_ratio", latest_publisher_coverage)
        object.__setattr__(self, "growth_score", growth_score)
        object.__setattr__(self, "acceleration_score", acceleration_score)
        object.__setattr__(self, "new_product_score", new_product_score)
        object.__setattr__(self, "concentration_penalty", concentration_penalty)
        object.__setattr__(self, "base_trend_score", base_trend_score)
        object.__setattr__(self, "confidence_score", confidence_score)
        object.__setattr__(self, "trend_score", trend_score)
