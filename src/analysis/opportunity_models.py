"""Typed V2 opportunity-evidence rows and their immutable result payload."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isclose, isfinite
from typing import Literal

from ..storage.models import normalize_storage_opaque_id
from .errors import AggregationValidationError
from .models import MonthlyMarketTotal, ThemeMonthlyMetric

type OpportunityDimensionType = Literal[
    "game_subgenre",
    "game_product_model",
    "game_art_style",
    "game_setting",
]
type RepresentativeEvidenceType = Literal[
    "downloads_leader",
    "revenue_leader",
    "market_new_entry_downloads_leader",
    "market_new_entry_revenue_leader",
    "downloads_growth_leader",
    "revenue_growth_leader",
]

OPPORTUNITY_DIMENSION_TYPES: tuple[OpportunityDimensionType, ...] = (
    "game_subgenre",
    "game_product_model",
    "game_art_style",
    "game_setting",
)
REPRESENTATIVE_EVIDENCE_TYPES: tuple[RepresentativeEvidenceType, ...] = (
    "downloads_leader",
    "revenue_leader",
    "market_new_entry_downloads_leader",
    "market_new_entry_revenue_leader",
    "downloads_growth_leader",
    "revenue_growth_leader",
)
DEFAULT_REPRESENTATIVE_GAME_LIMIT = 3


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AggregationValidationError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AggregationValidationError(f"{field_name} must be a string or NULL")
    return value


def _require_date(value: object, *, field_name: str) -> date:
    if type(value) is not date:
        raise AggregationValidationError(f"{field_name} must be a date")
    return value


def _require_natural_month(period_start: object, period_end: object) -> tuple[date, date]:
    start = _require_date(period_start, field_name="period_start")
    end = _require_date(period_end, field_name="period_end")
    if start.day != 1 or end != date(
        start.year,
        start.month,
        _month_days(start.year, start.month),
    ):
        raise AggregationValidationError("period must be one natural calendar month")
    return start, end


def _month_days(year: int, month: int) -> int:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (next_month - date(year, month, 1)).days


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


def _optional_signed_count(value: object, *, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AggregationValidationError(f"{field_name} must be an integer or NULL")
    return value


def _require_present_count(value: int | None, *, field_name: str) -> int:
    if value is None:
        raise AggregationValidationError(f"{field_name} is required")
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


def _optional_ratio(value: object, *, field_name: str) -> float | None:
    numeric_value = _optional_number(value, field_name=field_name)
    if numeric_value is not None and not 0 <= numeric_value <= 1:
        raise AggregationValidationError(f"{field_name} must be between 0 and 1")
    return numeric_value


def _validate_coverage_sum(
    coverage_count: int,
    value: float | None,
    *,
    metric_name: str,
) -> None:
    if coverage_count == 0 and value is not None:
        raise AggregationValidationError(f"{metric_name}_sum must be NULL when coverage is zero")
    if coverage_count > 0 and value is None:
        raise AggregationValidationError(
            f"{metric_name}_sum must be present when coverage is non-zero"
        )


def _validate_metric_group(
    *,
    product_count: int,
    coverage_count: int,
    coverage_ratio: float | None,
    metric_sum: float | None,
    metric_mean: float | None,
    metric_median: float | None,
    metric_name: str,
) -> tuple[float | None, float | None, float | None, float | None]:
    if coverage_count > product_count:
        raise AggregationValidationError(
            f"{metric_name}_coverage_count must not exceed product_count"
        )
    ratio = _optional_ratio(coverage_ratio, field_name=f"{metric_name}_coverage_ratio")
    total = _optional_number(metric_sum, field_name=f"{metric_name}_sum")
    mean = _optional_number(metric_mean, field_name=f"{metric_name}_mean_per_covered_product")
    median = _optional_number(metric_median, field_name=f"{metric_name}_median_per_covered_product")
    _validate_coverage_sum(coverage_count, total, metric_name=metric_name)
    if coverage_count == 0 and (mean is not None or median is not None):
        raise AggregationValidationError(
            f"{metric_name} mean and median must be NULL when coverage is zero"
        )
    if coverage_count > 0 and (mean is None or median is None):
        raise AggregationValidationError(
            f"{metric_name} mean and median must be present with coverage"
        )
    return ratio, total, mean, median


def _validate_concentration(
    value: object,
    *,
    field_name: str,
    metric_sum: float | None,
) -> float | None:
    concentration = _optional_ratio(value, field_name=field_name)
    if metric_sum is None or metric_sum <= 0:
        if concentration is not None:
            raise AggregationValidationError(
                f"{field_name} must be NULL when its compatible sum is unavailable or non-positive"
            )
    return concentration


def _validate_concentration_group(
    values: tuple[float | None, ...],
    *,
    field_names: tuple[str, ...],
    metric_sum: float | None,
) -> tuple[float | None, ...]:
    normalized = tuple(
        _validate_concentration(
            value,
            field_name=field_name,
            metric_sum=metric_sum,
        )
        for field_name, value in zip(field_names, values, strict=True)
    )
    if metric_sum is not None and metric_sum > 0 and any(value is None for value in normalized):
        raise AggregationValidationError(
            f"{field_names[0]} concentration fields are required with a positive sum"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class ThemeMarketStructureMetric:
    """Current-month market size and concentration evidence for one theme."""

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
    downloads_coverage_count: int
    downloads_coverage_ratio: float
    downloads_sum: float | None
    downloads_share: float | None
    downloads_mean_per_covered_product: float | None
    downloads_median_per_covered_product: float | None
    downloads_top_1_product_share: float | None
    downloads_top_3_product_share: float | None
    downloads_top_10_product_share: float | None
    downloads_product_hhi: float | None
    revenue_usd_coverage_count: int
    revenue_usd_coverage_ratio: float
    revenue_usd_sum: float | None
    revenue_usd_share: float | None
    revenue_usd_mean_per_covered_product: float | None
    revenue_usd_median_per_covered_product: float | None
    revenue_usd_top_1_product_share: float | None
    revenue_usd_top_3_product_share: float | None
    revenue_usd_top_10_product_share: float | None
    revenue_usd_product_hhi: float | None
    publisher_coverage_count: int
    publisher_coverage_ratio: float
    publisher_count: int
    top_1_publisher_product_share: float | None
    top_3_publisher_product_share: float | None
    publisher_product_hhi: float | None
    publisher_downloads_coverage_count: int
    publisher_downloads_coverage_ratio: float
    top_1_publisher_downloads_share: float | None
    top_3_publisher_downloads_share: float | None
    publisher_downloads_hhi: float | None
    publisher_revenue_usd_coverage_count: int
    publisher_revenue_usd_coverage_ratio: float
    top_1_publisher_revenue_usd_share: float | None
    top_3_publisher_revenue_usd_share: float | None
    publisher_revenue_usd_hhi: float | None
    release_date_ww_coverage_count: int
    release_date_ww_coverage_ratio: float
    release_date_ww_valid_age_count: int
    release_date_ww_future_count: int
    median_product_age_days: float | None
    downloads_top_10_median_product_age_days: float | None
    revenue_usd_top_10_median_product_age_days: float | None
    calculated_at: datetime

    @property
    def period_key(self) -> tuple[str, str, date, date]:
        """Return the month identity used by derived storage."""

        return (self.scope_name, self.cadence, self.period_start, self.period_end)

    def __post_init__(self) -> None:
        _require_text(self.scope_name, field_name="scope_name")
        if self.cadence != "monthly":
            raise AggregationValidationError("cadence must equal monthly")
        _require_natural_month(self.period_start, self.period_end)
        if not isinstance(self.game_theme, str):
            raise AggregationValidationError("game_theme must be a string")

        product_count = _require_count(self.product_count, field_name="product_count", minimum=1)
        top_100_count = _require_count(self.top_100_count, field_name="top_100_count")
        top_500_count = _require_count(self.top_500_count, field_name="top_500_count")
        if top_100_count > product_count or top_500_count > product_count:
            raise AggregationValidationError("top-rank counts must not exceed product_count")
        if top_100_count > top_500_count:
            raise AggregationValidationError("top_100_count must not exceed top_500_count")
        product_share = _optional_ratio(self.product_share, field_name="product_share")
        if product_share is None:
            raise AggregationValidationError("product_share must be present")
        average_rank = _require_number(self.average_rank, field_name="average_rank")
        median_rank = _require_number(self.median_rank, field_name="median_rank")

        downloads_coverage_count = _require_count(
            self.downloads_coverage_count,
            field_name="downloads_coverage_count",
        )
        downloads_ratio, downloads_sum, downloads_mean, downloads_median = _validate_metric_group(
            product_count=product_count,
            coverage_count=downloads_coverage_count,
            coverage_ratio=self.downloads_coverage_ratio,
            metric_sum=self.downloads_sum,
            metric_mean=self.downloads_mean_per_covered_product,
            metric_median=self.downloads_median_per_covered_product,
            metric_name="downloads",
        )
        revenue_coverage_count = _require_count(
            self.revenue_usd_coverage_count,
            field_name="revenue_usd_coverage_count",
        )
        revenue_ratio, revenue_sum, revenue_mean, revenue_median = _validate_metric_group(
            product_count=product_count,
            coverage_count=revenue_coverage_count,
            coverage_ratio=self.revenue_usd_coverage_ratio,
            metric_sum=self.revenue_usd_sum,
            metric_mean=self.revenue_usd_mean_per_covered_product,
            metric_median=self.revenue_usd_median_per_covered_product,
            metric_name="revenue_usd",
        )

        publisher_coverage_count = _require_count(
            self.publisher_coverage_count,
            field_name="publisher_coverage_count",
        )
        publisher_count = _require_count(self.publisher_count, field_name="publisher_count")
        if publisher_coverage_count > product_count or publisher_count > publisher_coverage_count:
            raise AggregationValidationError("publisher counts exceed product_count")
        publisher_ratio = _optional_ratio(
            self.publisher_coverage_ratio,
            field_name="publisher_coverage_ratio",
        )
        publisher_downloads_count = _require_count(
            self.publisher_downloads_coverage_count,
            field_name="publisher_downloads_coverage_count",
        )
        publisher_revenue_count = _require_count(
            self.publisher_revenue_usd_coverage_count,
            field_name="publisher_revenue_usd_coverage_count",
        )
        for field_name, count in (
            ("publisher_downloads_coverage_count", publisher_downloads_count),
            ("publisher_revenue_usd_coverage_count", publisher_revenue_count),
        ):
            if count > product_count:
                raise AggregationValidationError(f"{field_name} must not exceed product_count")
            if count > publisher_coverage_count:
                raise AggregationValidationError(
                    f"{field_name} must not exceed publisher_coverage_count"
                )
        publisher_downloads_ratio = _optional_ratio(
            self.publisher_downloads_coverage_ratio,
            field_name="publisher_downloads_coverage_ratio",
        )
        publisher_revenue_ratio = _optional_ratio(
            self.publisher_revenue_usd_coverage_ratio,
            field_name="publisher_revenue_usd_coverage_ratio",
        )

        release_coverage_count = _require_count(
            self.release_date_ww_coverage_count,
            field_name="release_date_ww_coverage_count",
        )
        release_valid_count = _require_count(
            self.release_date_ww_valid_age_count,
            field_name="release_date_ww_valid_age_count",
        )
        release_future_count = _require_count(
            self.release_date_ww_future_count,
            field_name="release_date_ww_future_count",
        )
        if release_coverage_count > product_count:
            raise AggregationValidationError("release-date coverage exceeds product_count")
        if release_valid_count + release_future_count != release_coverage_count:
            raise AggregationValidationError(
                "release-date valid and future counts must equal release-date coverage"
            )
        release_ratio = _optional_ratio(
            self.release_date_ww_coverage_ratio,
            field_name="release_date_ww_coverage_ratio",
        )

        ratio_fields = (
            ("downloads_share", self.downloads_share),
            ("revenue_usd_share", self.revenue_usd_share),
            ("top_1_publisher_product_share", self.top_1_publisher_product_share),
            ("top_3_publisher_product_share", self.top_3_publisher_product_share),
            ("publisher_product_hhi", self.publisher_product_hhi),
            ("top_1_publisher_downloads_share", self.top_1_publisher_downloads_share),
            ("top_3_publisher_downloads_share", self.top_3_publisher_downloads_share),
            ("publisher_downloads_hhi", self.publisher_downloads_hhi),
            ("top_1_publisher_revenue_usd_share", self.top_1_publisher_revenue_usd_share),
            ("top_3_publisher_revenue_usd_share", self.top_3_publisher_revenue_usd_share),
            ("publisher_revenue_usd_hhi", self.publisher_revenue_usd_hhi),
        )
        normalized_ratios = {
            field_name: _optional_ratio(value, field_name=field_name)
            for field_name, value in ratio_fields
        }
        for metric_name, metric_sum, values in (
            (
                "downloads",
                downloads_sum,
                (
                    self.downloads_top_1_product_share,
                    self.downloads_top_3_product_share,
                    self.downloads_top_10_product_share,
                    self.downloads_product_hhi,
                ),
            ),
            (
                "revenue_usd",
                revenue_sum,
                (
                    self.revenue_usd_top_1_product_share,
                    self.revenue_usd_top_3_product_share,
                    self.revenue_usd_top_10_product_share,
                    self.revenue_usd_product_hhi,
                ),
            ),
        ):
            concentration_fields = (
                f"{metric_name}_top_1_product_share",
                f"{metric_name}_top_3_product_share",
                f"{metric_name}_top_10_product_share",
                f"{metric_name}_product_hhi",
            )
            normalized_values = _validate_concentration_group(
                values,
                field_names=concentration_fields,
                metric_sum=metric_sum,
            )
            for field_name, value in zip(
                concentration_fields,
                normalized_values,
                strict=True,
            ):
                normalized_ratios[field_name] = value

        normalized_ages = {
            "median_product_age_days": _optional_number(
                self.median_product_age_days,
                field_name="median_product_age_days",
            ),
            "downloads_top_10_median_product_age_days": _optional_number(
                self.downloads_top_10_median_product_age_days,
                field_name="downloads_top_10_median_product_age_days",
            ),
            "revenue_usd_top_10_median_product_age_days": _optional_number(
                self.revenue_usd_top_10_median_product_age_days,
                field_name="revenue_usd_top_10_median_product_age_days",
            ),
        }
        if any(value is not None and value < 0 for value in normalized_ages.values()):
            raise AggregationValidationError("product ages must be non-negative")

        _require_timestamp(self.calculated_at, field_name="calculated_at")
        for field_name, value in (
            ("product_share", product_share),
            ("downloads_coverage_ratio", downloads_ratio),
            ("revenue_usd_coverage_ratio", revenue_ratio),
            ("publisher_coverage_ratio", publisher_ratio),
            ("publisher_downloads_coverage_ratio", publisher_downloads_ratio),
            ("publisher_revenue_usd_coverage_ratio", publisher_revenue_ratio),
            ("release_date_ww_coverage_ratio", release_ratio),
        ):
            if value is None:
                raise AggregationValidationError(f"{field_name} must be present")
            normalized_ratios[field_name] = value

        publisher_product_fields = (
            "top_1_publisher_product_share",
            "top_3_publisher_product_share",
            "publisher_product_hhi",
        )
        publisher_product_values = tuple(
            normalized_ratios[field_name] for field_name in publisher_product_fields
        )
        if publisher_coverage_count == 0 and any(
            value is not None for value in publisher_product_values
        ):
            raise AggregationValidationError(
                "publisher product concentration must be NULL with zero coverage"
            )
        if publisher_coverage_count > 0 and any(
            value is None for value in publisher_product_values
        ):
            raise AggregationValidationError(
                "publisher product concentration is required with coverage"
            )
        for prefix, coverage_count in (
            ("publisher_downloads", publisher_downloads_count),
            ("publisher_revenue_usd", publisher_revenue_count),
        ):
            publisher_concentration_fields = (
                f"top_1_{prefix}_share",
                f"top_3_{prefix}_share",
                f"{prefix}_hhi",
            )
            concentration_values = tuple(
                normalized_ratios[field_name] for field_name in publisher_concentration_fields
            )
            if coverage_count == 0 and any(value is not None for value in concentration_values):
                raise AggregationValidationError(
                    f"{prefix} concentration must be NULL with zero coverage"
                )
            if (
                coverage_count > 0
                and any(value is not None for value in concentration_values)
                and not all(value is not None for value in concentration_values)
            ):
                raise AggregationValidationError(
                    f"{prefix} concentration fields must be all present or all NULL"
                )

        object.__setattr__(self, "product_share", product_share)
        object.__setattr__(self, "average_rank", average_rank)
        object.__setattr__(self, "median_rank", median_rank)
        object.__setattr__(self, "downloads_coverage_ratio", downloads_ratio)
        object.__setattr__(self, "downloads_sum", downloads_sum)
        object.__setattr__(self, "downloads_mean_per_covered_product", downloads_mean)
        object.__setattr__(self, "downloads_median_per_covered_product", downloads_median)
        object.__setattr__(self, "revenue_usd_coverage_ratio", revenue_ratio)
        object.__setattr__(self, "revenue_usd_sum", revenue_sum)
        object.__setattr__(self, "revenue_usd_mean_per_covered_product", revenue_mean)
        object.__setattr__(self, "revenue_usd_median_per_covered_product", revenue_median)
        for field_name, value in normalized_ratios.items():
            object.__setattr__(self, field_name, value)
        for field_name, value in normalized_ages.items():
            object.__setattr__(self, field_name, value)


@dataclass(frozen=True, slots=True)
class ThemeGrowthSourceMetric:
    """Membership, turnover, persistence, and raw month-over-month evidence."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    has_previous_month: bool
    previous_product_count: int | None
    current_product_count: int
    product_count_change: int | None
    market_new_entry_count: int | None
    market_returning_product_count: int | None
    theme_entry_count: int | None
    theme_exit_count: int | None
    continuing_theme_product_count: int | None
    market_new_entry_share: float | None
    theme_entry_share: float | None
    market_new_entry_top_100_count: int | None
    market_new_entry_top_100_rate: float | None
    market_new_entry_top_500_count: int | None
    market_new_entry_top_500_rate: float | None
    top_100_current_count: int
    top_100_previous_count: int | None
    top_100_entry_count: int | None
    top_100_exit_count: int | None
    top_100_retained_count: int | None
    top_100_turnover_rate: float | None
    top_500_current_count: int
    top_500_previous_count: int | None
    top_500_entry_count: int | None
    top_500_exit_count: int | None
    top_500_retained_count: int | None
    top_500_turnover_rate: float | None
    downloads_top_10_current_count: int
    downloads_top_10_retained_count: int | None
    downloads_top_10_retention_rate: float | None
    revenue_usd_top_10_current_count: int
    revenue_usd_top_10_retained_count: int | None
    revenue_usd_top_10_retention_rate: float | None
    downloads_current_coverage_count: int
    downloads_previous_coverage_count: int | None
    downloads_decomposition_complete: bool | None
    downloads_current_sum: float | None
    downloads_previous_sum: float | None
    downloads_mom_change: float | None
    downloads_mom_growth_rate: float | None
    downloads_market_new_entry_sum: float | None
    downloads_market_new_entry_share_of_current: float | None
    downloads_theme_entry_contribution: float | None
    downloads_continuing_contribution: float | None
    downloads_theme_exit_contribution: float | None
    downloads_positive_contribution_sum: float | None
    downloads_negative_contribution_sum: float | None
    downloads_positive_contributor_count: int | None
    downloads_negative_contributor_count: int | None
    downloads_unchanged_contributor_count: int | None
    downloads_market_new_entry_positive_contribution_share: float | None
    downloads_continuing_positive_contribution_share: float | None
    downloads_top_1_positive_contribution_share: float | None
    downloads_top_3_positive_contribution_share: float | None
    downloads_top_10_positive_contribution_share: float | None
    revenue_usd_current_coverage_count: int
    revenue_usd_previous_coverage_count: int | None
    revenue_usd_decomposition_complete: bool | None
    revenue_usd_current_sum: float | None
    revenue_usd_previous_sum: float | None
    revenue_usd_mom_change: float | None
    revenue_usd_mom_growth_rate: float | None
    revenue_usd_market_new_entry_sum: float | None
    revenue_usd_market_new_entry_share_of_current: float | None
    revenue_usd_theme_entry_contribution: float | None
    revenue_usd_continuing_contribution: float | None
    revenue_usd_theme_exit_contribution: float | None
    revenue_usd_positive_contribution_sum: float | None
    revenue_usd_negative_contribution_sum: float | None
    revenue_usd_positive_contributor_count: int | None
    revenue_usd_negative_contributor_count: int | None
    revenue_usd_unchanged_contributor_count: int | None
    revenue_usd_market_new_entry_positive_contribution_share: float | None
    revenue_usd_continuing_positive_contribution_share: float | None
    revenue_usd_top_1_positive_contribution_share: float | None
    revenue_usd_top_3_positive_contribution_share: float | None
    revenue_usd_top_10_positive_contribution_share: float | None
    calculated_at: datetime

    @property
    def period_key(self) -> tuple[str, str, date, date]:
        """Return the month identity used by derived storage."""

        return (self.scope_name, self.cadence, self.period_start, self.period_end)

    def __post_init__(self) -> None:
        _validate_identity(
            self.scope_name,
            self.cadence,
            self.period_start,
            self.period_end,
            self.game_theme,
        )
        if not isinstance(self.has_previous_month, bool):
            raise AggregationValidationError("has_previous_month must be a boolean")
        current_count = _require_count(
            self.current_product_count,
            field_name="current_product_count",
            minimum=1,
        )
        current_coverage_counts: dict[str, int] = {}
        for prefix in ("downloads", "revenue_usd"):
            current_coverage = _require_count(
                getattr(self, f"{prefix}_current_coverage_count"),
                field_name=f"{prefix}_current_coverage_count",
            )
            if current_coverage > current_count:
                raise AggregationValidationError(
                    f"{prefix}_current_coverage_count exceeds current_product_count"
                )
            current_coverage_counts[prefix] = current_coverage
        previous_count = _optional_count(
            self.previous_product_count,
            field_name="previous_product_count",
        )
        product_change = _optional_signed_count(
            self.product_count_change,
            field_name="product_count_change",
        )
        if product_change is not None and self.product_count_change != product_change:
            raise AggregationValidationError("product_count_change must be an integer")
        if product_change is not None and previous_count is None:
            raise AggregationValidationError("product_count_change requires previous_product_count")
        if product_change is not None and product_change != current_count - previous_count:  # type: ignore[operator]
            raise AggregationValidationError(
                "product_count_change does not match membership counts"
            )

        count_fields = (
            "market_new_entry_count",
            "market_returning_product_count",
            "theme_entry_count",
            "theme_exit_count",
            "continuing_theme_product_count",
            "market_new_entry_top_100_count",
            "market_new_entry_top_500_count",
            "top_100_previous_count",
            "top_100_entry_count",
            "top_100_exit_count",
            "top_100_retained_count",
            "top_500_previous_count",
            "top_500_entry_count",
            "top_500_exit_count",
            "top_500_retained_count",
            "downloads_top_10_retained_count",
            "revenue_usd_top_10_retained_count",
            "downloads_previous_coverage_count",
            "revenue_usd_previous_coverage_count",
            "downloads_positive_contributor_count",
            "downloads_negative_contributor_count",
            "downloads_unchanged_contributor_count",
            "revenue_usd_positive_contributor_count",
            "revenue_usd_negative_contributor_count",
            "revenue_usd_unchanged_contributor_count",
        )
        normalized_counts: dict[str, int | None] = {}
        for field_name in count_fields:
            normalized_counts[field_name] = _optional_count(
                getattr(self, field_name),
                field_name=field_name,
            )
        top_current_fields = (
            "top_100_current_count",
            "top_500_current_count",
            "downloads_top_10_current_count",
            "revenue_usd_top_10_current_count",
        )
        for field_name in top_current_fields:
            normalized_value = _require_count(getattr(self, field_name), field_name=field_name)
            if normalized_value > current_count:
                raise AggregationValidationError(
                    f"{field_name} must not exceed current_product_count"
                )
            normalized_counts[field_name] = normalized_value
        top_100_current = normalized_counts["top_100_current_count"]
        top_500_current = normalized_counts["top_500_current_count"]
        if top_100_current is None or top_500_current is None:
            raise AggregationValidationError("current rank counts are required")
        if top_100_current > top_500_current:
            raise AggregationValidationError(
                "top_100_current_count must not exceed top_500_current_count"
            )

        ratio_fields = (
            "market_new_entry_share",
            "theme_entry_share",
            "market_new_entry_top_100_rate",
            "market_new_entry_top_500_rate",
            "top_100_turnover_rate",
            "top_500_turnover_rate",
            "downloads_top_10_retention_rate",
            "revenue_usd_top_10_retention_rate",
            "downloads_market_new_entry_share_of_current",
            "downloads_market_new_entry_positive_contribution_share",
            "downloads_continuing_positive_contribution_share",
            "downloads_top_1_positive_contribution_share",
            "downloads_top_3_positive_contribution_share",
            "downloads_top_10_positive_contribution_share",
            "revenue_usd_market_new_entry_share_of_current",
            "revenue_usd_market_new_entry_positive_contribution_share",
            "revenue_usd_continuing_positive_contribution_share",
            "revenue_usd_top_1_positive_contribution_share",
            "revenue_usd_top_3_positive_contribution_share",
            "revenue_usd_top_10_positive_contribution_share",
        )
        normalized_ratios = {
            field_name: _optional_ratio(getattr(self, field_name), field_name=field_name)
            for field_name in ratio_fields
        }

        metric_number_fields = (
            "downloads_current_sum",
            "downloads_previous_sum",
            "downloads_mom_change",
            "downloads_mom_growth_rate",
            "downloads_market_new_entry_sum",
            "downloads_theme_entry_contribution",
            "downloads_continuing_contribution",
            "downloads_theme_exit_contribution",
            "downloads_positive_contribution_sum",
            "downloads_negative_contribution_sum",
            "revenue_usd_current_sum",
            "revenue_usd_previous_sum",
            "revenue_usd_mom_change",
            "revenue_usd_mom_growth_rate",
            "revenue_usd_market_new_entry_sum",
            "revenue_usd_theme_entry_contribution",
            "revenue_usd_continuing_contribution",
            "revenue_usd_theme_exit_contribution",
            "revenue_usd_positive_contribution_sum",
            "revenue_usd_negative_contribution_sum",
        )
        normalized_numbers = {
            field_name: _optional_number(getattr(self, field_name), field_name=field_name)
            for field_name in metric_number_fields
        }

        for metric_name in ("downloads", "revenue_usd"):
            current_coverage = _require_count(
                getattr(self, f"{metric_name}_current_coverage_count"),
                field_name=f"{metric_name}_current_coverage_count",
            )
            previous_coverage = normalized_counts[f"{metric_name}_previous_coverage_count"]
            current_sum = normalized_numbers[f"{metric_name}_current_sum"]
            previous_sum = normalized_numbers[f"{metric_name}_previous_sum"]
            _validate_coverage_sum(
                current_coverage, current_sum, metric_name=f"{metric_name}_current"
            )
            if previous_coverage is not None:
                if previous_sum is not None and previous_coverage == 0:
                    raise AggregationValidationError(
                        f"{metric_name}_previous_sum must be NULL when coverage is zero"
                    )
                if previous_coverage > 0 and previous_sum is None:
                    raise AggregationValidationError(
                        f"{metric_name}_previous_sum must be present with coverage"
                    )

        if not self.has_previous_month:
            previous_fields = (
                "previous_product_count",
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
                "top_100_previous_count",
                "top_100_entry_count",
                "top_100_exit_count",
                "top_100_retained_count",
                "top_100_turnover_rate",
                "top_500_previous_count",
                "top_500_entry_count",
                "top_500_exit_count",
                "top_500_retained_count",
                "top_500_turnover_rate",
                "downloads_top_10_retained_count",
                "downloads_top_10_retention_rate",
                "revenue_usd_top_10_retained_count",
                "revenue_usd_top_10_retention_rate",
                "downloads_previous_coverage_count",
                "downloads_decomposition_complete",
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
                "revenue_usd_previous_coverage_count",
                "revenue_usd_decomposition_complete",
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
            )
            if any(getattr(self, field_name) is not None for field_name in previous_fields):
                raise AggregationValidationError(
                    "previous-month fields must be NULL when no previous month exists"
                )
        else:
            if previous_count is None:
                raise AggregationValidationError(
                    "previous_product_count is required with a previous month"
                )
            if product_change is None:
                raise AggregationValidationError(
                    "product_count_change is required with a previous month"
                )
            if any(
                normalized_counts[field_name] is None
                for field_name in (
                    "market_new_entry_count",
                    "market_returning_product_count",
                    "theme_entry_count",
                    "theme_exit_count",
                    "continuing_theme_product_count",
                )
            ):
                raise AggregationValidationError(
                    "membership counts are required with a previous month"
                )
            market_new_count = _require_present_count(
                normalized_counts["market_new_entry_count"],
                field_name="market_new_entry_count",
            )
            market_returning_count = _require_present_count(
                normalized_counts["market_returning_product_count"],
                field_name="market_returning_product_count",
            )
            theme_entry_count = _require_present_count(
                normalized_counts["theme_entry_count"],
                field_name="theme_entry_count",
            )
            continuing_count = _require_present_count(
                normalized_counts["continuing_theme_product_count"],
                field_name="continuing_theme_product_count",
            )
            theme_exit_count = _require_present_count(
                normalized_counts["theme_exit_count"],
                field_name="theme_exit_count",
            )
            if market_new_count + market_returning_count != current_count:
                raise AggregationValidationError(
                    "market entry counts do not equal current_product_count"
                )
            if theme_entry_count + continuing_count != current_count:
                raise AggregationValidationError(
                    "theme membership counts do not equal current_product_count"
                )
            if theme_exit_count > previous_count:
                raise AggregationValidationError("theme_exit_count exceeds previous_product_count")
            if (market_new_count == 0 and self.market_new_entry_top_100_rate is not None) or (
                market_new_count == 0 and self.market_new_entry_top_500_rate is not None
            ):
                raise AggregationValidationError(
                    "new-entry rank rates must be NULL with zero market-new entries"
                )
            if market_new_count > 0 and (
                self.market_new_entry_top_100_rate is None
                or self.market_new_entry_top_500_rate is None
            ):
                raise AggregationValidationError(
                    "new-entry rank rates are required with market-new entries"
                )
            for prefix in ("top_100", "top_500"):
                current_value = _require_present_count(
                    normalized_counts[f"{prefix}_current_count"],
                    field_name=f"{prefix}_current_count",
                )
                previous_value = _require_present_count(
                    normalized_counts[f"{prefix}_previous_count"],
                    field_name=f"{prefix}_previous_count",
                )
                entry_value = _require_present_count(
                    normalized_counts[f"{prefix}_entry_count"],
                    field_name=f"{prefix}_entry_count",
                )
                exit_value = _require_present_count(
                    normalized_counts[f"{prefix}_exit_count"],
                    field_name=f"{prefix}_exit_count",
                )
                retained_value = _require_present_count(
                    normalized_counts[f"{prefix}_retained_count"],
                    field_name=f"{prefix}_retained_count",
                )
                if entry_value + retained_value != current_value:
                    raise AggregationValidationError(
                        f"{prefix} entry and retained counts are inconsistent"
                    )
                if exit_value + retained_value != previous_value:
                    raise AggregationValidationError(
                        f"{prefix} exit and retained counts are inconsistent"
                    )
                if current_value > current_count or previous_value > previous_count:
                    raise AggregationValidationError(f"{prefix} turnover counts exceed membership")
                turnover_rate = getattr(self, f"{prefix}_turnover_rate")
                if current_value == 0 and turnover_rate is not None:
                    raise AggregationValidationError(
                        f"{prefix}_turnover_rate must be NULL with an empty current set"
                    )
                if current_value > 0 and turnover_rate is None:
                    raise AggregationValidationError(
                        f"{prefix}_turnover_rate is required with a current set"
                    )
            for prefix in ("downloads", "revenue_usd"):
                current_top10 = _require_present_count(
                    normalized_counts[f"{prefix}_top_10_current_count"],
                    field_name=f"{prefix}_top_10_current_count",
                )
                retention_rate = getattr(self, f"{prefix}_top_10_retention_rate")
                if current_top10 == 0 and retention_rate is not None:
                    raise AggregationValidationError(
                        f"{prefix}_top_10_retention_rate must be NULL with zero current coverage"
                    )
                if current_top10 > 0 and retention_rate is None:
                    raise AggregationValidationError(
                        f"{prefix}_top_10_retention_rate is required with current coverage"
                    )
            for prefix in ("downloads", "revenue_usd"):
                complete = getattr(self, f"{prefix}_decomposition_complete")
                if complete is not None and not isinstance(complete, bool):
                    raise AggregationValidationError(
                        f"{prefix}_decomposition_complete must be a boolean or NULL"
                    )
                if complete is None:
                    raise AggregationValidationError(
                        f"{prefix}_decomposition_complete is required with a previous month"
                    )

                current_coverage = current_coverage_counts[prefix]
                previous_coverage = normalized_counts[f"{prefix}_previous_coverage_count"]
                if previous_coverage is None:
                    raise AggregationValidationError(
                        f"{prefix}_previous_coverage_count is required with a previous month"
                    )
                if previous_coverage > previous_count:
                    raise AggregationValidationError(
                        f"{prefix}_previous_coverage_count exceeds previous_product_count"
                    )

                contribution_number_fields = (
                    f"{prefix}_mom_change",
                    f"{prefix}_mom_growth_rate",
                    f"{prefix}_market_new_entry_sum",
                    f"{prefix}_theme_entry_contribution",
                    f"{prefix}_continuing_contribution",
                    f"{prefix}_theme_exit_contribution",
                    f"{prefix}_positive_contribution_sum",
                    f"{prefix}_negative_contribution_sum",
                )
                contribution_count_fields = (
                    f"{prefix}_positive_contributor_count",
                    f"{prefix}_negative_contributor_count",
                    f"{prefix}_unchanged_contributor_count",
                )
                contribution_share_fields = (
                    f"{prefix}_market_new_entry_positive_contribution_share",
                    f"{prefix}_continuing_positive_contribution_share",
                    f"{prefix}_top_1_positive_contribution_share",
                    f"{prefix}_top_3_positive_contribution_share",
                    f"{prefix}_top_10_positive_contribution_share",
                )
                contribution_fields = (
                    *contribution_number_fields,
                    *contribution_count_fields,
                    *contribution_share_fields,
                )
                required_contribution_fields = (
                    *(
                        field_name
                        for field_name in contribution_number_fields
                        if not field_name.endswith("mom_growth_rate")
                    ),
                    *contribution_count_fields,
                )
                if not complete:
                    if any(
                        getattr(self, field_name) is not None for field_name in contribution_fields
                    ):
                        raise AggregationValidationError(
                            f"{prefix} incomplete decomposition must leave contribution fields NULL"
                        )
                    continue

                if current_coverage == 0:
                    raise AggregationValidationError(
                        f"{prefix} complete decomposition requires current coverage"
                    )
                current_sum = normalized_numbers[f"{prefix}_current_sum"]
                previous_sum = normalized_numbers[f"{prefix}_previous_sum"]
                mom_change = normalized_numbers[f"{prefix}_mom_change"]
                if current_sum is None or mom_change is None:
                    raise AggregationValidationError(
                        f"{prefix} complete decomposition requires current sum and change"
                    )
                expected_change = current_sum - (previous_sum or 0.0)
                if not isclose(mom_change, expected_change, rel_tol=1e-9, abs_tol=1e-9):
                    raise AggregationValidationError(
                        f"{prefix} month-over-month change does not reconcile"
                    )
                if any(
                    getattr(self, field_name) is None for field_name in required_contribution_fields
                ):
                    raise AggregationValidationError(
                        f"{prefix} complete decomposition requires contribution fields"
                    )
                positive_sum = normalized_numbers[f"{prefix}_positive_contribution_sum"]
                negative_sum = normalized_numbers[f"{prefix}_negative_contribution_sum"]
                if positive_sum is None or positive_sum < 0:
                    raise AggregationValidationError(
                        f"{prefix}_positive_contribution_sum must be non-negative"
                    )
                if negative_sum is None or negative_sum > 0:
                    raise AggregationValidationError(
                        f"{prefix}_negative_contribution_sum must be non-positive"
                    )
                if not isclose(
                    positive_sum + negative_sum,
                    mom_change,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                ):
                    raise AggregationValidationError(
                        f"{prefix} gross contributions do not reconcile"
                    )
                positive_count = normalized_counts[f"{prefix}_positive_contributor_count"]
                negative_count = normalized_counts[f"{prefix}_negative_contributor_count"]
                unchanged_count = normalized_counts[f"{prefix}_unchanged_contributor_count"]
                continuing_members = normalized_counts["continuing_theme_product_count"]
                continuing_members = _require_present_count(
                    continuing_members,
                    field_name="continuing_theme_product_count",
                )
                union_count = current_count + previous_count - continuing_members
                positive_count = _require_present_count(
                    positive_count,
                    field_name=f"{prefix}_positive_contributor_count",
                )
                negative_count = _require_present_count(
                    negative_count,
                    field_name=f"{prefix}_negative_contributor_count",
                )
                unchanged_count = _require_present_count(
                    unchanged_count,
                    field_name=f"{prefix}_unchanged_contributor_count",
                )
                if positive_count + negative_count + unchanged_count != union_count:
                    raise AggregationValidationError(
                        f"{prefix} contributor counts do not equal the membership union"
                    )
                growth_rate = normalized_numbers[f"{prefix}_mom_growth_rate"]
                if previous_sum is None or previous_sum <= 0:
                    if growth_rate is not None:
                        raise AggregationValidationError(
                            f"{prefix}_mom_growth_rate requires a positive previous sum"
                        )
                elif growth_rate is None or not isclose(
                    growth_rate,
                    mom_change / previous_sum,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                ):
                    raise AggregationValidationError(
                        f"{prefix}_mom_growth_rate does not match the previous sum"
                    )
                positive_shares = tuple(
                    getattr(self, field_name) for field_name in contribution_share_fields
                )
                if positive_sum == 0 and any(value is not None for value in positive_shares):
                    raise AggregationValidationError(
                        f"{prefix} positive contribution shares require a positive gross sum"
                    )
                if positive_sum > 0 and any(value is None for value in positive_shares):
                    raise AggregationValidationError(
                        f"{prefix} positive contribution shares are required with "
                        "a positive gross sum"
                    )

        for field_name, count_value in normalized_counts.items():
            object.__setattr__(self, field_name, count_value)
        for field_name, ratio_value in normalized_ratios.items():
            object.__setattr__(self, field_name, ratio_value)
        for field_name, number_value in normalized_numbers.items():
            object.__setattr__(self, field_name, number_value)
        _require_timestamp(self.calculated_at, field_name="calculated_at")


@dataclass(frozen=True, slots=True)
class ThemeDimensionMonthlyMetric:
    """Observed theme adoption for one raw product dimension value."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    dimension_type: OpportunityDimensionType
    dimension_value: str
    product_count: int
    product_share_within_theme: float
    product_share_within_market: float
    top_100_count: int
    top_500_count: int
    average_rank: float
    median_rank: float
    downloads_coverage_count: int
    downloads_sum: float | None
    downloads_share_within_theme: float | None
    downloads_share_within_market: float | None
    downloads_mean_per_covered_product: float | None
    downloads_median_per_covered_product: float | None
    downloads_top_1_product_share: float | None
    revenue_usd_coverage_count: int
    revenue_usd_sum: float | None
    revenue_usd_share_within_theme: float | None
    revenue_usd_share_within_market: float | None
    revenue_usd_mean_per_covered_product: float | None
    revenue_usd_median_per_covered_product: float | None
    revenue_usd_top_1_product_share: float | None
    has_previous_month: bool
    market_new_entry_count: int | None
    market_new_entry_share: float | None
    market_new_entry_top_100_count: int | None
    market_new_entry_top_100_rate: float | None
    market_new_entry_top_500_count: int | None
    market_new_entry_top_500_rate: float | None
    publisher_coverage_count: int
    publisher_count: int
    top_1_publisher_product_share: float | None
    calculated_at: datetime

    @property
    def period_key(self) -> tuple[str, str, date, date]:
        """Return the month identity used by derived storage."""

        return (self.scope_name, self.cadence, self.period_start, self.period_end)

    def __post_init__(self) -> None:
        _validate_identity(
            self.scope_name,
            self.cadence,
            self.period_start,
            self.period_end,
            self.game_theme,
        )
        if self.dimension_type not in OPPORTUNITY_DIMENSION_TYPES:
            raise AggregationValidationError("dimension_type is not supported")
        if not isinstance(self.dimension_value, str):
            raise AggregationValidationError("dimension_value must be a string")
        product_count = _require_count(self.product_count, field_name="product_count", minimum=1)
        top100 = _require_count(self.top_100_count, field_name="top_100_count")
        top500 = _require_count(self.top_500_count, field_name="top_500_count")
        if top100 > product_count or top500 > product_count:
            raise AggregationValidationError("top-rank counts must not exceed product_count")
        if top100 > top500:
            raise AggregationValidationError("top_100_count must not exceed top_500_count")
        for field_name in ("product_share_within_theme", "product_share_within_market"):
            if _optional_ratio(getattr(self, field_name), field_name=field_name) is None:
                raise AggregationValidationError(f"{field_name} must be present")
        average_rank = _require_number(self.average_rank, field_name="average_rank")
        median_rank = _require_number(self.median_rank, field_name="median_rank")

        downloads_count = _require_count(
            self.downloads_coverage_count,
            field_name="downloads_coverage_count",
        )
        downloads_sum = _optional_number(self.downloads_sum, field_name="downloads_sum")
        _validate_coverage_sum(downloads_count, downloads_sum, metric_name="downloads")
        revenue_count = _require_count(
            self.revenue_usd_coverage_count,
            field_name="revenue_usd_coverage_count",
        )
        revenue_sum = _optional_number(self.revenue_usd_sum, field_name="revenue_usd_sum")
        _validate_coverage_sum(revenue_count, revenue_sum, metric_name="revenue_usd")
        for metric_name, count in (
            ("downloads", downloads_count),
            ("revenue_usd", revenue_count),
        ):
            if count > product_count:
                raise AggregationValidationError(
                    f"{metric_name}_coverage_count exceeds product_count"
                )

        optional_numbers: dict[str, float | None] = {}
        for field_name in (
            "downloads_share_within_theme",
            "downloads_share_within_market",
            "downloads_mean_per_covered_product",
            "downloads_median_per_covered_product",
            "downloads_top_1_product_share",
            "revenue_usd_share_within_theme",
            "revenue_usd_share_within_market",
            "revenue_usd_mean_per_covered_product",
            "revenue_usd_median_per_covered_product",
            "revenue_usd_top_1_product_share",
            "market_new_entry_share",
            "market_new_entry_top_100_rate",
            "market_new_entry_top_500_rate",
            "top_1_publisher_product_share",
        ):
            if "share" in field_name or "rate" in field_name:
                optional_numbers[field_name] = _optional_ratio(
                    getattr(self, field_name),
                    field_name=field_name,
                )
            else:
                optional_numbers[field_name] = _optional_number(
                    getattr(self, field_name),
                    field_name=field_name,
                )
        if downloads_count == 0 and any(
            optional_numbers[field_name] is not None
            for field_name in (
                "downloads_mean_per_covered_product",
                "downloads_median_per_covered_product",
            )
        ):
            raise AggregationValidationError("downloads statistics require coverage")
        if revenue_count == 0 and any(
            optional_numbers[field_name] is not None
            for field_name in (
                "revenue_usd_mean_per_covered_product",
                "revenue_usd_median_per_covered_product",
            )
        ):
            raise AggregationValidationError("revenue_usd statistics require coverage")

        for metric_sum, field_names in (
            (
                downloads_sum,
                ("downloads_top_1_product_share",),
            ),
            (
                revenue_sum,
                ("revenue_usd_top_1_product_share",),
            ),
        ):
            normalized_concentrations = _validate_concentration_group(
                tuple(optional_numbers[field_name] for field_name in field_names),
                field_names=field_names,
                metric_sum=metric_sum,
            )
            for field_name, value in zip(field_names, normalized_concentrations, strict=True):
                optional_numbers[field_name] = value

        publisher_coverage = _require_count(
            self.publisher_coverage_count,
            field_name="publisher_coverage_count",
        )
        publisher_count = _require_count(self.publisher_count, field_name="publisher_count")
        if publisher_coverage > product_count or publisher_count > publisher_coverage:
            raise AggregationValidationError("publisher counts exceed product_count")

        if not isinstance(self.has_previous_month, bool):
            raise AggregationValidationError("has_previous_month must be a boolean")
        entry_count = _optional_count(
            self.market_new_entry_count,
            field_name="market_new_entry_count",
        )
        top100_entry = _optional_count(
            self.market_new_entry_top_100_count,
            field_name="market_new_entry_top_100_count",
        )
        top500_entry = _optional_count(
            self.market_new_entry_top_500_count,
            field_name="market_new_entry_top_500_count",
        )
        if not self.has_previous_month and any(
            value is not None
            for value in (
                entry_count,
                optional_numbers["market_new_entry_share"],
                top100_entry,
                optional_numbers["market_new_entry_top_100_rate"],
                top500_entry,
                optional_numbers["market_new_entry_top_500_rate"],
            )
        ):
            raise AggregationValidationError("new-entry fields require a previous month")
        if self.has_previous_month:
            if entry_count is None or top100_entry is None or top500_entry is None:
                raise AggregationValidationError("new-entry counts require a previous month")
            if (
                entry_count > product_count
                or top100_entry > entry_count
                or top500_entry > entry_count
            ):
                raise AggregationValidationError("new-entry counts are inconsistent")
            if entry_count == 0 and (
                optional_numbers["market_new_entry_top_100_rate"] is not None
                or optional_numbers["market_new_entry_top_500_rate"] is not None
            ):
                raise AggregationValidationError(
                    "dimension new-entry rank rates must be NULL with zero entries"
                )
            if entry_count > 0 and (
                optional_numbers["market_new_entry_top_100_rate"] is None
                or optional_numbers["market_new_entry_top_500_rate"] is None
            ):
                raise AggregationValidationError(
                    "dimension new-entry rank rates are required with entries"
                )

        if (
            publisher_coverage == 0
            and optional_numbers["top_1_publisher_product_share"] is not None
        ):
            raise AggregationValidationError("publisher share requires publisher coverage")
        if publisher_coverage > 0 and optional_numbers["top_1_publisher_product_share"] is None:
            raise AggregationValidationError("publisher share is required with publisher coverage")
        _require_timestamp(self.calculated_at, field_name="calculated_at")
        object.__setattr__(self, "average_rank", average_rank)
        object.__setattr__(self, "median_rank", median_rank)
        object.__setattr__(self, "downloads_sum", downloads_sum)
        object.__setattr__(self, "revenue_usd_sum", revenue_sum)
        for field_name, value in optional_numbers.items():
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "market_new_entry_count", entry_count)
        object.__setattr__(self, "market_new_entry_top_100_count", top100_entry)
        object.__setattr__(self, "market_new_entry_top_500_count", top500_entry)


@dataclass(frozen=True, slots=True)
class ThemeRepresentativeGame:
    """One traceable product selected as raw theme evidence."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    evidence_type: RepresentativeEvidenceType
    evidence_rank: int
    source_app_id: str
    unified_app_id: str
    game_name: str | None
    publisher_display_name: str | None
    game_subgenre: str | None
    game_product_model: str | None
    game_art_style: str | None
    game_setting: str | None
    release_date_ww: date | None
    rank_position: int
    previous_rank_position: int | None
    downloads: float | None
    previous_downloads: float | None
    downloads_change: float | None
    revenue_usd: float | None
    previous_revenue_usd: float | None
    revenue_usd_change: float | None
    is_market_new_entry: bool | None
    is_theme_entry: bool | None
    calculated_at: datetime

    @property
    def period_key(self) -> tuple[str, str, date, date]:
        """Return the month identity used by derived storage."""

        return (self.scope_name, self.cadence, self.period_start, self.period_end)

    def __post_init__(self) -> None:
        _validate_identity(
            self.scope_name,
            self.cadence,
            self.period_start,
            self.period_end,
            self.game_theme,
        )
        if self.evidence_type not in REPRESENTATIVE_EVIDENCE_TYPES:
            raise AggregationValidationError("evidence_type is not supported")
        evidence_rank = _require_count(
            self.evidence_rank,
            field_name="evidence_rank",
            minimum=1,
        )
        if evidence_rank > DEFAULT_REPRESENTATIVE_GAME_LIMIT:
            raise AggregationValidationError(
                f"evidence_rank must not exceed {DEFAULT_REPRESENTATIVE_GAME_LIMIT}"
            )
        try:
            source_app_id = normalize_storage_opaque_id(
                self.source_app_id,
                field_name="source_app_id",
            )
            unified_app_id = normalize_storage_opaque_id(
                self.unified_app_id,
                field_name="unified_app_id",
            )
        except Exception as error:
            raise AggregationValidationError(
                "representative product identity is invalid"
            ) from error
        for field_name in (
            "game_name",
            "publisher_display_name",
            "game_subgenre",
            "game_product_model",
            "game_art_style",
            "game_setting",
        ):
            _optional_text(getattr(self, field_name), field_name=field_name)
        release_date = self.release_date_ww
        if release_date is not None:
            release_date = _require_date(release_date, field_name="release_date_ww")
        rank_position = _require_count(self.rank_position, field_name="rank_position", minimum=1)
        previous_rank = _optional_count(
            self.previous_rank_position,
            field_name="previous_rank_position",
        )
        if previous_rank == 0:
            raise AggregationValidationError("previous_rank_position must be positive when present")
        numbers = {
            field_name: _optional_number(getattr(self, field_name), field_name=field_name)
            for field_name in (
                "downloads",
                "previous_downloads",
                "downloads_change",
                "revenue_usd",
                "previous_revenue_usd",
                "revenue_usd_change",
            )
        }
        for field_name in ("is_market_new_entry", "is_theme_entry"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, bool):
                raise AggregationValidationError(f"{field_name} must be a boolean or NULL")
        _require_timestamp(self.calculated_at, field_name="calculated_at")
        object.__setattr__(self, "source_app_id", source_app_id)
        object.__setattr__(self, "unified_app_id", unified_app_id)
        object.__setattr__(self, "evidence_rank", evidence_rank)
        object.__setattr__(self, "rank_position", rank_position)
        object.__setattr__(self, "previous_rank_position", previous_rank)
        object.__setattr__(self, "release_date_ww", release_date)
        for field_name, value in numbers.items():
            object.__setattr__(self, field_name, value)


@dataclass(frozen=True, slots=True)
class OpportunityAggregationResult:
    """Complete AGG-001 plus AGG-002 derived replacement payload."""

    monthly_totals: tuple[MonthlyMarketTotal, ...]
    theme_metrics: tuple[ThemeMonthlyMetric, ...]
    theme_market_structure_metrics: tuple[ThemeMarketStructureMetric, ...]
    theme_growth_source_metrics: tuple[ThemeGrowthSourceMetric, ...]
    theme_dimension_monthly_metrics: tuple[ThemeDimensionMonthlyMetric, ...]
    theme_representative_games: tuple[ThemeRepresentativeGame, ...]

    @property
    def market_structure_metrics(self) -> tuple[ThemeMarketStructureMetric, ...]:
        """Return the V2 structure rows under a concise compatibility name."""

        return self.theme_market_structure_metrics

    @property
    def growth_source_metrics(self) -> tuple[ThemeGrowthSourceMetric, ...]:
        """Return the V2 growth rows under a concise compatibility name."""

        return self.theme_growth_source_metrics

    @property
    def dimension_metrics(self) -> tuple[ThemeDimensionMonthlyMetric, ...]:
        """Return the V2 dimension rows under a concise compatibility name."""

        return self.theme_dimension_monthly_metrics

    @property
    def representative_games(self) -> tuple[ThemeRepresentativeGame, ...]:
        """Return the V2 representative rows under a concise compatibility name."""

        return self.theme_representative_games


def _validate_identity(
    scope_name: object,
    cadence: object,
    period_start: object,
    period_end: object,
    game_theme: object,
) -> None:
    _require_text(scope_name, field_name="scope_name")
    if cadence != "monthly":
        raise AggregationValidationError("cadence must equal monthly")
    _require_natural_month(period_start, period_end)
    if not isinstance(game_theme, str):
        raise AggregationValidationError("game_theme must be a string")


__all__ = [
    "DEFAULT_REPRESENTATIVE_GAME_LIMIT",
    "OPPORTUNITY_DIMENSION_TYPES",
    "REPRESENTATIVE_EVIDENCE_TYPES",
    "OpportunityAggregationResult",
    "ThemeDimensionMonthlyMetric",
    "ThemeGrowthSourceMetric",
    "ThemeMarketStructureMetric",
    "ThemeRepresentativeGame",
]
