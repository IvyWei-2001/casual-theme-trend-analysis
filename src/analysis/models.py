"""Typed derived rows produced by the monthly Game Theme aggregation."""

from __future__ import annotations

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


def _require_timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AggregationValidationError(f"{field_name} must be timezone-aware")
    return value


def _require_count(value: object, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AggregationValidationError(
            f"{field_name} must be an integer greater than or equal to {minimum}"
        )
    return value


def _optional_count(value: object, *, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_count(value, field_name=field_name)


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


def _validate_share(value: float | None, *, field_name: str) -> float | None:
    if value is None:
        return None
    numeric_value = _require_number(value, field_name=field_name)
    if not 0 <= numeric_value <= 1:
        raise AggregationValidationError(f"{field_name} must be between 0 and 1")
    return numeric_value


def _validate_coverage_sum(
    coverage_count: int,
    value: float | None,
    *,
    metric_name: str,
) -> None:
    if coverage_count == 0 and value is not None:
        raise AggregationValidationError(
            f"{metric_name}_sum must be NULL when coverage is zero"
        )
    if coverage_count > 0 and value is None:
        raise AggregationValidationError(
            f"{metric_name}_sum must be present when coverage is non-zero"
        )


@dataclass(frozen=True, slots=True)
class MonthlyMarketTotal:
    """One month-wide population and source-coverage aggregate."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    snapshot_count: int
    theme_present_count: int
    theme_missing_count: int
    metadata_coverage_count: int
    units_absolute_coverage_count: int
    units_absolute_sum: float | None
    revenue_absolute_coverage_count: int
    revenue_absolute_sum: float | None
    calculated_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.scope_name, field_name="scope_name")
        if self.cadence != "monthly":
            raise AggregationValidationError("cadence must equal monthly")
        start = _require_date(self.period_start, field_name="period_start")
        end = _require_date(self.period_end, field_name="period_end")
        if start > end:
            raise AggregationValidationError("period_start must be on or before period_end")

        snapshot_count = _require_count(self.snapshot_count, field_name="snapshot_count")
        theme_present_count = _require_count(
            self.theme_present_count,
            field_name="theme_present_count",
        )
        theme_missing_count = _require_count(
            self.theme_missing_count,
            field_name="theme_missing_count",
        )
        metadata_coverage_count = _require_count(
            self.metadata_coverage_count,
            field_name="metadata_coverage_count",
        )
        units_coverage_count = _require_count(
            self.units_absolute_coverage_count,
            field_name="units_absolute_coverage_count",
        )
        revenue_coverage_count = _require_count(
            self.revenue_absolute_coverage_count,
            field_name="revenue_absolute_coverage_count",
        )
        if theme_present_count + theme_missing_count != snapshot_count:
            raise AggregationValidationError(
                "theme_present_count plus theme_missing_count must equal snapshot_count"
            )
        for field_name, count in (
            ("metadata_coverage_count", metadata_coverage_count),
            ("units_absolute_coverage_count", units_coverage_count),
            ("revenue_absolute_coverage_count", revenue_coverage_count),
        ):
            if count > snapshot_count:
                raise AggregationValidationError(
                    f"{field_name} must not exceed snapshot_count"
                )

        units_sum = _optional_number(self.units_absolute_sum, field_name="units_absolute_sum")
        revenue_sum = _optional_number(
            self.revenue_absolute_sum,
            field_name="revenue_absolute_sum",
        )
        _validate_coverage_sum(
            units_coverage_count,
            units_sum,
            metric_name="units_absolute",
        )
        _validate_coverage_sum(
            revenue_coverage_count,
            revenue_sum,
            metric_name="revenue_absolute",
        )
        _require_timestamp(self.calculated_at, field_name="calculated_at")
        object.__setattr__(self, "units_absolute_sum", units_sum)
        object.__setattr__(self, "revenue_absolute_sum", revenue_sum)


@dataclass(frozen=True, slots=True)
class ThemeMonthlyMetric:
    """One raw Game Theme's deterministic monthly metrics."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    product_count: int
    product_share: float
    top_100_count: int
    top_500_count: int
    average_rank: float
    median_rank: float
    units_absolute_coverage_count: int
    units_absolute_sum: float | None
    units_absolute_share: float | None
    revenue_absolute_coverage_count: int
    revenue_absolute_sum: float | None
    revenue_absolute_share: float | None
    has_previous_month: bool
    new_entry_count: int | None
    returning_product_count: int | None
    new_entry_share: float | None
    publisher_coverage_count: int
    publisher_count: int
    top_publisher_product_share: float | None
    calculated_at: datetime

    @property
    def period_key(self) -> tuple[str, str, date, date]:
        """Return the metric's derived-table identity without a storage import."""

        return (self.scope_name, self.cadence, self.period_start, self.period_end)

    def __post_init__(self) -> None:
        _require_text(self.scope_name, field_name="scope_name")
        if self.cadence != "monthly":
            raise AggregationValidationError("cadence must equal monthly")
        start = _require_date(self.period_start, field_name="period_start")
        end = _require_date(self.period_end, field_name="period_end")
        if start > end:
            raise AggregationValidationError("period_start must be on or before period_end")
        if not isinstance(self.game_theme, str):
            raise AggregationValidationError("game_theme must be a string")

        product_count = _require_count(
            self.product_count,
            field_name="product_count",
            minimum=1,
        )
        top_100_count = _require_count(self.top_100_count, field_name="top_100_count")
        top_500_count = _require_count(self.top_500_count, field_name="top_500_count")
        if top_100_count > product_count or top_500_count > product_count:
            raise AggregationValidationError(
                "top_100_count and top_500_count must not exceed product_count"
            )

        publisher_coverage_count = _require_count(
            self.publisher_coverage_count,
            field_name="publisher_coverage_count",
        )
        publisher_count = _require_count(self.publisher_count, field_name="publisher_count")
        if publisher_coverage_count > product_count:
            raise AggregationValidationError(
                "publisher_coverage_count must not exceed product_count"
            )
        if publisher_count > publisher_coverage_count:
            raise AggregationValidationError(
                "publisher_count must not exceed publisher_coverage_count"
            )
        units_coverage_count = _require_count(
            self.units_absolute_coverage_count,
            field_name="units_absolute_coverage_count",
        )
        revenue_coverage_count = _require_count(
            self.revenue_absolute_coverage_count,
            field_name="revenue_absolute_coverage_count",
        )
        if units_coverage_count > product_count or revenue_coverage_count > product_count:
            raise AggregationValidationError(
                "metric coverage counts must not exceed product_count"
            )

        if self.product_share is None:
            raise AggregationValidationError("product_share must be present")
        product_share = _validate_share(self.product_share, field_name="product_share")
        average_rank = _require_number(self.average_rank, field_name="average_rank")
        median_rank = _require_number(self.median_rank, field_name="median_rank")
        units_sum = _optional_number(self.units_absolute_sum, field_name="units_absolute_sum")
        revenue_sum = _optional_number(
            self.revenue_absolute_sum,
            field_name="revenue_absolute_sum",
        )
        _validate_coverage_sum(
            units_coverage_count,
            units_sum,
            metric_name="units_absolute",
        )
        _validate_coverage_sum(
            revenue_coverage_count,
            revenue_sum,
            metric_name="revenue_absolute",
        )
        units_share = _validate_share(
            self.units_absolute_share,
            field_name="units_absolute_share",
        )
        revenue_share = _validate_share(
            self.revenue_absolute_share,
            field_name="revenue_absolute_share",
        )
        if units_sum is None and units_share is not None:
            raise AggregationValidationError(
                "units_absolute_share must be NULL when its sum is unavailable"
            )
        if revenue_sum is None and revenue_share is not None:
            raise AggregationValidationError(
                "revenue_absolute_share must be NULL when its sum is unavailable"
            )
        if not isinstance(self.has_previous_month, bool):
            raise AggregationValidationError("has_previous_month must be a boolean")
        new_entry_count = _optional_count(self.new_entry_count, field_name="new_entry_count")
        returning_product_count = _optional_count(
            self.returning_product_count,
            field_name="returning_product_count",
        )
        new_entry_share = _validate_share(
            self.new_entry_share,
            field_name="new_entry_share",
        )
        if not self.has_previous_month:
            if (
                new_entry_count is not None
                or returning_product_count is not None
                or new_entry_share is not None
            ):
                raise AggregationValidationError(
                    "new-entry fields must be NULL without a previous month"
                )
        elif (
            new_entry_count is None
            or returning_product_count is None
            or new_entry_count + returning_product_count != product_count
        ):
            raise AggregationValidationError(
                "new-entry and returning counts must equal product_count"
            )
        top_publisher_share = _validate_share(
            self.top_publisher_product_share,
            field_name="top_publisher_product_share",
        )
        if publisher_coverage_count == 0 and top_publisher_share is not None:
            raise AggregationValidationError(
                "top_publisher_product_share must be NULL with zero publisher coverage"
            )
        if publisher_coverage_count > 0 and top_publisher_share is None:
            raise AggregationValidationError(
                "top_publisher_product_share must be present with publisher coverage"
            )
        _require_timestamp(self.calculated_at, field_name="calculated_at")
        object.__setattr__(self, "product_share", product_share)
        object.__setattr__(self, "average_rank", average_rank)
        object.__setattr__(self, "median_rank", median_rank)
        object.__setattr__(self, "units_absolute_sum", units_sum)
        object.__setattr__(self, "units_absolute_share", units_share)
        object.__setattr__(self, "revenue_absolute_sum", revenue_sum)
        object.__setattr__(self, "revenue_absolute_share", revenue_share)
        object.__setattr__(self, "new_entry_share", new_entry_share)
        object.__setattr__(self, "top_publisher_product_share", top_publisher_share)
