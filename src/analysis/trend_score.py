"""Deterministic six-month Game Theme trend and opportunity scoring."""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from math import isfinite
from typing import Any, cast

from .errors import AggregationValidationError
from .models import MonthlyMarketTotal, ThemeMonthlyMetric
from .trend_models import ThemeTrendScore

WINDOW_MONTH_COUNT = 6
RECENT_MONTH_COUNT = 3
MIN_ACTIONABLE_PRODUCT_COUNT = 5
MIN_ACTIONABLE_ACTIVE_MONTHS = 3


@dataclass(frozen=True, slots=True)
class TrendScoreWeights:
    """Named MVP weights for the base score formula."""

    growth: float
    acceleration: float
    new_product: float
    concentration_penalty: float


@dataclass(frozen=True, slots=True)
class ConfidenceWeights:
    """Named MVP weights for the confidence formula."""

    history: float
    size: float
    units_coverage: float
    revenue_coverage: float
    publisher_coverage: float


MVP_TREND_SCORE_WEIGHTS = TrendScoreWeights(
    growth=0.45,
    acceleration=0.30,
    new_product=0.25,
    concentration_penalty=0.20,
)
MVP_CONFIDENCE_WEIGHTS = ConfidenceWeights(
    history=0.25,
    size=0.25,
    units_coverage=0.20,
    revenue_coverage=0.20,
    publisher_coverage=0.10,
)


@dataclass(frozen=True, slots=True)
class _ThemeMonth:
    """A theme's observed or zero-filled value for one calendar month."""

    metric: ThemeMonthlyMetric | None
    product_count: int
    product_share: float
    units_absolute_share: float | None
    revenue_absolute_share: float | None
    new_entry_share: float | None
    median_rank: float | None
    publisher_count: int | None
    publisher_coverage_count: int | None
    units_absolute_coverage_count: int
    revenue_absolute_coverage_count: int


def calculate_theme_trend_scores(
    monthly_totals: Sequence[MonthlyMarketTotal],
    theme_metrics: Sequence[ThemeMonthlyMetric],
    *,
    calculated_at: datetime,
) -> tuple[ThemeTrendScore, ...]:
    """Calculate all six-month target rows from schema-v2 internal models.

    The function intentionally accepts only the two schema-v2 analytical model
    types. It has no database, HTTP, or Sensor Tower dependency. Every target
    month is scored independently; percentile ranks never cross target-month
    boundaries.
    """

    _require_timestamp(calculated_at)
    totals = _validate_totals(monthly_totals)
    metrics = _validate_metrics(theme_metrics, totals)
    totals_by_scope = _group_totals(totals)
    metrics_by_key = {
        _metric_key(metric): metric
        for metric in metrics
    }

    scores: list[ThemeTrendScore] = []
    for scope_name, scope_totals in sorted(totals_by_scope.items()):
        ordered_totals = sorted(scope_totals, key=lambda row: row.period_start)
        _require_contiguous_history(ordered_totals)
        if len(ordered_totals) < WINDOW_MONTH_COUNT:
            raise AggregationValidationError(
                "at least six consecutive monthly totals are required for trend scoring"
            )

        for target_index in range(WINDOW_MONTH_COUNT - 1, len(ordered_totals)):
            window_totals = ordered_totals[
                target_index - WINDOW_MONTH_COUNT + 1 : target_index + 1
            ]
            target_total = window_totals[-1]
            target_metrics = [
                metric
                for metric in metrics
                if metric.scope_name == scope_name
                and metric.period_start == target_total.period_start
                and metric.period_end == target_total.period_end
            ]
            if not target_metrics:
                continue
            scores.extend(
                _score_target_month(
                    window_totals,
                    target_metrics,
                    metrics_by_key,
                    calculated_at=calculated_at,
                )
            )

    return tuple(
        sorted(
            scores,
            key=lambda row: (
                row.scope_name,
                row.period_start,
                row.trend_rank is None,
                row.trend_rank if row.trend_rank is not None else 0,
                row.game_theme,
            ),
        )
    )


def calculate_trend_scores(
    monthly_totals: Sequence[MonthlyMarketTotal],
    theme_metrics: Sequence[ThemeMonthlyMetric],
    *,
    calculated_at: datetime,
) -> tuple[ThemeTrendScore, ...]:
    """Compatibility alias for callers that use the shorter operation name."""

    return calculate_theme_trend_scores(
        monthly_totals,
        theme_metrics,
        calculated_at=calculated_at,
    )


def _score_target_month(
    window_totals: Sequence[MonthlyMarketTotal],
    target_metrics: Sequence[ThemeMonthlyMetric],
    metrics_by_key: Mapping[tuple[str, date, date, str], ThemeMonthlyMetric],
    *,
    calculated_at: datetime,
) -> list[ThemeTrendScore]:
    drafts: list[dict[str, object]] = []

    for target_metric in sorted(target_metrics, key=lambda row: row.game_theme):
        theme_months = [
            _theme_month(
                total,
                metrics_by_key.get(
                    (
                        target_metric.scope_name,
                        total.period_start,
                        total.period_end,
                        target_metric.game_theme,
                    )
                ),
            )
            for total in window_totals
        ]
        raw_values = _build_raw_values(theme_months)
        exclusion_reason = _exclusion_reason(target_metric.game_theme, raw_values)
        draft: dict[str, object] = {
            "scope_name": target_metric.scope_name,
            "cadence": target_metric.cadence,
            "period_start": target_metric.period_start,
            "period_end": target_metric.period_end,
            "game_theme": target_metric.game_theme,
            "window_start": window_totals[0].period_start,
            "window_month_count": WINDOW_MONTH_COUNT,
            "active_months_6m": raw_values["active_months_6m"],
            "latest_product_count": raw_values["latest_product_count"],
            "is_actionable": exclusion_reason is None,
            "exclusion_reason": exclusion_reason,
            "latest_product_share": raw_values["latest_product_share"],
            "latest_units_absolute_share": raw_values["latest_units_absolute_share"],
            "latest_revenue_absolute_share": raw_values["latest_revenue_absolute_share"],
            "latest_new_entry_share": raw_values["latest_new_entry_share"],
            "latest_median_rank": raw_values["latest_median_rank"],
            "latest_publisher_count": raw_values["latest_publisher_count"],
            "latest_top_publisher_product_share": raw_values[
                "latest_top_publisher_product_share"
            ],
            "product_share_gain_3m": raw_values["product_share_gain_3m"],
            "units_absolute_share_gain_3m": raw_values["units_absolute_share_gain_3m"],
            "revenue_absolute_share_gain_3m": raw_values["revenue_absolute_share_gain_3m"],
            "product_share_acceleration": raw_values["product_share_acceleration"],
            "units_absolute_share_acceleration": raw_values[
                "units_absolute_share_acceleration"
            ],
            "revenue_absolute_share_acceleration": raw_values[
                "revenue_absolute_share_acceleration"
            ],
            "recent3_new_entry_share": raw_values["recent3_new_entry_share"],
            "median_rank_improvement": raw_values["median_rank_improvement"],
            "publisher_count_gain_3m": raw_values["publisher_count_gain_3m"],
            "units_absolute_overindex": raw_values["units_absolute_overindex"],
            "revenue_absolute_overindex": raw_values["revenue_absolute_overindex"],
            "recent3_units_coverage_ratio": raw_values["recent3_units_coverage_ratio"],
            "recent3_revenue_coverage_ratio": raw_values["recent3_revenue_coverage_ratio"],
            "latest_publisher_coverage_ratio": raw_values[
                "latest_publisher_coverage_ratio"
            ],
            "growth_score": None,
            "acceleration_score": None,
            "new_product_score": None,
            "concentration_penalty": None,
            "base_trend_score": None,
            "confidence_score": _confidence_score(raw_values),
            "trend_score": None,
            "trend_rank": None,
            "calculated_at": calculated_at,
        }
        drafts.append(draft)

    actionable_drafts = [draft for draft in drafts if bool(draft["is_actionable"])]
    percentiles = {
        feature: _feature_percentiles(actionable_drafts, feature)
        for feature in (
            "product_share_gain_3m",
            "units_absolute_share_gain_3m",
            "revenue_absolute_share_gain_3m",
            "product_share_acceleration",
            "units_absolute_share_acceleration",
            "revenue_absolute_share_acceleration",
            "recent3_new_entry_share",
            "latest_product_share",
            "latest_top_publisher_product_share",
        )
    }

    for draft in actionable_drafts:
        draft_id = id(draft)
        growth_score = _average_available(
            _lookup_percentile(percentiles, "product_share_gain_3m", draft_id),
            _lookup_percentile(percentiles, "units_absolute_share_gain_3m", draft_id),
            _lookup_percentile(percentiles, "revenue_absolute_share_gain_3m", draft_id),
        )
        acceleration_score = _average_available(
            _lookup_percentile(percentiles, "product_share_acceleration", draft_id),
            _lookup_percentile(
                percentiles,
                "units_absolute_share_acceleration",
                draft_id,
            ),
            _lookup_percentile(
                percentiles,
                "revenue_absolute_share_acceleration",
                draft_id,
            ),
        )
        new_product_score = _lookup_percentile(
            percentiles,
            "recent3_new_entry_share",
            draft_id,
        )
        product_concentration = _lookup_percentile(
            percentiles,
            "latest_product_share",
            draft_id,
        )
        publisher_concentration = _lookup_percentile(
            percentiles,
            "latest_top_publisher_product_share",
            draft_id,
        )
        concentration_penalty = _average_available(
            product_concentration,
            publisher_concentration,
        )
        if (
            growth_score is None
            or acceleration_score is None
            or new_product_score is None
            or concentration_penalty is None
        ):
            raise AggregationValidationError(
                "actionable theme is missing a required score component"
            )
        base_trend_score = _clip(
            MVP_TREND_SCORE_WEIGHTS.growth * growth_score
            + MVP_TREND_SCORE_WEIGHTS.acceleration * acceleration_score
            + MVP_TREND_SCORE_WEIGHTS.new_product * new_product_score
            - MVP_TREND_SCORE_WEIGHTS.concentration_penalty * concentration_penalty,
            0.0,
            100.0,
        )
        trend_score = base_trend_score * float(cast(float, draft["confidence_score"])) / 100.0
        draft.update(
            {
                "growth_score": growth_score,
                "acceleration_score": acceleration_score,
                "new_product_score": new_product_score,
                "concentration_penalty": concentration_penalty,
                "base_trend_score": base_trend_score,
                "trend_score": trend_score,
            }
        )

    actionable_drafts.sort(
        key=lambda draft: (
            -float(cast(float, draft["trend_score"])),
            -float(cast(float, draft["base_trend_score"])),
            -float(cast(float, draft["confidence_score"])),
            str(draft["game_theme"]),
        )
    )
    for rank, draft in enumerate(actionable_drafts, start=1):
        draft["trend_rank"] = rank

    return [
        ThemeTrendScore(**cast(Any, draft))
        for draft in drafts
    ]


def _build_raw_values(theme_months: Sequence[_ThemeMonth]) -> dict[str, object]:
    recent = theme_months[-RECENT_MONTH_COUNT:]
    prior = theme_months[:RECENT_MONTH_COUNT]
    latest = theme_months[-1]

    product_recent_average = _complete_average(row.product_share for row in recent)
    product_prior_average = _complete_average(row.product_share for row in prior)
    units_recent_average = _complete_average(row.units_absolute_share for row in recent)
    units_prior_average = _complete_average(row.units_absolute_share for row in prior)
    revenue_recent_average = _complete_average(row.revenue_absolute_share for row in recent)
    revenue_prior_average = _complete_average(row.revenue_absolute_share for row in prior)

    product_recent_slope = _slope(recent[0].product_share, recent[-1].product_share)
    product_prior_slope = _slope(prior[0].product_share, prior[-1].product_share)
    units_recent_slope = _slope(recent[0].units_absolute_share, recent[-1].units_absolute_share)
    units_prior_slope = _slope(prior[0].units_absolute_share, prior[-1].units_absolute_share)
    revenue_recent_slope = _slope(
        recent[0].revenue_absolute_share,
        recent[-1].revenue_absolute_share,
    )
    revenue_prior_slope = _slope(
        prior[0].revenue_absolute_share,
        prior[-1].revenue_absolute_share,
    )

    latest_metric = latest.metric
    if latest_metric is None:
        raise AggregationValidationError("target theme metric is missing")

    return {
        "active_months_6m": sum(row.metric is not None for row in theme_months),
        "latest_product_count": latest.product_count,
        "latest_product_share": latest.product_share,
        "latest_units_absolute_share": latest.units_absolute_share,
        "latest_revenue_absolute_share": latest.revenue_absolute_share,
        "latest_new_entry_share": latest.new_entry_share,
        "latest_median_rank": latest.median_rank,
        "latest_publisher_count": latest.publisher_count,
        "latest_top_publisher_product_share": (
            latest_metric.top_publisher_product_share
        ),
        "product_share_gain_3m": _difference(product_recent_average, product_prior_average),
        "units_absolute_share_gain_3m": _difference(
            units_recent_average,
            units_prior_average,
        ),
        "revenue_absolute_share_gain_3m": _difference(
            revenue_recent_average,
            revenue_prior_average,
        ),
        "product_share_acceleration": _difference(product_recent_slope, product_prior_slope),
        "units_absolute_share_acceleration": _difference(
            units_recent_slope,
            units_prior_slope,
        ),
        "revenue_absolute_share_acceleration": _difference(
            revenue_recent_slope,
            revenue_prior_slope,
        ),
        "recent3_new_entry_share": _complete_average(row.new_entry_share for row in recent),
        "median_rank_improvement": _difference(
            _active_average(row.median_rank for row in prior),
            _active_average(row.median_rank for row in recent),
        ),
        "publisher_count_gain_3m": _difference(
            _active_average(row.publisher_count for row in recent),
            _active_average(row.publisher_count for row in prior),
        ),
        "units_absolute_overindex": _overindex(
            latest.units_absolute_share,
            latest.product_share,
        ),
        "revenue_absolute_overindex": _overindex(
            latest.revenue_absolute_share,
            latest.product_share,
        ),
        "recent3_units_coverage_ratio": _coverage_ratio(
            recent,
            metric_name="units_absolute_coverage_count",
        ),
        "recent3_revenue_coverage_ratio": _coverage_ratio(
            recent,
            metric_name="revenue_absolute_coverage_count",
        ),
        "latest_publisher_coverage_ratio": (
            int(latest.publisher_coverage_count or 0) / latest.product_count
            if latest.product_count
            else 0.0
        ),
    }


def _theme_month(
    total: MonthlyMarketTotal,
    metric: ThemeMonthlyMetric | None,
) -> _ThemeMonth:
    if metric is None:
        return _ThemeMonth(
            metric=None,
            product_count=0,
            product_share=0.0,
            units_absolute_share=(
                0.0 if _has_denominator(total.units_absolute_sum) else None
            ),
            revenue_absolute_share=(
                0.0 if _has_denominator(total.revenue_absolute_sum) else None
            ),
            new_entry_share=0.0,
            median_rank=None,
            publisher_count=None,
            publisher_coverage_count=None,
            units_absolute_coverage_count=0,
            revenue_absolute_coverage_count=0,
        )
    if metric.period_key != (
        total.scope_name,
        total.cadence,
        total.period_start,
        total.period_end,
    ):
        raise AggregationValidationError("theme metric and monthly total identities differ")
    return _ThemeMonth(
        metric=metric,
        product_count=metric.product_count,
        product_share=metric.product_share,
        units_absolute_share=metric.units_absolute_share,
        revenue_absolute_share=metric.revenue_absolute_share,
        new_entry_share=metric.new_entry_share,
        median_rank=metric.median_rank,
        publisher_count=metric.publisher_count,
        publisher_coverage_count=metric.publisher_coverage_count,
        units_absolute_coverage_count=metric.units_absolute_coverage_count,
        revenue_absolute_coverage_count=metric.revenue_absolute_coverage_count,
    )


def _exclusion_reason(theme: str, raw_values: Mapping[str, object]) -> str | None:
    if theme in {"", "Unknown", "N/A"}:
        return "non_actionable_source_label"
    if int(cast(int, raw_values["latest_product_count"])) < MIN_ACTIONABLE_PRODUCT_COUNT:
        return "insufficient_latest_product_count"
    if int(cast(int, raw_values["active_months_6m"])) < MIN_ACTIONABLE_ACTIVE_MONTHS:
        return "insufficient_active_history"
    if raw_values["latest_product_share"] is None or raw_values["recent3_new_entry_share"] is None:
        return "insufficient_metric_coverage"
    return None


def _confidence_score(raw_values: Mapping[str, object]) -> float:
    history_confidence = (
        int(cast(int, raw_values["active_months_6m"])) / WINDOW_MONTH_COUNT
    )
    size_confidence = min(int(cast(int, raw_values["latest_product_count"])) / 20.0, 1.0)
    return 100.0 * (
        MVP_CONFIDENCE_WEIGHTS.history * history_confidence
        + MVP_CONFIDENCE_WEIGHTS.size * size_confidence
        + MVP_CONFIDENCE_WEIGHTS.units_coverage
        * float(cast(float, raw_values["recent3_units_coverage_ratio"]))
        + MVP_CONFIDENCE_WEIGHTS.revenue_coverage
        * float(cast(float, raw_values["recent3_revenue_coverage_ratio"]))
        + MVP_CONFIDENCE_WEIGHTS.publisher_coverage
        * float(cast(float, raw_values["latest_publisher_coverage_ratio"]))
    )


def _feature_percentiles(
    drafts: Sequence[Mapping[str, object]],
    feature: str,
) -> dict[int, float]:
    values: list[tuple[int, float]] = []
    for draft in drafts:
        value = draft[feature]
        if value is not None:
            values.append((id(draft), float(cast(float, value))))
    values.sort(key=lambda item: (item[1], item[0]))
    if not values:
        return {}

    percentiles: dict[int, float] = {}
    index = 0
    count = len(values)
    while index < count:
        end = index + 1
        while end < count and values[end][1] == values[index][1]:
            end += 1
        average_rank = ((index + 1) + end) / 2.0
        percentile = 50.0 if count == 1 else 100.0 * (average_rank - 1.0) / (count - 1)
        for tied_index in range(index, end):
            percentiles[values[tied_index][0]] = percentile
        index = end
    return percentiles


def _lookup_percentile(
    percentiles: Mapping[str, Mapping[int, float]],
    feature: str,
    draft_id: int,
) -> float | None:
    return percentiles[feature].get(draft_id)


def _average_available(*values: float | None) -> float | None:
    available = [value for value in values if value is not None]
    return sum(available) / len(available) if available else None


def _complete_average(values: Sequence[float | None] | Any) -> float | None:
    materialized = list(values)
    if not materialized or any(value is None for value in materialized):
        return None
    return sum(float(cast(float, value)) for value in materialized) / len(materialized)


def _active_average(values: Sequence[float | int | None] | Any) -> float | None:
    available = [float(value) for value in values if value is not None]
    return sum(available) / len(available) if available else None


def _slope(first: float | None, last: float | None) -> float | None:
    if first is None or last is None:
        return None
    return (last - first) / 2.0


def _difference(first: float | None, second: float | None) -> float | None:
    if first is None or second is None:
        return None
    return first - second


def _overindex(share: float | None, product_share: float) -> float | None:
    if share is None or product_share == 0:
        return None
    return share / product_share


def _coverage_ratio(
    theme_months: Sequence[_ThemeMonth],
    *,
    metric_name: str,
) -> float:
    product_count = sum(row.product_count for row in theme_months)
    coverage_count = sum(int(getattr(row, metric_name)) for row in theme_months)
    return coverage_count / product_count if product_count else 0.0


def _has_denominator(value: float | None) -> bool:
    return value is not None and value != 0


def _require_timestamp(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AggregationValidationError("calculated_at must be timezone-aware")


def _validate_totals(
    rows: Sequence[MonthlyMarketTotal],
) -> tuple[MonthlyMarketTotal, ...]:
    values = tuple(rows)
    if not values:
        raise AggregationValidationError("at least one monthly total is required")
    if any(not isinstance(row, MonthlyMarketTotal) for row in values):
        raise AggregationValidationError("monthly totals must be MonthlyMarketTotal values")
    try:
        values = tuple(replace(row) for row in values)
    except Exception as error:
        raise AggregationValidationError("monthly totals failed validation") from error
    keys = [_total_key(row) for row in values]
    if len(set(keys)) != len(keys):
        raise AggregationValidationError("monthly totals must have unique identities")
    if any(not _is_natural_month(row.period_start, row.period_end) for row in values):
        raise AggregationValidationError("monthly totals must use natural calendar months")
    return values


def _validate_metrics(
    rows: Sequence[ThemeMonthlyMetric],
    totals: Sequence[MonthlyMarketTotal],
) -> tuple[ThemeMonthlyMetric, ...]:
    values = tuple(rows)
    if any(not isinstance(row, ThemeMonthlyMetric) for row in values):
        raise AggregationValidationError("theme metrics must be ThemeMonthlyMetric values")
    try:
        values = tuple(replace(row) for row in values)
    except Exception as error:
        raise AggregationValidationError("theme metrics failed validation") from error
    total_keys = {_total_key(row) for row in totals}
    metric_keys = [_metric_key(row) for row in values]
    if len(set(metric_keys)) != len(metric_keys):
        raise AggregationValidationError("theme metrics must have unique identities")
    if any(key[:3] not in total_keys for key in metric_keys):
        raise AggregationValidationError("theme metrics must belong to monthly totals")
    return values


def _group_totals(
    totals: Sequence[MonthlyMarketTotal],
) -> dict[str, list[MonthlyMarketTotal]]:
    grouped: dict[str, list[MonthlyMarketTotal]] = defaultdict(list)
    for row in totals:
        grouped[row.scope_name].append(row)
    return grouped


def _require_contiguous_history(rows: Sequence[MonthlyMarketTotal]) -> None:
    ordered = sorted(rows, key=lambda row: row.period_start)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        expected_start = _month_shift(previous.period_start, 1)
        if current.period_start != expected_start:
            raise AggregationValidationError(
                "monthly totals contain a missing calendar month; scoring cannot zero-fill it"
            )


def _total_key(row: MonthlyMarketTotal) -> tuple[str, date, date]:
    return (row.scope_name, row.period_start, row.period_end)


def _metric_key(row: ThemeMonthlyMetric) -> tuple[str, date, date, str]:
    return (row.scope_name, row.period_start, row.period_end, row.game_theme)


def _month_shift(month_start: date, offset: int) -> date:
    month_index = month_start.year * 12 + month_start.month - 1 + offset
    year, month_zero_based = divmod(month_index, 12)
    return date(year, month_zero_based + 1, 1)


def _is_natural_month(period_start: date, period_end: date) -> bool:
    return (
        period_start.day == 1
        and period_end
        == date(
            period_start.year,
            period_start.month,
            calendar.monthrange(period_start.year, period_start.month)[1],
        )
    )


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _is_finite(value: float) -> bool:
    return isfinite(value)


__all__ = [
    "ConfidenceWeights",
    "MVP_CONFIDENCE_WEIGHTS",
    "MVP_TREND_SCORE_WEIGHTS",
    "MIN_ACTIONABLE_ACTIVE_MONTHS",
    "MIN_ACTIONABLE_PRODUCT_COUNT",
    "RECENT_MONTH_COUNT",
    "TrendScoreWeights",
    "WINDOW_MONTH_COUNT",
    "calculate_theme_trend_scores",
    "calculate_trend_scores",
]
