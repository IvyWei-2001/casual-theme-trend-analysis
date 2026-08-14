"""Pure leakage-safe BACKTEST-001 launch-window evaluation.

The calculation consumes only normalized rows already accepted by AGG-002,
TREND-001, and MODEL-002.  Every decision feature is read from the decision
month; future evidence is read from exactly the requested outcome month.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime
from math import ceil, isclose, sqrt
from statistics import mean
from typing import Protocol, TypeGuard

from .backtest_models import (
    BACKTEST_LOW_SAMPLE_COHORT_COUNT,
    BACKTEST_LOW_SAMPLE_ROW_COUNT,
    BACKTEST_MIN_COHORT_SIZE,
    BACKTEST_OUTCOME_HORIZONS,
    BACKTEST_POLICY_VERSION,
    BACKTEST_TOP_FRACTION,
    BACKTEST_WILSON_Z,
    FEATURE_DEFINITIONS,
    PRIMARY_OUTCOME_NAMES,
    SEGMENT_NAMES,
    ThemeBacktestFeatureMetric,
    ThemeBacktestSegmentMetric,
    ThemeLaunchWindowBacktestResult,
    ThemeLaunchWindowOutcome,
    month_shift,
    natural_month_end,
)
from .errors import BacktestValidationError
from .model_v2_models import MODEL_POLICY_VERSION, ThemeModelSummary, ThemeSeasonalityProfile
from .models import MonthlyMarketTotal
from .opportunity_models import ThemeGrowthSourceMetric, ThemeMarketStructureMetric
from .trend_models import ThemeTrendScore


class _ThemeIdentityRow(Protocol):
    @property
    def scope_name(self) -> str: ...

    @property
    def cadence(self) -> str: ...

    @property
    def period_start(self) -> date: ...

    @property
    def period_end(self) -> date: ...

    @property
    def game_theme(self) -> str: ...


def calculate_theme_launch_window_backtest(
    monthly_market_totals: Sequence[MonthlyMarketTotal],
    theme_market_structure_metrics: Sequence[ThemeMarketStructureMetric],
    theme_growth_source_metrics: Sequence[ThemeGrowthSourceMetric],
    theme_trend_scores: Sequence[ThemeTrendScore],
    theme_model_summaries: Sequence[ThemeModelSummary],
    theme_seasonality_profiles: Sequence[ThemeSeasonalityProfile],
    *,
    calculated_at: datetime,
) -> ThemeLaunchWindowBacktestResult:
    """Calculate all raw outcomes, feature metrics, and segment metrics.

    The supplied rows must cover one complete, consecutive natural-month
    range.  This function never recalculates AGG-002, TREND-001, or MODEL-002
    values and never reads a row after the exact outcome month for a raw row.
    """

    _require_timestamp(calculated_at)
    totals = tuple(monthly_market_totals)
    structures = tuple(theme_market_structure_metrics)
    growth_sources = tuple(theme_growth_source_metrics)
    trend_scores = tuple(theme_trend_scores)
    summaries = tuple(theme_model_summaries)
    seasonality = tuple(theme_seasonality_profiles)
    start, end, _periods = _validate_input_range(totals)
    scope_name = totals[0].scope_name

    structure_by_identity = _index_rows(
        structures,
        label="market structure",
        scope_name=scope_name,
        start=start,
        end=end,
        identity=lambda row: _theme_identity(row),
    )
    growth_by_identity = _index_rows(
        growth_sources,
        label="growth source",
        scope_name=scope_name,
        start=start,
        end=end,
        identity=lambda row: _theme_identity(row),
    )
    score_by_identity = _index_rows(
        trend_scores,
        label="legacy trend score",
        scope_name=scope_name,
        start=start,
        end=end,
        identity=lambda row: _theme_identity(row),
    )
    summary_by_identity = _index_rows(
        summaries,
        label="model summary",
        scope_name=scope_name,
        start=start,
        end=end,
        identity=lambda row: _theme_identity(row),
    )
    seasonality_by_identity = _index_rows(
        seasonality,
        label="seasonality profile",
        scope_name=scope_name,
        start=start,
        end=end,
        identity=lambda row: _seasonality_identity(row),
    )
    total_by_period = {_period_identity(row): row for row in totals}
    _validate_source_identity_compatibility(
        structure_by_identity,
        growth_by_identity,
        score_by_identity,
        summary_by_identity,
        total_by_period,
    )

    raw_rows: list[ThemeLaunchWindowOutcome] = []
    expected_decision_ids = _expected_decision_identities(
        summary_by_identity,
        score_by_identity,
        total_by_period,
    )
    for identity in sorted(
        expected_decision_ids,
        key=lambda value: (value[2], value[3], str(value[4])),
    ):
        decision_period = identity[2]
        if not isinstance(decision_period, date):
            raise BacktestValidationError("BACKTEST-001 source identities are incompatible")
        decision_structure = structure_by_identity[identity]
        summary = summary_by_identity[identity]
        trend_score = score_by_identity[identity]
        growth_source = growth_by_identity[identity]
        theme = decision_structure.game_theme
        for horizon in BACKTEST_OUTCOME_HORIZONS:
            outcome_period = month_shift(decision_period, horizon)
            if (
                scope_name,
                outcome_period,
                natural_month_end(outcome_period),
            ) not in total_by_period:
                continue
            future_identity = (
                scope_name,
                "monthly",
                outcome_period,
                natural_month_end(outcome_period),
                theme,
            )
            future_structure = structure_by_identity.get(future_identity)
            raw_rows.append(
                _build_outcome(
                    decision_structure,
                    growth_source,
                    trend_score,
                    summary,
                    future_structure,
                    seasonality_by_identity,
                    outcome_period=outcome_period,
                    horizon=horizon,
                    backtest_policy_version=BACKTEST_POLICY_VERSION,
                    model_policy_version=MODEL_POLICY_VERSION,
                    calculated_at=calculated_at,
                )
            )

    ranked_rows = _assign_future_ranks(tuple(raw_rows))
    feature_metrics = _calculate_feature_metrics(
        ranked_rows,
        start=start,
        end=end,
        calculated_at=calculated_at,
        scope_name=scope_name,
    )
    segment_metrics = _calculate_segment_metrics(
        ranked_rows,
        start=start,
        end=end,
        calculated_at=calculated_at,
    )
    return ThemeLaunchWindowBacktestResult(
        outcomes=ranked_rows,
        feature_metrics=feature_metrics,
        segment_metrics=segment_metrics,
    )


def validate_backtest_source_identity_compatibility(
    monthly_market_totals: Sequence[MonthlyMarketTotal],
    theme_market_structure_metrics: Sequence[ThemeMarketStructureMetric],
    theme_growth_source_metrics: Sequence[ThemeGrowthSourceMetric],
    theme_trend_scores: Sequence[ThemeTrendScore],
    theme_model_summaries: Sequence[ThemeModelSummary],
) -> None:
    """Validate the exact decision population without reading storage.

    The workflow uses this same implementation before invoking the pure
    calculation.  Scores and 6M model summaries jointly establish expected
    decision identities, while the exact future total range excludes pre-6M
    rows and final months without a reachable outcome.
    """

    totals = tuple(monthly_market_totals)
    structures = tuple(theme_market_structure_metrics)
    growth_sources = tuple(theme_growth_source_metrics)
    trend_scores = tuple(theme_trend_scores)
    summaries = tuple(theme_model_summaries)
    start, end, _periods = _validate_input_range(totals)
    scope_name = totals[0].scope_name
    _validate_source_identity_compatibility(
        _index_rows(
            structures,
            label="market structure",
            scope_name=scope_name,
            start=start,
            end=end,
            identity=lambda row: _theme_identity(row),
        ),
        _index_rows(
            growth_sources,
            label="growth source",
            scope_name=scope_name,
            start=start,
            end=end,
            identity=lambda row: _theme_identity(row),
        ),
        _index_rows(
            trend_scores,
            label="legacy trend score",
            scope_name=scope_name,
            start=start,
            end=end,
            identity=lambda row: _theme_identity(row),
        ),
        _index_rows(
            summaries,
            label="model summary",
            scope_name=scope_name,
            start=start,
            end=end,
            identity=lambda row: _theme_identity(row),
        ),
        {_period_identity(row): row for row in totals},
    )


def _validate_input_range(
    totals: Sequence[MonthlyMarketTotal],
) -> tuple[date, date, tuple[date, ...]]:
    if not totals:
        raise BacktestValidationError("backtest requires monthly market totals")
    first = totals[0]
    if first.cadence != "monthly":
        raise BacktestValidationError("backtest requires monthly cadence")
    scope_name = first.scope_name
    by_period: dict[tuple[str, date, date], MonthlyMarketTotal] = {}
    for row in totals:
        if row.scope_name != scope_name or row.cadence != "monthly":
            raise BacktestValidationError("backtest source rows have incompatible scope")
        key = (row.scope_name, row.period_start, row.period_end)
        if key in by_period:
            raise BacktestValidationError("monthly totals contain duplicate identities")
        if row.period_end != natural_month_end(row.period_start) or row.period_start.day != 1:
            raise BacktestValidationError("monthly totals must use natural months")
        by_period[key] = row
    starts = sorted(row.period_start for row in totals)
    start = starts[0]
    end = starts[-1]
    periods = tuple(month_shift(start, offset) for offset in range(len(starts)))
    if starts != list(periods):
        raise BacktestValidationError("backtest source months must be consecutive")
    if len(periods) < 7:
        raise BacktestValidationError("backtest requires at least seven completed months")
    return start, end, periods


def _index_rows[ThemeRow](
    rows: Sequence[ThemeRow],
    *,
    label: str,
    scope_name: str,
    start: date,
    end: date,
    identity: Callable[[ThemeRow], tuple[object, ...]],
) -> dict[tuple[object, ...], ThemeRow]:
    indexed: dict[tuple[object, ...], ThemeRow] = {}
    for row in rows:
        if (
            getattr(row, "scope_name", None) != scope_name
            or getattr(row, "cadence", None) != "monthly"
        ):
            raise BacktestValidationError(f"{label} rows have incompatible scope")
        row_start = getattr(row, "period_start", None)
        row_end = getattr(row, "period_end", None)
        if not isinstance(row_start, date) or row_start < start or row_start > end:
            raise BacktestValidationError(f"{label} row is outside the requested range")
        if row_end != natural_month_end(row_start):
            raise BacktestValidationError(f"{label} rows must use natural months")
        row_identity = identity(row)
        if row_identity in indexed:
            raise BacktestValidationError(f"{label} rows contain duplicate identities")
        indexed[row_identity] = row
    return indexed


def _period_identity(row: MonthlyMarketTotal) -> tuple[str, date, date]:
    return (row.scope_name, row.period_start, row.period_end)


def _theme_identity(row: _ThemeIdentityRow) -> tuple[str, str, date, date, str]:
    return (
        row.scope_name,
        row.cadence,
        row.period_start,
        row.period_end,
        row.game_theme,
    )


def _seasonality_identity(
    row: ThemeSeasonalityProfile,
) -> tuple[str, str, date, date, str, str, int]:
    return (*_theme_identity(row), row.metric_name, row.calendar_month)


def _validate_source_identity_compatibility(
    structures: Mapping[tuple[object, ...], ThemeMarketStructureMetric],
    growth_sources: Mapping[tuple[object, ...], ThemeGrowthSourceMetric],
    scores: Mapping[tuple[object, ...], ThemeTrendScore],
    summaries: Mapping[tuple[object, ...], ThemeModelSummary],
    totals: Mapping[tuple[str, date, date], MonthlyMarketTotal],
) -> None:
    """Require complete stored decision evidence before building outcomes."""

    expected_decision_ids = _expected_decision_identities(summaries, scores, totals)
    if (
        not expected_decision_ids.issubset(structures)
        or not expected_decision_ids.issubset(growth_sources)
        or not expected_decision_ids.issubset(scores)
        or not expected_decision_ids.issubset(summaries)
    ):
        raise BacktestValidationError("BACKTEST-001 source identities are incompatible")


def _expected_decision_identities(
    summaries: Mapping[tuple[object, ...], ThemeModelSummary],
    scores: Mapping[tuple[object, ...], ThemeTrendScore],
    totals: Mapping[tuple[str, date, date], MonthlyMarketTotal],
) -> set[tuple[object, ...]]:
    """Return expected decision identities independently of structures."""

    candidate_ids = set(scores) | {
        identity for identity, summary in summaries.items() if summary.has_6m_history
    }
    expected: set[tuple[object, ...]] = set()
    for identity in candidate_ids:
        if len(identity) != 5:
            raise BacktestValidationError("BACKTEST-001 source identities are incompatible")
        scope_name, cadence, period_start, period_end, _theme = identity
        if not isinstance(scope_name, str) or cadence != "monthly":
            raise BacktestValidationError("BACKTEST-001 source identities are incompatible")
        if not isinstance(period_start, date) or not isinstance(period_end, date):
            raise BacktestValidationError("BACKTEST-001 source identities are incompatible")
        for horizon in BACKTEST_OUTCOME_HORIZONS:
            future_period = month_shift(period_start, horizon)
            if (
                scope_name,
                future_period,
                natural_month_end(future_period),
            ) in totals:
                expected.add(identity)
                break
    for identity in expected:
        summary = summaries.get(identity)
        if summary is None or not summary.has_6m_history:
            raise BacktestValidationError("BACKTEST-001 source identities are incompatible")
    return expected


def _build_outcome(
    decision_structure: ThemeMarketStructureMetric,
    growth_source: ThemeGrowthSourceMetric,
    trend_score: ThemeTrendScore,
    summary: ThemeModelSummary,
    future_structure: ThemeMarketStructureMetric | None,
    seasonality_by_identity: Mapping[tuple[object, ...], ThemeSeasonalityProfile],
    *,
    outcome_period: date,
    horizon: int,
    backtest_policy_version: str,
    model_policy_version: str,
    calculated_at: datetime,
) -> ThemeLaunchWindowOutcome:
    future_theme_present = future_structure is not None
    future_values: dict[str, float | int | None]
    if future_structure is None:
        future_product_count = 0
        future_product_share = 0.0
        future_values = {
            "product_count": future_product_count,
            "product_share": future_product_share,
            "downloads_sum": 0.0,
            "downloads_share": 0.0,
            "revenue_usd_sum": 0.0,
            "revenue_usd_share": 0.0,
        }
    else:
        future_product_count = future_structure.product_count
        future_product_share = future_structure.product_share
        future_values = {
            "product_count": future_product_count,
            "product_share": future_product_share,
            "downloads_sum": future_structure.downloads_sum,
            "downloads_share": future_structure.downloads_share,
            "revenue_usd_sum": future_structure.revenue_usd_sum,
            "revenue_usd_share": future_structure.revenue_usd_share,
        }

    future_calendar_month = outcome_period.month
    decision_identity = _theme_identity(decision_structure)
    downloads_profile = seasonality_by_identity.get(
        (*decision_identity, "downloads_sum", future_calendar_month)
    )
    revenue_profile = seasonality_by_identity.get(
        (*decision_identity, "revenue_usd_sum", future_calendar_month)
    )
    downloads_seasonal_index = (
        None if downloads_profile is None else downloads_profile.seasonal_index
    )
    revenue_seasonal_index = None if revenue_profile is None else revenue_profile.seasonal_index

    decision_values = {
        "product_count": decision_structure.product_count,
        "product_share": decision_structure.product_share,
        "downloads_sum": decision_structure.downloads_sum,
        "downloads_share": decision_structure.downloads_share,
        "revenue_usd_sum": decision_structure.revenue_usd_sum,
        "revenue_usd_share": decision_structure.revenue_usd_share,
    }
    changes: dict[str, float | None] = {}
    for metric_name, decision_value in decision_values.items():
        future_value = future_values[metric_name]
        absolute, relative = _changes(decision_value, future_value)
        changes[f"{metric_name}_absolute_change"] = absolute
        changes[f"{metric_name}_relative_change"] = relative

    return ThemeLaunchWindowOutcome(
        scope_name=decision_structure.scope_name,
        cadence=decision_structure.cadence,
        decision_period_start=decision_structure.period_start,
        decision_period_end=decision_structure.period_end,
        outcome_horizon_months=horizon,
        outcome_period_start=outcome_period,
        outcome_period_end=natural_month_end(outcome_period),
        game_theme=decision_structure.game_theme,
        backtest_policy_version=backtest_policy_version,
        model_policy_version=model_policy_version,
        legacy_is_actionable=trend_score.is_actionable,
        legacy_exclusion_reason=trend_score.exclusion_reason,
        legacy_confidence_score=trend_score.confidence_score,
        legacy_6m_momentum_score=trend_score.trend_score,
        legacy_6m_momentum_rank=trend_score.trend_rank,
        has_6m_history=summary.has_6m_history,
        has_12m_history=summary.has_12m_history,
        has_36m_history=summary.has_36m_history,
        direction_6m=summary.direction_6m,
        direction_12m=summary.direction_12m,
        direction_36m=summary.direction_36m,
        direction_evidence_count_6m=summary.direction_evidence_count_6m,
        direction_evidence_count_12m=summary.direction_evidence_count_12m,
        direction_evidence_count_36m=summary.direction_evidence_count_36m,
        median_normalized_slope_6m=summary.median_normalized_slope_6m,
        median_normalized_slope_12m=summary.median_normalized_slope_12m,
        median_normalized_slope_36m=summary.median_normalized_slope_36m,
        stability_cv_median_6m=summary.stability_cv_median_6m,
        stability_cv_median_12m=summary.stability_cv_median_12m,
        stability_cv_median_36m=summary.stability_cv_median_36m,
        stability_band_6m=summary.stability_band_6m,
        stability_band_12m=summary.stability_band_12m,
        stability_band_36m=summary.stability_band_36m,
        lifecycle_stage=summary.lifecycle_stage,
        first_active_left_censored=summary.first_active_left_censored,
        months_since_first_active=summary.months_since_first_active,
        decision_product_count=decision_structure.product_count,
        decision_product_share=decision_structure.product_share,
        decision_downloads_sum=decision_structure.downloads_sum,
        decision_downloads_share=decision_structure.downloads_share,
        decision_revenue_usd_sum=decision_structure.revenue_usd_sum,
        decision_revenue_usd_share=decision_structure.revenue_usd_share,
        decision_downloads_product_hhi=decision_structure.downloads_product_hhi,
        decision_revenue_usd_product_hhi=decision_structure.revenue_usd_product_hhi,
        decision_publisher_downloads_hhi=decision_structure.publisher_downloads_hhi,
        decision_publisher_revenue_usd_hhi=decision_structure.publisher_revenue_usd_hhi,
        decision_top_500_turnover_rate=growth_source.top_500_turnover_rate,
        decision_market_new_entry_share=growth_source.market_new_entry_share,
        decision_downloads_market_new_entry_share_of_current=(
            growth_source.downloads_market_new_entry_share_of_current
        ),
        decision_revenue_usd_market_new_entry_share_of_current=(
            growth_source.revenue_usd_market_new_entry_share_of_current
        ),
        decision_downloads_top_10_positive_contribution_share=(
            growth_source.downloads_top_10_positive_contribution_share
        ),
        decision_revenue_usd_top_10_positive_contribution_share=(
            growth_source.revenue_usd_top_10_positive_contribution_share
        ),
        decision_downloads_expected_seasonal_index=downloads_seasonal_index,
        decision_revenue_usd_expected_seasonal_index=revenue_seasonal_index,
        decision_downloads_seasonality_amplitude=(
            summary.downloads_seasonality_amplitude
            if downloads_seasonal_index is not None
            else None
        ),
        decision_revenue_usd_seasonality_amplitude=(
            summary.revenue_usd_seasonality_amplitude
            if revenue_seasonal_index is not None
            else None
        ),
        future_theme_present=future_theme_present,
        future_product_count=future_product_count,
        future_product_share=future_product_share,
        future_downloads_sum=_as_float_or_none(future_values["downloads_sum"]),
        future_downloads_share=_as_float_or_none(future_values["downloads_share"]),
        future_revenue_usd_sum=_as_float_or_none(future_values["revenue_usd_sum"]),
        future_revenue_usd_share=_as_float_or_none(future_values["revenue_usd_share"]),
        product_count_absolute_change=changes["product_count_absolute_change"],
        product_count_relative_change=changes["product_count_relative_change"],
        product_share_absolute_change=changes["product_share_absolute_change"],
        product_share_relative_change=changes["product_share_relative_change"],
        downloads_sum_absolute_change=changes["downloads_sum_absolute_change"],
        downloads_sum_relative_change=changes["downloads_sum_relative_change"],
        downloads_share_absolute_change=changes["downloads_share_absolute_change"],
        downloads_share_relative_change=changes["downloads_share_relative_change"],
        revenue_usd_sum_absolute_change=changes["revenue_usd_sum_absolute_change"],
        revenue_usd_sum_relative_change=changes["revenue_usd_sum_relative_change"],
        revenue_usd_share_absolute_change=changes["revenue_usd_share_absolute_change"],
        revenue_usd_share_relative_change=changes["revenue_usd_share_relative_change"],
        product_share_change_direction=_change_direction(
            decision_structure.product_share,
            future_product_share,
        ),
        downloads_share_change_direction=_change_direction(
            decision_structure.downloads_share,
            _as_float_or_none(future_values["downloads_share"]),
        ),
        revenue_usd_share_change_direction=_change_direction(
            decision_structure.revenue_usd_share,
            _as_float_or_none(future_values["revenue_usd_share"]),
        ),
        future_product_share_percentile=0.5,
        future_downloads_share_percentile=(
            0.5 if future_values["downloads_share"] is not None else None
        ),
        future_revenue_usd_share_percentile=(
            0.5 if future_values["revenue_usd_share"] is not None else None
        ),
        future_product_share_top_quintile=None,
        future_downloads_share_top_quintile=None,
        future_revenue_usd_share_top_quintile=None,
        calculated_at=calculated_at,
    )


def _as_float_or_none(value: float | int | None) -> float | None:
    return None if value is None else float(value)


def _changes(
    decision_value: float | int | None,
    future_value: float | int | None,
) -> tuple[float | None, float | None]:
    if decision_value is None or future_value is None:
        return None, None
    absolute = float(future_value) - float(decision_value)
    relative = absolute / float(decision_value) if float(decision_value) > 0 else None
    return absolute, relative


def _change_direction(decision_value: float | None, future_value: float | None) -> str:
    if decision_value is None or future_value is None:
        return "unavailable"
    if isclose(future_value, decision_value, rel_tol=1e-9, abs_tol=1e-12):
        return "unchanged"
    return "up" if future_value > decision_value else "down"


def _assign_future_ranks(
    rows: Sequence[ThemeLaunchWindowOutcome],
) -> tuple[ThemeLaunchWindowOutcome, ...]:
    by_cohort: defaultdict[tuple[date, int], list[ThemeLaunchWindowOutcome]] = defaultdict(list)
    for row in rows:
        by_cohort[(row.decision_period_start, row.outcome_horizon_months)].append(row)
    updated: dict[tuple[object, ...], ThemeLaunchWindowOutcome] = {
        row.identity: row for row in rows
    }
    for cohort_rows in by_cohort.values():
        updated_rows = cohort_rows
        for value_name, percentile_name in (
            (
                "future_product_share",
                "future_product_share_percentile",
            ),
            (
                "future_downloads_share",
                "future_downloads_share_percentile",
            ),
            (
                "future_revenue_usd_share",
                "future_revenue_usd_percentile",
            ),
        ):
            numeric_rows = [row for row in updated_rows if _is_numeric(getattr(row, value_name))]
            percentiles = _percentiles_for_rows(numeric_rows, value_name)
            top_flags = _top_flags_for_rows(numeric_rows, value_name)
            for row in updated_rows:
                percentile = percentiles.get(row.identity)
                top_flag = top_flags.get(row.identity)
                if percentile_name == "future_product_share_percentile":
                    updated[row.identity] = replace(
                        updated[row.identity],
                        future_product_share_percentile=percentile
                        if percentile is not None
                        else 0.5,
                        future_product_share_top_quintile=top_flag,
                    )
                elif percentile_name == "future_downloads_share_percentile":
                    updated[row.identity] = replace(
                        updated[row.identity],
                        future_downloads_share_percentile=percentile,
                        future_downloads_share_top_quintile=top_flag,
                    )
                else:
                    updated[row.identity] = replace(
                        updated[row.identity],
                        future_revenue_usd_share_percentile=percentile,
                        future_revenue_usd_share_top_quintile=top_flag,
                    )
    return tuple(updated[row.identity] for row in rows)


def _percentiles_for_rows(
    rows: Sequence[ThemeLaunchWindowOutcome],
    value_name: str,
) -> dict[tuple[object, ...], float]:
    if not rows:
        return {}
    sorted_values = sorted(float(getattr(row, value_name)) for row in rows)
    ranks = _average_ranks(sorted_values)
    n = len(rows)
    by_value: dict[float, float] = {}
    for value, rank in zip(sorted_values, ranks, strict=True):
        by_value[value] = 0.5 if n == 1 else (rank - 1) / (n - 1)
    return {row.identity: by_value[float(getattr(row, value_name))] for row in rows}


def _top_flags_for_rows(
    rows: Sequence[ThemeLaunchWindowOutcome],
    value_name: str,
) -> dict[tuple[object, ...], bool | None]:
    if len(rows) < BACKTEST_MIN_COHORT_SIZE:
        return {row.identity: None for row in rows}
    top_count = max(1, ceil(len(rows) * BACKTEST_TOP_FRACTION))
    ordered = sorted(
        rows,
        key=lambda row: (-float(getattr(row, value_name)), row.game_theme),
    )
    selected = {row.identity for row in ordered[:top_count]}
    return {row.identity: row.identity in selected for row in rows}


def _calculate_feature_metrics(
    rows: Sequence[ThemeLaunchWindowOutcome],
    *,
    start: date,
    end: date,
    calculated_at: datetime,
    scope_name: str,
) -> tuple[ThemeBacktestFeatureMetric, ...]:
    metrics: list[ThemeBacktestFeatureMetric] = []
    for horizon in BACKTEST_OUTCOME_HORIZONS:
        horizon_rows = tuple(row for row in rows if row.outcome_horizon_months == horizon)
        for definition in FEATURE_DEFINITIONS:
            for outcome_name in PRIMARY_OUTCOME_NAMES:
                metrics.append(
                    _feature_metric(
                        horizon_rows,
                        definition.feature_name,
                        outcome_name,
                        definition.feature_hypothesis,
                        definition.feature_group,
                        start=start,
                        end=end,
                        horizon=horizon,
                        calculated_at=calculated_at,
                        scope_name=scope_name,
                    )
                )
    return tuple(metrics)


def _feature_metric(
    rows: Sequence[ThemeLaunchWindowOutcome],
    feature_name: str,
    outcome_name: str,
    feature_hypothesis: str,
    feature_group: str,
    *,
    start: date,
    end: date,
    horizon: int,
    calculated_at: datetime,
    scope_name: str,
) -> ThemeBacktestFeatureMetric:
    candidate_count = len(rows)
    pair_groups: defaultdict[date, list[tuple[ThemeLaunchWindowOutcome, float, float]]] = (
        defaultdict(list)
    )
    paired_outcomes: list[float] = []
    for row in rows:
        feature_value = _feature_value(row, feature_name)
        outcome_value = _outcome_value(row, outcome_name)
        if _is_numeric(feature_value) and _is_numeric(outcome_value):
            oriented = (
                float(feature_value)
                if feature_hypothesis == "higher_better"
                else -float(feature_value)
            )
            numeric_outcome = float(outcome_value)
            pair_groups[row.decision_period_start].append((row, oriented, numeric_outcome))
            paired_outcomes.append(numeric_outcome)
    eligible_count = len(paired_outcomes)
    decision_month_count = len(pair_groups)
    correlations: list[float] = []
    correlation_cohort_count = 0
    for pairs in pair_groups.values():
        if len(pairs) < BACKTEST_MIN_COHORT_SIZE:
            continue
        correlation = _spearman(
            [pair[1] for pair in pairs],
            [pair[2] for pair in pairs],
        )
        if correlation is not None:
            correlations.append(correlation)
            correlation_cohort_count += 1

    top_groups = [pairs for pairs in pair_groups.values() if len(pairs) >= BACKTEST_MIN_COHORT_SIZE]
    selected_outcomes: list[float] = []
    hit_count = 0
    selected_count = 0
    outcome_top_count = 0
    outcome_population_count = 0
    for pairs in top_groups:
        feature_ordered = sorted(pairs, key=lambda pair: (-pair[1], pair[0].game_theme))
        outcome_ordered = sorted(pairs, key=lambda pair: (-pair[2], pair[0].game_theme))
        top_count = max(1, ceil(len(pairs) * BACKTEST_TOP_FRACTION))
        selected = feature_ordered[:top_count]
        future_top = {pair[0].identity for pair in outcome_ordered[:top_count]}
        selected_count += len(selected)
        hit_count += sum(pair[0].identity in future_top for pair in selected)
        selected_outcomes.extend(pair[2] for pair in selected)
        outcome_top_count += len(future_top)
        outcome_population_count += len(pairs)

    top_hit_rate = None if selected_count == 0 else hit_count / selected_count
    base_rate = (
        None if outcome_population_count == 0 else outcome_top_count / outcome_population_count
    )
    lift = (
        None
        if base_rate is None or base_rate == 0 or top_hit_rate is None
        else top_hit_rate / base_rate
    )
    positive_change = outcome_name in {
        "downloads_share_absolute_change",
        "revenue_usd_share_absolute_change",
    }
    selected_positive_count, selected_positive_rate = _positive_rate(
        selected_outcomes if positive_change else (),
    )
    all_positive_count, all_positive_rate = _positive_rate(
        paired_outcomes if positive_change else (),
    )
    positive_correlations = sum(value > 0 for value in correlations)
    positive_correlation_ratio = (
        None if not correlations else positive_correlations / len(correlations)
    )
    positive_ci = (
        _wilson_interval(positive_correlations, len(correlations)) if correlations else (None, None)
    )
    top_hit_ci = _wilson_interval(hit_count, selected_count) if selected_count else (None, None)
    selected_positive_ci = (
        _wilson_interval(selected_positive_count, len(selected_outcomes))
        if positive_change and selected_outcomes
        else (None, None)
    )
    all_positive_ci = (
        _wilson_interval(all_positive_count, len(paired_outcomes))
        if positive_change and paired_outcomes
        else (None, None)
    )
    return ThemeBacktestFeatureMetric(
        scope_name=scope_name,
        cadence="monthly",
        backtest_start=start,
        backtest_end=end,
        outcome_horizon_months=horizon,
        feature_name=feature_name,
        feature_group=feature_group,
        feature_hypothesis=feature_hypothesis,
        outcome_name=outcome_name,
        backtest_policy_version=BACKTEST_POLICY_VERSION,
        candidate_row_count=candidate_count,
        eligible_row_count=eligible_count,
        coverage_ratio=0.0 if candidate_count == 0 else eligible_count / candidate_count,
        decision_month_count=decision_month_count,
        correlation_cohort_count=correlation_cohort_count,
        mean_spearman=None if not correlations else mean(correlations),
        median_spearman=_median_or_none(correlations),
        p25_spearman=_percentile_or_none(correlations, 0.25),
        p75_spearman=_percentile_or_none(correlations, 0.75),
        positive_spearman_cohort_count=None if not correlations else positive_correlations,
        positive_spearman_cohort_ratio=positive_correlation_ratio,
        positive_spearman_ci_low=positive_ci[0],
        positive_spearman_ci_high=positive_ci[1],
        top_quintile_cohort_count=len(top_groups) if top_groups else None,
        top_quintile_selected_count=selected_count if top_groups else None,
        top_quintile_hit_count=None if not top_groups else hit_count,
        top_quintile_hit_rate=top_hit_rate,
        top_quintile_hit_ci_low=top_hit_ci[0],
        top_quintile_hit_ci_high=top_hit_ci[1],
        future_top_quintile_base_rate=base_rate,
        top_quintile_lift=lift,
        top_quintile_outcome_mean=_mean_or_none(selected_outcomes),
        top_quintile_outcome_median=_median_or_none(selected_outcomes),
        all_eligible_outcome_mean=_mean_or_none(paired_outcomes),
        all_eligible_outcome_median=_median_or_none(paired_outcomes),
        top_quintile_positive_change_count=selected_positive_count
        if positive_change and selected_outcomes
        else None,
        top_quintile_positive_change_rate=selected_positive_rate
        if positive_change and selected_outcomes
        else None,
        top_quintile_positive_change_ci_low=selected_positive_ci[0],
        top_quintile_positive_change_ci_high=selected_positive_ci[1],
        all_positive_change_count=all_positive_count
        if positive_change and paired_outcomes
        else None,
        all_positive_change_rate=all_positive_rate if positive_change and paired_outcomes else None,
        all_positive_change_ci_low=all_positive_ci[0],
        all_positive_change_ci_high=all_positive_ci[1],
        low_sample_warning=(
            eligible_count < BACKTEST_LOW_SAMPLE_ROW_COUNT
            or decision_month_count < BACKTEST_LOW_SAMPLE_COHORT_COUNT
        ),
        calculated_at=calculated_at,
    )


def _calculate_segment_metrics(
    rows: Sequence[ThemeLaunchWindowOutcome],
    *,
    start: date,
    end: date,
    calculated_at: datetime,
) -> tuple[ThemeBacktestSegmentMetric, ...]:
    metrics: list[ThemeBacktestSegmentMetric] = []
    for horizon in BACKTEST_OUTCOME_HORIZONS:
        horizon_rows = tuple(row for row in rows if row.outcome_horizon_months == horizon)
        outcome_top_flags = {
            outcome_name: _outcome_top_flags(horizon_rows, outcome_name)
            for outcome_name in PRIMARY_OUTCOME_NAMES
        }
        for segment_name in SEGMENT_NAMES:
            observed_values = sorted({_segment_value(row, segment_name) for row in horizon_rows})
            for segment_value in observed_values:
                segment_rows = tuple(
                    row
                    for row in horizon_rows
                    if _segment_value(row, segment_name) == segment_value
                )
                for outcome_name in PRIMARY_OUTCOME_NAMES:
                    metrics.append(
                        _segment_metric(
                            segment_rows,
                            horizon_rows,
                            segment_name,
                            segment_value,
                            outcome_name,
                            outcome_top_flags[outcome_name],
                            start=start,
                            end=end,
                            horizon=horizon,
                            calculated_at=calculated_at,
                        )
                    )
    return tuple(metrics)


def _segment_metric(
    segment_rows: Sequence[ThemeLaunchWindowOutcome],
    all_rows: Sequence[ThemeLaunchWindowOutcome],
    segment_name: str,
    segment_value: str,
    outcome_name: str,
    outcome_top_flags: dict[tuple[object, ...], bool | None],
    *,
    start: date,
    end: date,
    horizon: int,
    calculated_at: datetime,
) -> ThemeBacktestSegmentMetric:
    outcome_values = [
        float(value)
        for row in segment_rows
        if _is_numeric(value := _outcome_value(row, outcome_name))
    ]
    eligible_count = len(outcome_values)
    candidate_count = len(segment_rows)
    decision_month_count = len(
        {
            row.decision_period_start
            for row in segment_rows
            if _is_numeric(_outcome_value(row, outcome_name))
        }
    )
    valid_cohort_rows = [
        row
        for row in all_rows
        if _is_numeric(_outcome_value(row, outcome_name))
        and row.identity in outcome_top_flags
    ]
    valid_segment_rows = [row for row in segment_rows if row.identity in outcome_top_flags]
    top_eligible_count = len(valid_segment_rows)
    top_count = sum(outcome_top_flags[row.identity] is True for row in valid_segment_rows)
    top_rate = (
        None if top_eligible_count == 0 else top_count / top_eligible_count
    )
    all_top_count = sum(outcome_top_flags[row.identity] is True for row in valid_cohort_rows)
    all_top_population = len(valid_cohort_rows)
    base_rate = None if all_top_population == 0 else all_top_count / all_top_population
    lift = None if base_rate is None or base_rate == 0 or top_rate is None else top_rate / base_rate
    positive_change = outcome_name in {
        "downloads_share_absolute_change",
        "revenue_usd_share_absolute_change",
    }
    positive_count, positive_rate = _positive_rate(outcome_values if positive_change else ())
    top_ci = (
        _wilson_interval(top_count, top_eligible_count)
        if top_eligible_count
        else (None, None)
    )
    positive_ci = (
        _wilson_interval(positive_count, eligible_count)
        if positive_change and eligible_count
        else (None, None)
    )
    return ThemeBacktestSegmentMetric(
        scope_name=segment_rows[0].scope_name if segment_rows else "backtest",
        cadence="monthly",
        backtest_start=start,
        backtest_end=end,
        outcome_horizon_months=horizon,
        segment_name=segment_name,
        segment_value=segment_value,
        outcome_name=outcome_name,
        backtest_policy_version=BACKTEST_POLICY_VERSION,
        candidate_row_count=candidate_count,
        eligible_row_count=eligible_count,
        coverage_ratio=0.0 if candidate_count == 0 else eligible_count / candidate_count,
        decision_month_count=decision_month_count,
        segment_row_share=0.0 if not all_rows else candidate_count / len(all_rows),
        outcome_mean=_mean_or_none(outcome_values),
        outcome_median=_median_or_none(outcome_values),
        outcome_p25=_percentile_or_none(outcome_values, 0.25),
        outcome_p75=_percentile_or_none(outcome_values, 0.75),
        future_top_quintile_eligible_count=top_eligible_count,
        future_top_quintile_count=top_count,
        future_top_quintile_rate=top_rate,
        future_top_quintile_ci_low=top_ci[0],
        future_top_quintile_ci_high=top_ci[1],
        future_top_quintile_base_rate=base_rate,
        future_top_quintile_lift=lift,
        positive_change_count=positive_count if positive_change and outcome_values else None,
        positive_change_rate=positive_rate if positive_change and outcome_values else None,
        positive_change_ci_low=positive_ci[0],
        positive_change_ci_high=positive_ci[1],
        low_sample_warning=(
            eligible_count < BACKTEST_LOW_SAMPLE_ROW_COUNT
            or decision_month_count < BACKTEST_LOW_SAMPLE_COHORT_COUNT
        ),
        calculated_at=calculated_at,
    )


def _outcome_top_flags(
    rows: Sequence[ThemeLaunchWindowOutcome],
    outcome_name: str,
) -> dict[tuple[object, ...], bool | None]:
    by_month: defaultdict[date, list[ThemeLaunchWindowOutcome]] = defaultdict(list)
    for row in rows:
        if _is_numeric(_outcome_value(row, outcome_name)):
            by_month[row.decision_period_start].append(row)
    flags: dict[tuple[object, ...], bool | None] = {}
    for month_rows in by_month.values():
        if len(month_rows) < BACKTEST_MIN_COHORT_SIZE:
            continue
        value_name = _outcome_name_to_field(outcome_name)
        flags.update(_top_flags_for_rows(month_rows, value_name))
    return flags


def _feature_value(row: ThemeLaunchWindowOutcome, feature_name: str) -> float | None:
    mapping = {
        "decision_product_share": row.decision_product_share,
        "decision_downloads_share": row.decision_downloads_share,
        "decision_revenue_usd_share": row.decision_revenue_usd_share,
        "legacy_6m_momentum_score": row.legacy_6m_momentum_score,
        "median_normalized_slope_6m": row.median_normalized_slope_6m,
        "median_normalized_slope_12m": row.median_normalized_slope_12m,
        "median_normalized_slope_36m": row.median_normalized_slope_36m,
        "stability_cv_median_6m": row.stability_cv_median_6m,
        "stability_cv_median_12m": row.stability_cv_median_12m,
        "stability_cv_median_36m": row.stability_cv_median_36m,
        "downloads_product_hhi": row.decision_downloads_product_hhi,
        "revenue_usd_product_hhi": row.decision_revenue_usd_product_hhi,
        "top_500_turnover_rate": row.decision_top_500_turnover_rate,
        "downloads_market_new_entry_share_of_current": (
            row.decision_downloads_market_new_entry_share_of_current
        ),
        "revenue_usd_market_new_entry_share_of_current": (
            row.decision_revenue_usd_market_new_entry_share_of_current
        ),
        "downloads_top_10_positive_contribution_share": (
            row.decision_downloads_top_10_positive_contribution_share
        ),
        "revenue_usd_top_10_positive_contribution_share": (
            row.decision_revenue_usd_top_10_positive_contribution_share
        ),
        "downloads_expected_seasonal_index": row.decision_downloads_expected_seasonal_index,
        "revenue_usd_expected_seasonal_index": row.decision_revenue_usd_expected_seasonal_index,
    }
    return mapping.get(feature_name)


def _outcome_value(row: ThemeLaunchWindowOutcome, outcome_name: str) -> float | None:
    return {
        "future_downloads_share": row.future_downloads_share,
        "future_revenue_usd_share": row.future_revenue_usd_share,
        "downloads_share_absolute_change": row.downloads_share_absolute_change,
        "revenue_usd_share_absolute_change": row.revenue_usd_share_absolute_change,
    }[outcome_name]


def _outcome_name_to_field(outcome_name: str) -> str:
    return {
        "future_downloads_share": "future_downloads_share",
        "future_revenue_usd_share": "future_revenue_usd_share",
        "downloads_share_absolute_change": "downloads_share_absolute_change",
        "revenue_usd_share_absolute_change": "revenue_usd_share_absolute_change",
    }[outcome_name]


def _segment_value(row: ThemeLaunchWindowOutcome, segment_name: str) -> str:
    if segment_name == "legacy_actionability":
        return "actionable" if row.legacy_is_actionable else "non_actionable"
    return str(getattr(row, segment_name))


def _is_numeric(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _average_ranks(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(indexed):
        end = position + 1
        while end < len(indexed) and indexed[end][1] == indexed[position][1]:
            end += 1
        average_rank = (position + 1 + end) / 2
        for index in range(position, end):
            ranks[indexed[index][0]] = average_rank
        position = end
    return ranks


def _spearman(first: Sequence[float], second: Sequence[float]) -> float | None:
    if len(first) != len(second) or len(first) < 2:
        return None
    first_ranks = _average_ranks(first)
    second_ranks = _average_ranks(second)
    first_mean = mean(first_ranks)
    second_mean = mean(second_ranks)
    numerator = sum(
        (left - first_mean) * (right - second_mean)
        for left, right in zip(first_ranks, second_ranks, strict=True)
    )
    first_denominator = sqrt(sum((value - first_mean) ** 2 for value in first_ranks))
    second_denominator = sqrt(sum((value - second_mean) ** 2 for value in second_ranks))
    if first_denominator == 0 or second_denominator == 0:
        return None
    return numerator / (first_denominator * second_denominator)


def _percentile_or_none(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _median_or_none(values: Sequence[float]) -> float | None:
    return _percentile_or_none(values, 0.5)


def _mean_or_none(values: Sequence[float]) -> float | None:
    return None if not values else mean(values)


def _positive_rate(values: Sequence[float]) -> tuple[int | None, float | None]:
    if not values:
        return None, None
    positive_count = sum(
        value > 0 and not isclose(value, 0.0, rel_tol=1e-9, abs_tol=1e-12) for value in values
    )
    return positive_count, positive_count / len(values)


def _wilson_interval(successes: int | None, trials: int) -> tuple[float | None, float | None]:
    if successes is None or trials == 0:
        return None, None
    z = BACKTEST_WILSON_Z
    denominator = 1 + z * z / trials
    center = (successes / trials) + z * z / (2 * trials)
    margin = z * sqrt(
        (successes / trials * (1 - successes / trials) + z * z / (4 * trials)) / trials
    )
    lower = (center - margin) / denominator
    upper = (center + margin) / denominator
    return max(0.0, lower), min(1.0, upper)


def _require_timestamp(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BacktestValidationError("calculated_at must be timezone-aware")


__all__ = [
    "calculate_theme_launch_window_backtest",
    "validate_backtest_source_identity_compatibility",
]
