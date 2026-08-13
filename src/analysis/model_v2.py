"""Pure MODEL-002 multi-horizon trend, lifecycle, and seasonality evidence."""

from __future__ import annotations

import calendar
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isclose
from statistics import mean, median, pstdev
from typing import TYPE_CHECKING

from .errors import AggregationValidationError
from .model_v2_models import (
    HORIZON_METRIC_NAMES,
    HORIZON_MONTH_COUNTS,
    MODEL_POLICY_VERSION,
    SHARE_METRIC_NAMES,
    ThemeHorizonMetric,
    ThemeModelResult,
    ThemeModelSummary,
    ThemeSeasonalityProfile,
)
from .models import MonthlyMarketTotal

if TYPE_CHECKING:
    from .opportunity_models import ThemeMarketStructureMetric

# These are provisional interpretive policy values.  They are not investment
# weights, recommendation thresholds, or forecasts, and remain subject to
# BACKTEST-001 validation.
DIRECTION_NORMALIZED_SLOPE_THRESHOLD = 0.005
DIRECTION_MIN_R_SQUARED = 0.20
STABILITY_STABLE_CV_MAX = 0.15
STABILITY_VARIABLE_CV_MAX = 0.35
ACCELERATION_NORMALIZED_SLOPE_MARGIN = 0.005

SEASONALITY_MIN_HISTORY_MONTHS = 24
SEASONALITY_MAX_HISTORY_MONTHS = 36


@dataclass(frozen=True, slots=True)
class _HistoryMonth:
    total: MonthlyMarketTotal
    structures: Mapping[str, ThemeMarketStructureMetric]


def calculate_theme_model_metrics(
    monthly_market_totals: Sequence[MonthlyMarketTotal],
    theme_market_structure_metrics: Sequence[ThemeMarketStructureMetric],
    calculated_at: datetime,
) -> ThemeModelResult:
    """Calculate leakage-safe MODEL-002 rows from normalized AGG-002 rows.

    The supplied month sequence is the available completed history.  Every
    summary target uses only its prefix of that sequence; later months are
    never consulted when building an earlier target's horizon or seasonality
    evidence.
    """

    _require_timestamp(calculated_at, field_name="calculated_at")
    totals = _validate_totals(monthly_market_totals)
    structures = _validate_structures(theme_market_structure_metrics, totals)
    history = tuple(
        _HistoryMonth(total=total, structures=structures.get(_total_key(total), {}))
        for total in totals
    )

    horizon_rows: list[ThemeHorizonMetric] = []
    summary_rows: list[ThemeModelSummary] = []
    seasonality_rows: list[ThemeSeasonalityProfile] = []

    for target_index, target_month in enumerate(history):
        target_themes = tuple(sorted(target_month.structures))
        for game_theme in target_themes:
            prefix = history[: target_index + 1]
            values_by_metric = {
                metric_name: tuple(
                    _value_for_theme(month.structures.get(game_theme), metric_name)
                    for month in prefix
                )
                for metric_name in HORIZON_METRIC_NAMES
            }
            horizon_by_count: dict[int, dict[str, ThemeHorizonMetric]] = {}
            for horizon in HORIZON_MONTH_COUNTS:
                if len(prefix) < horizon:
                    continue
                window_start = prefix[-horizon].total.period_start
                rows_for_horizon: dict[str, ThemeHorizonMetric] = {}
                active_month_count = sum(
                    value is not None and value > 0
                    for value in values_by_metric["product_count"][-horizon:]
                )
                for metric_name in HORIZON_METRIC_NAMES:
                    row = _build_horizon_metric(
                        scope_name=target_month.total.scope_name,
                        period_start=target_month.total.period_start,
                        period_end=target_month.total.period_end,
                        game_theme=game_theme,
                        horizon=horizon,
                        metric_name=metric_name,
                        window_start=window_start,
                        values=values_by_metric[metric_name][-horizon:],
                        active_month_count=active_month_count,
                        calculated_at=calculated_at,
                    )
                    rows_for_horizon[metric_name] = row
                    horizon_rows.append(row)
                horizon_by_count[horizon] = rows_for_horizon

            profiles, seasonality_history_count, complete_year_count = _build_seasonality_profiles(
                scope_name=target_month.total.scope_name,
                period_start=target_month.total.period_start,
                period_end=target_month.total.period_end,
                game_theme=game_theme,
                prefix=prefix,
                values_by_metric=values_by_metric,
                calculated_at=calculated_at,
            )
            seasonality_rows.extend(profiles)

            first_active_index = _first_active_index(values_by_metric["product_count"])
            active_months_to_date = sum(
                value is not None and value > 0
                for value in values_by_metric["product_count"]
            )
            first_active_month = (
                prefix[first_active_index].total.period_start
                if first_active_index is not None
                else None
            )
            first_active_left_censored = first_active_index == 0

            direction_evidence: dict[int, tuple[str, int, float | None, float | None, str]] = {}
            for horizon in HORIZON_MONTH_COUNTS:
                direction_evidence[horizon] = _summarize_horizon_evidence(
                    horizon_by_count.get(horizon)
                )

            summary = _build_summary(
                target_month=target_month.total,
                game_theme=game_theme,
                history_start=prefix[0].total.period_start,
                history_month_count=len(prefix),
                first_active_month=first_active_month,
                first_active_left_censored=first_active_left_censored,
                months_since_first_active=(
                    target_index - first_active_index
                    if first_active_index is not None
                    else None
                ),
                active_months_to_date=active_months_to_date,
                horizon_by_count=horizon_by_count,
                direction_evidence=direction_evidence,
                seasonality_profiles=profiles,
                seasonality_history_count=seasonality_history_count,
                complete_year_count=complete_year_count,
                calculated_at=calculated_at,
            )
            summary_rows.append(summary)

    return ThemeModelResult(
        horizon_metrics=tuple(horizon_rows),
        model_summaries=tuple(summary_rows),
        seasonality_profiles=tuple(seasonality_rows),
    )


def _validate_totals(rows: Sequence[MonthlyMarketTotal]) -> tuple[MonthlyMarketTotal, ...]:
    values = tuple(rows)
    if not values:
        raise AggregationValidationError("MODEL-002 history must contain monthly totals")
    if any(not isinstance(row, MonthlyMarketTotal) for row in values):
        raise AggregationValidationError("MODEL-002 totals must be MonthlyMarketTotal values")
    ordered = tuple(sorted(values, key=_total_sort_key))
    first = ordered[0]
    scope_name = first.scope_name
    for row in ordered:
        _require_natural_month(row.period_start, row.period_end, field_name="period")
        if row.scope_name != scope_name or row.cadence != "monthly":
            raise AggregationValidationError("MODEL-002 history must use one monthly scope")
    identities = [_total_key(row) for row in ordered]
    if len(set(identities)) != len(identities):
        raise AggregationValidationError("MODEL-002 totals must have unique period identities")
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current.period_start != _month_shift(previous.period_start, 1):
            raise AggregationValidationError(
                "MODEL-002 history must be consecutive calendar months"
            )
    return ordered


def _validate_structures(
    rows: Sequence[ThemeMarketStructureMetric],
    totals: Sequence[MonthlyMarketTotal],
) -> dict[tuple[str, str, date, date], dict[str, ThemeMarketStructureMetric]]:
    from .opportunity_models import ThemeMarketStructureMetric

    values = tuple(rows)
    if any(not isinstance(row, ThemeMarketStructureMetric) for row in values):
        raise AggregationValidationError(
            "MODEL-002 structure rows must be ThemeMarketStructureMetric values"
        )
    total_keys = {_total_key(row) for row in totals}
    grouped: dict[tuple[str, str, date, date], dict[str, ThemeMarketStructureMetric]] = {}
    identities: set[tuple[str, str, date, date, str]] = set()
    for row in values:
        key = _structure_key(row)
        if key not in total_keys:
            raise AggregationValidationError(
                "MODEL-002 structure row is outside the supplied history"
            )
        identity = (*key, row.game_theme)
        if identity in identities:
            raise AggregationValidationError("MODEL-002 structure rows must have unique identities")
        identities.add(identity)
        grouped.setdefault(key, {})[row.game_theme] = row
    return grouped


def _build_horizon_metric(
    *,
    scope_name: str,
    period_start: date,
    period_end: date,
    game_theme: str,
    horizon: int,
    metric_name: str,
    window_start: date,
    values: Sequence[float | None],
    active_month_count: int,
    calculated_at: datetime,
) -> ThemeHorizonMetric:
    numeric_values = [value for value in values if value is not None]
    coverage = len(numeric_values)
    is_complete = coverage == horizon
    first_value = values[0]
    latest_value = values[-1]
    if numeric_values:
        mean_value: float | None = mean(numeric_values)
        median_value: float | None = median(numeric_values)
        minimum_value: float | None = min(numeric_values)
        maximum_value: float | None = max(numeric_values)
        standard_deviation: float | None = pstdev(numeric_values)
    else:
        mean_value = median_value = minimum_value = maximum_value = standard_deviation = None

    absolute_change: float | None = None
    relative_change: float | None = None
    linear_slope: float | None = None
    normalized_slope: float | None = None
    r_squared: float | None = None
    latest_to_mean_ratio: float | None = None
    coefficient_of_variation: float | None = None
    maximum_drawdown: float | None = None
    months_since_peak: int | None = None
    if is_complete:
        complete_values = [value for value in values if value is not None]
        if len(complete_values) != horizon:
            raise AggregationValidationError("complete horizon contains unavailable metric values")
        if any(value < 0 for value in complete_values):
            raise AggregationValidationError("MODEL-002 metric values must be non-negative")
        assert first_value is not None
        assert latest_value is not None
        assert mean_value is not None
        absolute_change = latest_value - first_value
        if first_value > 0:
            relative_change = absolute_change / first_value
        linear_slope = _linear_slope(complete_values)
        if mean_value > 0:
            normalized_slope = linear_slope / mean_value
            assert standard_deviation is not None
            coefficient_of_variation = standard_deviation / mean_value
            latest_to_mean_ratio = latest_value / mean_value
        r_squared = _r_squared(complete_values)
        maximum_drawdown = _maximum_drawdown(complete_values)
        latest_peak_index = max(
            index for index, value in enumerate(complete_values) if value == max(complete_values)
        )
        months_since_peak = horizon - 1 - latest_peak_index

    transition_count = horizon - 1
    positive_change_count = 0
    negative_change_count = 0
    unchanged_change_count = 0
    for previous, current in zip(values, values[1:], strict=False):
        if previous is None or current is None:
            continue
        if isclose(current, previous, rel_tol=1e-9, abs_tol=1e-12):
            unchanged_change_count += 1
        elif current > previous:
            positive_change_count += 1
        else:
            negative_change_count += 1
    transition_coverage_count = (
        positive_change_count + negative_change_count + unchanged_change_count
    )
    positive_change_ratio = (
        positive_change_count / transition_coverage_count
        if transition_coverage_count > 0
        else None
    )

    return ThemeHorizonMetric(
        scope_name=scope_name,
        cadence="monthly",
        period_start=period_start,
        period_end=period_end,
        game_theme=game_theme,
        horizon_month_count=horizon,
        metric_name=metric_name,
        window_start=window_start,
        expected_month_count=horizon,
        metric_coverage_count=coverage,
        active_month_count=active_month_count,
        is_complete=is_complete,
        first_value=first_value,
        latest_value=latest_value,
        mean_value=mean_value,
        median_value=median_value,
        minimum_value=minimum_value,
        maximum_value=maximum_value,
        absolute_change=absolute_change,
        relative_change=relative_change,
        linear_slope=linear_slope,
        normalized_slope=normalized_slope,
        r_squared=r_squared,
        latest_to_mean_ratio=latest_to_mean_ratio,
        transition_count=transition_count,
        transition_coverage_count=transition_coverage_count,
        positive_change_count=positive_change_count,
        negative_change_count=negative_change_count,
        unchanged_change_count=unchanged_change_count,
        positive_change_ratio=positive_change_ratio,
        standard_deviation=standard_deviation,
        coefficient_of_variation=coefficient_of_variation,
        maximum_drawdown=maximum_drawdown,
        months_since_peak=months_since_peak,
        calculated_at=calculated_at,
    )


def _summarize_horizon_evidence(
    rows: Mapping[str, ThemeHorizonMetric] | None,
) -> tuple[str, int, float | None, float | None, str]:
    """Return direction, direction evidence count, slope/r2 medians, and band."""

    if rows is None:
        return "insufficient_history", 0, None, None, "insufficient_history"

    direction_values: list[str] = []
    slope_values: list[float] = []
    r_squared_values: list[float] = []
    coefficient_values: list[float] = []
    for metric_name in SHARE_METRIC_NAMES:
        row = rows.get(metric_name)
        if row is None or not row.is_complete:
            continue
        if row.normalized_slope is not None:
            slope_values.append(row.normalized_slope)
            if abs(row.normalized_slope) < DIRECTION_NORMALIZED_SLOPE_THRESHOLD:
                direction_values.append("flat")
            elif row.r_squared is None or row.r_squared < DIRECTION_MIN_R_SQUARED:
                # A non-flat but low-fit series is noisy evidence, not a
                # directional vote.
                pass
            elif row.normalized_slope > 0:
                direction_values.append("up")
            else:
                direction_values.append("down")
        if row.r_squared is not None:
            r_squared_values.append(row.r_squared)
        if row.coefficient_of_variation is not None:
            coefficient_values.append(row.coefficient_of_variation)

    direction = _composite_direction(direction_values)
    stability_band = _stability_band(coefficient_values)
    return (
        direction,
        len(direction_values),
        median(slope_values) if slope_values else None,
        median(r_squared_values) if r_squared_values else None,
        stability_band,
    )


def _composite_direction(values: Sequence[str]) -> str:
    if len(values) < 2:
        return "insufficient_history"
    for candidate in ("up", "down", "flat"):
        if values.count(candidate) >= 2:
            return candidate
    return "mixed"


def _stability_band(values: Sequence[float]) -> str:
    if len(values) < 2:
        return "insufficient_history"
    median_cv = median(values)
    if median_cv <= STABILITY_STABLE_CV_MAX:
        return "stable"
    if median_cv <= STABILITY_VARIABLE_CV_MAX:
        return "variable"
    return "volatile"


def _build_summary(
    *,
    target_month: MonthlyMarketTotal,
    game_theme: str,
    history_start: date,
    history_month_count: int,
    first_active_month: date | None,
    first_active_left_censored: bool,
    months_since_first_active: int | None,
    active_months_to_date: int,
    horizon_by_count: Mapping[int, Mapping[str, ThemeHorizonMetric]],
    direction_evidence: Mapping[int, tuple[str, int, float | None, float | None, str]],
    seasonality_profiles: Sequence[ThemeSeasonalityProfile],
    seasonality_history_count: int | None,
    complete_year_count: int | None,
    calculated_at: datetime,
) -> ThemeModelSummary:
    horizon_flags = {horizon: horizon in horizon_by_count for horizon in HORIZON_MONTH_COUNTS}
    active_months = {
        horizon: (
            next(iter(horizon_by_count[horizon].values())).active_month_count
            if horizon_flags[horizon]
            else None
        )
        for horizon in HORIZON_MONTH_COUNTS
    }
    directions = {horizon: direction_evidence[horizon][0] for horizon in HORIZON_MONTH_COUNTS}
    direction_counts = {
        horizon: direction_evidence[horizon][1] for horizon in HORIZON_MONTH_COUNTS
    }
    slope_medians = {
        horizon: direction_evidence[horizon][2] for horizon in HORIZON_MONTH_COUNTS
    }
    r_squared_medians = {
        horizon: direction_evidence[horizon][3] for horizon in HORIZON_MONTH_COUNTS
    }
    stability_bands = {
        horizon: direction_evidence[horizon][4] for horizon in HORIZON_MONTH_COUNTS
    }
    cv_medians = {
        horizon: _median_cv(horizon_by_count.get(horizon))
        for horizon in HORIZON_MONTH_COUNTS
    }
    downloads_seasonality = _seasonality_summary(seasonality_profiles, "downloads_sum")
    revenue_seasonality = _seasonality_summary(seasonality_profiles, "revenue_usd_sum")
    lifecycle_stage = _lifecycle_stage(
        direction_6m=directions[6],
        direction_12m=directions[12],
        median_slope_6m=slope_medians[6],
        median_slope_12m=slope_medians[12],
        first_active_left_censored=first_active_left_censored,
        months_since_first_active=months_since_first_active,
        active_months_12m=active_months[12],
        stability_band_12m=stability_bands[12],
    )
    return ThemeModelSummary(
        scope_name=target_month.scope_name,
        cadence=target_month.cadence,
        period_start=target_month.period_start,
        period_end=target_month.period_end,
        game_theme=game_theme,
        model_policy_version=MODEL_POLICY_VERSION,
        history_start=history_start,
        history_month_count=history_month_count,
        first_active_month=first_active_month,
        first_active_left_censored=first_active_left_censored,
        months_since_first_active=months_since_first_active,
        active_months_to_date=active_months_to_date,
        has_6m_history=horizon_flags[6],
        has_12m_history=horizon_flags[12],
        has_36m_history=horizon_flags[36],
        active_months_6m=active_months[6],
        active_months_12m=active_months[12],
        active_months_36m=active_months[36],
        direction_6m=directions[6],
        direction_12m=directions[12],
        direction_36m=directions[36],
        direction_evidence_count_6m=direction_counts[6],
        direction_evidence_count_12m=direction_counts[12],
        direction_evidence_count_36m=direction_counts[36],
        median_normalized_slope_6m=slope_medians[6],
        median_normalized_slope_12m=slope_medians[12],
        median_normalized_slope_36m=slope_medians[36],
        median_r_squared_6m=r_squared_medians[6],
        median_r_squared_12m=r_squared_medians[12],
        median_r_squared_36m=r_squared_medians[36],
        stability_cv_median_6m=cv_medians[6],
        stability_cv_median_12m=cv_medians[12],
        stability_cv_median_36m=cv_medians[36],
        stability_band_6m=stability_bands[6],
        stability_band_12m=stability_bands[12],
        stability_band_36m=stability_bands[36],
        lifecycle_stage=lifecycle_stage,
        seasonality_history_month_count=seasonality_history_count,
        seasonality_complete_year_count=complete_year_count,
        downloads_peak_calendar_month=downloads_seasonality[0],
        downloads_trough_calendar_month=downloads_seasonality[1],
        downloads_seasonality_amplitude=downloads_seasonality[2],
        revenue_usd_peak_calendar_month=revenue_seasonality[0],
        revenue_usd_trough_calendar_month=revenue_seasonality[1],
        revenue_usd_seasonality_amplitude=revenue_seasonality[2],
        calculated_at=calculated_at,
    )


def _lifecycle_stage(
    *,
    direction_6m: str,
    direction_12m: str,
    median_slope_6m: float | None,
    median_slope_12m: float | None,
    first_active_left_censored: bool,
    months_since_first_active: int | None,
    active_months_12m: int | None,
    stability_band_12m: str,
) -> str:
    if direction_12m == "insufficient_history":
        return "insufficient_history"
    if (
        not first_active_left_censored
        and months_since_first_active is not None
        and months_since_first_active < 12
        and direction_6m == "up"
    ):
        return "emerging"
    if (
        direction_6m == "up"
        and direction_12m == "up"
        and median_slope_6m is not None
        and median_slope_12m is not None
        and median_slope_6m >= median_slope_12m + ACCELERATION_NORMALIZED_SLOPE_MARGIN
    ):
        return "accelerating"
    if direction_6m == "up" and direction_12m in {"down", "flat", "mixed"}:
        return "recovering"
    if direction_12m == "down" and direction_6m != "up":
        return "declining"
    if (
        direction_12m == "flat"
        and active_months_12m == 12
        and stability_band_12m in {"stable", "variable"}
    ):
        return "mature"
    if direction_12m == "up":
        return "growing"
    return "mixed"


def _build_seasonality_profiles(
    *,
    scope_name: str,
    period_start: date,
    period_end: date,
    game_theme: str,
    prefix: Sequence[_HistoryMonth],
    values_by_metric: Mapping[str, Sequence[float | None]],
    calculated_at: datetime,
) -> tuple[tuple[ThemeSeasonalityProfile, ...], int | None, int | None]:
    available_months = len(prefix)
    if available_months < SEASONALITY_MIN_HISTORY_MONTHS:
        return (), None, None
    history_month_count = min(
        SEASONALITY_MAX_HISTORY_MONTHS,
        (available_months // 12) * 12,
    )
    if history_month_count < SEASONALITY_MIN_HISTORY_MONTHS:
        return (), None, None
    selected_prefix = prefix[-history_month_count:]
    selected_values = {
        metric_name: tuple(values_by_metric[metric_name][-history_month_count:])
        for metric_name in HORIZON_METRIC_NAMES
    }
    complete_year_count = history_month_count // 12
    profiles: list[ThemeSeasonalityProfile] = []
    for metric_name in HORIZON_METRIC_NAMES:
        blocks: list[tuple[tuple[date, float], ...]] = []
        for block_start in range(0, history_month_count, 12):
            block_values = selected_values[metric_name][block_start : block_start + 12]
            if any(value is None for value in block_values):
                continue
            numeric_values = tuple(value for value in block_values if value is not None)
            if any(value < 0 for value in numeric_values):
                raise AggregationValidationError("seasonality metric values must be non-negative")
            block_mean = mean(numeric_values)
            if block_mean <= 0:
                continue
            blocks.append(
                tuple(
                    (
                        selected_prefix[block_start + month_offset].total.period_start,
                        value / block_mean,
                    )
                    for month_offset, value in enumerate(numeric_values)
                )
            )
        if len(blocks) < 2:
            continue
        by_calendar_month: dict[int, list[float]] = {month: [] for month in range(1, 13)}
        for block in blocks:
            for month_start, normalized_value in block:
                by_calendar_month[month_start.month].append(normalized_value)
        seasonal_indices = {
            month: mean(values)
            for month, values in by_calendar_month.items()
            if values
        }
        if set(seasonal_indices) != set(range(1, 13)):
            continue
        if not isclose(mean(tuple(seasonal_indices.values())), 1.0, rel_tol=1e-9, abs_tol=1e-9):
            raise AggregationValidationError("seasonality indices must average approximately one")
        peak_month = min(seasonal_indices, key=lambda month: (-seasonal_indices[month], month))
        trough_month = min(seasonal_indices, key=lambda month: (seasonal_indices[month], month))
        history_start = selected_prefix[0].total.period_start
        for calendar_month_number in range(1, 13):
            seasonal_index = seasonal_indices[calendar_month_number]
            profiles.append(
                ThemeSeasonalityProfile(
                    scope_name=scope_name,
                    cadence="monthly",
                    period_start=period_start,
                    period_end=period_end,
                    game_theme=game_theme,
                    metric_name=metric_name,
                    calendar_month=calendar_month_number,
                    history_start=history_start,
                    history_month_count=history_month_count,
                    complete_year_count=len(blocks),
                    observation_count=len(blocks),
                    seasonal_index=seasonal_index,
                    index_deviation=seasonal_index - 1,
                    is_peak_month=calendar_month_number == peak_month,
                    is_trough_month=calendar_month_number == trough_month,
                    calculated_at=calculated_at,
                )
            )
    return tuple(profiles), history_month_count, complete_year_count


def _seasonality_summary(
    profiles: Sequence[ThemeSeasonalityProfile],
    metric_name: str,
) -> tuple[int | None, int | None, float | None]:
    rows = [row for row in profiles if row.metric_name == metric_name]
    if len(rows) != 12:
        return None, None, None
    peak_rows = [row for row in rows if row.is_peak_month]
    trough_rows = [row for row in rows if row.is_trough_month]
    if len(peak_rows) != 1 or len(trough_rows) != 1:
        raise AggregationValidationError("seasonality profile must have one peak and one trough")
    values = [row.seasonal_index for row in rows]
    return peak_rows[0].calendar_month, trough_rows[0].calendar_month, max(values) - min(values)


def _median_cv(rows: Mapping[str, ThemeHorizonMetric] | None) -> float | None:
    if rows is None:
        return None
    values = [
        row.coefficient_of_variation
        for metric_name in SHARE_METRIC_NAMES
        if (row := rows.get(metric_name)) is not None
        and row.is_complete
        and row.coefficient_of_variation is not None
    ]
    return median(values) if values else None


def _first_active_index(values: Sequence[float | None]) -> int | None:
    for index, value in enumerate(values):
        if value is not None and value > 0:
            return index
    return None


def _value_for_theme(
    row: ThemeMarketStructureMetric | None,
    metric_name: str,
) -> float | None:
    if row is None:
        return 0.0
    if metric_name == "product_count":
        return float(row.product_count)
    if metric_name == "product_share":
        return row.product_share
    if metric_name == "downloads_sum":
        return row.downloads_sum
    if metric_name == "downloads_share":
        return row.downloads_share
    if metric_name == "revenue_usd_sum":
        return row.revenue_usd_sum
    if metric_name == "revenue_usd_share":
        return row.revenue_usd_share
    raise AggregationValidationError("MODEL-002 metric name is not supported")


def _linear_slope(values: Sequence[float]) -> float:
    if not values:
        raise AggregationValidationError("OLS requires at least one value")
    x_mean = (len(values) - 1) / 2
    y_mean = mean(values)
    denominator = sum((index - x_mean) ** 2 for index in range(len(values)))
    if denominator == 0:
        return 0.0
    return (
        sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values))
        / denominator
    )


def _r_squared(values: Sequence[float]) -> float | None:
    y_mean = mean(values)
    total_sum_squares = sum((value - y_mean) ** 2 for value in values)
    if total_sum_squares == 0:
        return None
    slope = _linear_slope(values)
    intercept = y_mean - slope * (len(values) - 1) / 2
    residual_sum_squares = sum(
        (value - (intercept + slope * index)) ** 2
        for index, value in enumerate(values)
    )
    return 1 - residual_sum_squares / total_sum_squares


def _maximum_drawdown(values: Sequence[float]) -> float:
    if all(value == 0 for value in values):
        return 0.0
    running_peak = 0.0
    maximum = 0.0
    for value in values:
        running_peak = max(running_peak, value)
        if running_peak > 0:
            maximum = max(maximum, (running_peak - value) / running_peak)
    return max(0.0, min(1.0, maximum))


def _total_sort_key(row: MonthlyMarketTotal) -> tuple[str, date, date, str]:
    return row.scope_name, row.period_start, row.period_end, row.cadence


def _total_key(row: MonthlyMarketTotal) -> tuple[str, str, date, date]:
    return row.scope_name, row.cadence, row.period_start, row.period_end


def _structure_key(row: ThemeMarketStructureMetric) -> tuple[str, str, date, date]:
    return row.scope_name, row.cadence, row.period_start, row.period_end


def _month_shift(month_start: date, offset: int) -> date:
    month_index = month_start.year * 12 + month_start.month - 1 + offset
    year, month_zero_based = divmod(month_index, 12)
    return date(year, month_zero_based + 1, 1)


def _require_natural_month(period_start: object, period_end: object, *, field_name: str) -> None:
    if type(period_start) is not date or type(period_end) is not date:
        raise AggregationValidationError(f"{field_name} must use date boundaries")
    start = period_start
    end = period_end
    if start.day != 1 or end != date(
        start.year,
        start.month,
        calendar.monthrange(start.year, start.month)[1],
    ):
        raise AggregationValidationError(f"{field_name} must be a natural calendar month")


def _require_timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AggregationValidationError(f"{field_name} must be timezone-aware")
    return value


__all__ = [
    "ACCELERATION_NORMALIZED_SLOPE_MARGIN",
    "DIRECTION_MIN_R_SQUARED",
    "DIRECTION_NORMALIZED_SLOPE_THRESHOLD",
    "MODEL_POLICY_VERSION",
    "SEASONALITY_MAX_HISTORY_MONTHS",
    "SEASONALITY_MIN_HISTORY_MONTHS",
    "STABILITY_STABLE_CV_MAX",
    "STABILITY_VARIABLE_CV_MAX",
    "calculate_theme_model_metrics",
]
