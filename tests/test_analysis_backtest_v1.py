"""Pure synthetic regression tests for the leakage-safe BACKTEST-001 analysis."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest
from test_analysis_theme_monthly import _metadata, _row

from src.analysis.backtest_v1 import (
    _calculate_segment_metrics,
    _feature_metric,
    _percentile_or_none,
    _spearman,
    _wilson_interval,
    calculate_theme_launch_window_backtest,
)
from src.analysis.errors import AggregationValidationError, BacktestValidationError
from src.analysis.model_v2 import calculate_theme_model_metrics
from src.analysis.opportunity_aggregation import aggregate_theme_opportunity_metrics
from src.analysis.trend_score import calculate_theme_trend_scores

CALCULATED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _month(index: int) -> str:
    month_number = 2023 * 12 + 8 - 1 + index
    year, zero_month = divmod(month_number, 12)
    return f"{year:04d}-{zero_month + 1:02d}"


def _build_payload(*, theme_count: int = 1, null_metric_index: int | None = None) -> Any:
    source_periods = []
    metadata = {}
    for month_index in range(36):
        current_rows = []
        for theme_index in range(theme_count):
            app_id = f"backtest-app-{month_index}-{theme_index}"
            missing_metrics = month_index == null_metric_index
            row = _row(
                app_id,
                theme_index + 1,
                month=_month(month_index),
                theme=f"Theme-{theme_index}",
                units=None if missing_metrics else 100.0 + theme_index * 10,
                revenue=None if missing_metrics else 100.0 + theme_index * 5,
            )
            current_rows.append(row)
            metadata[app_id] = _metadata(app_id, "Publisher")
        source_periods.append(current_rows)
    return aggregate_theme_opportunity_metrics(
        source_periods,
        metadata,
        calculated_at=CALCULATED_AT,
    )


def _calculate(payload: Any) -> Any:
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        CALCULATED_AT,
    )
    scores = calculate_theme_trend_scores(
        payload.monthly_totals,
        payload.theme_metrics,
        calculated_at=CALCULATED_AT,
    )
    result = calculate_theme_launch_window_backtest(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        payload.theme_growth_source_metrics,
        scores,
        model.model_summaries,
        model.seasonality_profiles,
        calculated_at=CALCULATED_AT,
    )
    return result, model, scores


@pytest.fixture(scope="module")
def five_theme_result() -> Any:
    return _calculate(_build_payload(theme_count=5))


def test_emits_fixed_registry_and_valid_cohort_statistics(five_theme_result: Any) -> None:
    result, _model, _scores = five_theme_result

    assert len(result.outcomes) == 435
    assert len(result.feature_metrics) == 19 * 4 * 3
    assert len({row.identity for row in result.outcomes}) == len(result.outcomes)
    assert len({row.identity for row in result.feature_metrics}) == 228

    first_decision_period = min(row.decision_period_start for row in result.outcomes)
    first_cohort = [
        row
        for row in result.outcomes
        if row.decision_period_start == first_decision_period and row.outcome_horizon_months == 1
    ]
    assert len(first_cohort) == 5
    assert all(row.future_product_share_percentile == 0.5 for row in first_cohort)
    assert [row.game_theme for row in first_cohort if row.future_product_share_top_quintile] == [
        "Theme-0"
    ]
    assert all(row.future_downloads_share_top_quintile is not None for row in first_cohort)

    feature_metric = next(
        row
        for row in result.feature_metrics
        if row.outcome_horizon_months == 1
        and row.feature_name == "decision_downloads_share"
        and row.outcome_name == "future_downloads_share"
    )
    assert feature_metric.correlation_cohort_count == 30
    assert feature_metric.top_quintile_cohort_count == 30
    assert feature_metric.top_quintile_selected_count == 30
    assert feature_metric.top_quintile_hit_count == 30
    assert feature_metric.top_quintile_hit_rate == 1.0
    selected_outcomes = [
        row.future_downloads_share
        for row in result.outcomes
        if row.outcome_horizon_months == 1 and row.game_theme == "Theme-4"
    ]
    all_outcomes = [
        row.future_downloads_share
        for row in result.outcomes
        if row.outcome_horizon_months == 1
    ]
    assert feature_metric.future_top_quintile_base_rate == pytest.approx(0.2)
    assert feature_metric.top_quintile_lift == pytest.approx(5.0)
    assert feature_metric.top_quintile_outcome_mean == pytest.approx(sum(selected_outcomes) / 30)
    assert feature_metric.top_quintile_outcome_median == pytest.approx(selected_outcomes[14])
    assert feature_metric.all_eligible_outcome_mean == pytest.approx(sum(all_outcomes) / 150)
    assert feature_metric.all_eligible_outcome_median == pytest.approx(sorted(all_outcomes)[74])

    change_metric = next(
        row
        for row in result.feature_metrics
        if row.outcome_horizon_months == 1
        and row.feature_name == "decision_downloads_share"
        and row.outcome_name == "downloads_share_absolute_change"
    )
    assert change_metric.top_quintile_positive_change_count == 0
    assert change_metric.top_quintile_positive_change_rate == 0.0
    assert change_metric.all_positive_change_count == 0
    assert change_metric.all_positive_change_rate == 0.0


def test_36m_features_are_explicitly_unavailable(five_theme_result: Any) -> None:
    result, _model, _scores = five_theme_result
    unavailable = [
        row
        for row in result.feature_metrics
        if row.feature_name in {"median_normalized_slope_36m", "stability_cv_median_36m"}
    ]

    assert len(unavailable) == 3 * 4 * 2
    assert all(row.eligible_row_count == 0 for row in unavailable)
    assert all(row.coverage_ratio == 0 for row in unavailable)
    assert all(row.mean_spearman is None for row in unavailable)
    assert all(row.top_quintile_cohort_count is None for row in unavailable)
    assert all(row.top_quintile_selected_count is None for row in unavailable)
    assert all(row.top_quintile_hit_count is None for row in unavailable)
    assert all(row.low_sample_warning for row in unavailable)


def test_absent_future_theme_is_zero_filled() -> None:
    payload = _build_payload()
    result, model, scores = _calculate(payload)
    first_outcome = max(
        (row for row in result.outcomes if row.outcome_horizon_months == 1),
        key=lambda row: row.decision_period_start,
    )
    structures = tuple(
        row
        for row in payload.theme_market_structure_metrics
        if not (
            row.game_theme == first_outcome.game_theme
            and row.period_start == first_outcome.outcome_period_start
        )
    )

    absent_result = calculate_theme_launch_window_backtest(
        payload.monthly_totals,
        structures,
        payload.theme_growth_source_metrics,
        scores,
        model.model_summaries,
        model.seasonality_profiles,
        calculated_at=CALCULATED_AT,
    )
    absent = next(row for row in absent_result.outcomes if row.identity == first_outcome.identity)

    assert absent.future_theme_present is False
    assert absent.future_product_count == 0
    assert absent.future_downloads_sum == 0
    assert absent.future_downloads_share == 0
    assert absent.future_revenue_usd_sum == 0
    assert absent.future_revenue_usd_share == 0
    assert absent.downloads_share_change_direction == "down"
    assert absent.revenue_usd_share_change_direction == "down"


def test_present_null_future_metrics_remain_unavailable() -> None:
    payload = _build_payload(null_metric_index=8)
    result, _model, _scores = _calculate(payload)
    null_outcome = next(
        row for row in result.outcomes if row.outcome_period_start == date(2024, 4, 1)
    )

    assert null_outcome.future_theme_present is True
    assert null_outcome.future_product_count == 1
    assert null_outcome.future_downloads_sum is None
    assert null_outcome.future_downloads_share is None
    assert null_outcome.future_revenue_usd_sum is None
    assert null_outcome.future_revenue_usd_share is None
    assert null_outcome.downloads_share_absolute_change is None
    assert null_outcome.revenue_usd_share_absolute_change is None
    assert null_outcome.downloads_share_change_direction == "unavailable"
    assert null_outcome.revenue_usd_share_change_direction == "unavailable"


@pytest.mark.parametrize("source_name", ("structures", "growth_sources", "scores", "summaries"))
def test_missing_decision_source_identity_fails_before_output(
    source_name: str,
) -> None:
    payload = _build_payload()
    baseline, model, scores = _calculate(payload)
    assert baseline.outcomes
    sources: dict[str, Any] = {
        "structures": payload.theme_market_structure_metrics,
        "growth_sources": payload.theme_growth_source_metrics,
        "scores": scores,
        "summaries": model.model_summaries,
    }
    missing_identity = (
        "casual_puzzle_tabletop",
        "monthly",
        date(2024, 6, 1),
        date(2024, 6, 30),
        "Theme-0",
    )
    sources[source_name] = tuple(
        row
        for row in sources[source_name]
        if (
            row.scope_name,
            row.cadence,
            row.period_start,
            row.period_end,
            row.game_theme,
        )
        != missing_identity
    )

    with pytest.raises(BacktestValidationError, match="identities"):
        calculate_theme_launch_window_backtest(
            payload.monthly_totals,
            sources["structures"],
            sources["growth_sources"],
            sources["scores"],
            sources["summaries"],
            model.seasonality_profiles,
            calculated_at=CALCULATED_AT,
        )


def test_seasonality_uses_decision_month_absolute_metric_profiles_only() -> None:
    payload = _build_payload()
    baseline, model, scores = _calculate(payload)
    target = next(
        row
        for row in baseline.outcomes
        if row.decision_downloads_expected_seasonal_index is not None
    )
    target_month = target.outcome_period_start.month
    mutated_profiles = []
    for profile in model.seasonality_profiles:
        if (
            profile.period_start == target.decision_period_start
            and profile.calendar_month == target_month
        ):
            if profile.metric_name == "downloads_sum":
                profile = replace(profile, seasonal_index=1.7, index_deviation=1.7 - 1)
            elif profile.metric_name == "downloads_share":
                profile = replace(profile, seasonal_index=0.2, index_deviation=0.2 - 1)
            elif profile.metric_name == "revenue_usd_sum":
                profile = replace(profile, seasonal_index=2.3, index_deviation=2.3 - 1)
            elif profile.metric_name == "revenue_usd_share":
                profile = replace(profile, seasonal_index=0.4, index_deviation=0.4 - 1)
        elif (
            profile.period_start == target.outcome_period_start
            and profile.calendar_month == target_month
        ):
            profile = replace(profile, seasonal_index=9.0, index_deviation=9.0 - 1)
        mutated_profiles.append(profile)

    result = calculate_theme_launch_window_backtest(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        payload.theme_growth_source_metrics,
        scores,
        model.model_summaries,
        tuple(mutated_profiles),
        calculated_at=CALCULATED_AT,
    )
    mutated = next(row for row in result.outcomes if row.identity == target.identity)

    assert mutated.decision_downloads_expected_seasonal_index == pytest.approx(1.7)
    assert mutated.decision_revenue_usd_expected_seasonal_index == pytest.approx(2.3)
    assert mutated.decision_downloads_expected_seasonal_index != pytest.approx(0.2)
    assert mutated.decision_revenue_usd_expected_seasonal_index != pytest.approx(0.4)


def test_future_model_and_seasonality_rows_cannot_leak_into_prior_outcome() -> None:
    payload = _build_payload()
    baseline, model, scores = _calculate(payload)
    target = baseline.outcomes[0]
    mutated_scores = tuple(
        replace(row, confidence_score=0.0)
        if row.period_start == target.outcome_period_start
        else row
        for row in scores
    )
    mutated_profiles = tuple(
        replace(row, seasonal_index=2.0, index_deviation=1.0)
        if row.period_start == target.outcome_period_start
        else row
        for row in model.seasonality_profiles
    )
    mutated, _unused_model, _unused_scores = _calculate(payload)
    leaked_check = calculate_theme_launch_window_backtest(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        payload.theme_growth_source_metrics,
        mutated_scores,
        model.model_summaries,
        mutated_profiles,
        calculated_at=CALCULATED_AT,
    )

    assert next(row for row in leaked_check.outcomes if row.identity == target.identity) == target
    assert mutated.outcomes[0] == baseline.outcomes[0]


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    (
        ([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], 1.0),
        ([1.0, 2.0, 3.0], [3.0, 2.0, 1.0], -1.0),
        ([1.0, 1.0, 2.0, 3.0], [1.0, 2.0, 2.0, 3.0], 5 / 6),
        ([1.0, 1.0, 1.0], [1.0, 2.0, 3.0], None),
        ([1.0, 2.0, 3.0], [2.0, 2.0, 2.0], None),
    ),
)
def test_spearman_handles_orientation_ties_and_constant_series(
    first: list[float],
    second: list[float],
    expected: float | None,
) -> None:
    result = _spearman(first, second)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_spearman_excludes_null_pairs_and_weights_decision_months_equally(
    five_theme_result: Any,
) -> None:
    baseline = five_theme_result[0]
    first_month = min(row.decision_period_start for row in baseline.outcomes)
    first_rows = [
        row
        for row in baseline.outcomes
        if row.decision_period_start == first_month and row.outcome_horizon_months == 1
    ]
    null_metric = _feature_metric(
        (
            replace(first_rows[0], legacy_6m_momentum_score=0.25),
            replace(first_rows[1], legacy_6m_momentum_score=None),
        ),
        "legacy_6m_momentum_score",
        "future_downloads_share",
        "higher_better",
        "legacy_baseline",
        start=date(2023, 8, 1),
        end=date(2026, 7, 1),
        horizon=1,
        calculated_at=CALCULATED_AT,
        scope_name=first_rows[0].scope_name,
    )
    assert null_metric.candidate_row_count == 2
    assert null_metric.eligible_row_count == 1

    six_result, _model, _scores = _calculate(_build_payload(theme_count=6))
    horizon_rows = [row for row in six_result.outcomes if row.outcome_horizon_months == 1]
    months = sorted({row.decision_period_start for row in horizon_rows})
    first_cohort = [row for row in horizon_rows if row.decision_period_start == months[0]][:5]
    second_cohort = [row for row in horizon_rows if row.decision_period_start == months[1]]
    def _rewrite(row: Any, feature_value: float, outcome_value: float) -> Any:
        absolute_change = outcome_value - row.decision_downloads_share
        relative_change = absolute_change / row.decision_downloads_share
        direction = (
            "unchanged"
            if absolute_change == 0
            else "up"
            if absolute_change > 0
            else "down"
        )
        return replace(
            row,
            legacy_6m_momentum_score=feature_value,
            future_downloads_share=outcome_value,
            downloads_share_absolute_change=absolute_change,
            downloads_share_relative_change=relative_change,
            downloads_share_change_direction=direction,
            future_downloads_share_percentile=0.5,
            future_downloads_share_top_quintile=False,
        )

    rewritten = [
        _rewrite(row, float(index + 1), 0.10 + index * 0.05)
        for index, row in enumerate(first_cohort)
    ]
    rewritten.extend(
        _rewrite(row, float(index + 1), 0.60 - index * 0.05)
        for index, row in enumerate(second_cohort)
    )
    equal_month_metric = _feature_metric(
        tuple(rewritten),
        "legacy_6m_momentum_score",
        "future_downloads_share",
        "higher_better",
        "legacy_baseline",
        start=date(2023, 8, 1),
        end=date(2026, 7, 1),
        horizon=1,
        calculated_at=CALCULATED_AT,
        scope_name=first_rows[0].scope_name,
    )
    assert equal_month_metric.correlation_cohort_count == 2
    assert equal_month_metric.mean_spearman == pytest.approx(0.0)


def test_lower_better_feature_is_oriented_before_correlation(five_theme_result: Any) -> None:
    baseline = five_theme_result[0]
    first_month = min(row.decision_period_start for row in baseline.outcomes)
    rows = [
        replace(
            row,
            decision_downloads_product_hhi=(index + 1) / 10,
        )
        for index, row in enumerate(
            row
            for row in baseline.outcomes
            if row.decision_period_start == first_month and row.outcome_horizon_months == 1
        )
    ]
    metric = _feature_metric(
        tuple(rows),
        "downloads_product_hhi",
        "future_downloads_share",
        "lower_better",
        "competition",
        start=date(2023, 8, 1),
        end=date(2026, 7, 1),
        horizon=1,
        calculated_at=CALCULATED_AT,
        scope_name=rows[0].scope_name,
    )
    assert metric.mean_spearman == pytest.approx(-1.0)


def test_distribution_and_wilson_statistics_cover_edge_cases() -> None:
    assert _percentile_or_none([1.0, 2.0, 3.0, 4.0], 0.25) == pytest.approx(1.75)
    assert _percentile_or_none([1.0, 2.0, 3.0, 4.0], 0.5) == pytest.approx(2.5)
    assert _percentile_or_none([1.0, 2.0, 3.0, 4.0], 0.75) == pytest.approx(3.25)

    zero_success = _wilson_interval(0, 5)
    all_success = _wilson_interval(5, 5)
    partial_success = _wilson_interval(2, 5)
    assert zero_success[0] == 0.0 and zero_success[1] < 1.0
    assert all_success[1] == 1.0 and all_success[0] > 0.0
    assert partial_success[0] < 0.4 < partial_success[1]
    assert _wilson_interval(0, 0) == (None, None)


def test_segment_top_quintile_uses_only_valid_decision_cohorts(five_theme_result: Any) -> None:
    baseline = five_theme_result[0]
    horizon_rows = [row for row in baseline.outcomes if row.outcome_horizon_months == 1]
    months = sorted({row.decision_period_start for row in horizon_rows})
    valid_rows = [row for row in horizon_rows if row.decision_period_start == months[0]]
    invalid_rows = [row for row in horizon_rows if row.decision_period_start == months[1]][:4]
    rows = tuple(replace(row, legacy_is_actionable=True) for row in (*valid_rows, *invalid_rows))
    segments = _calculate_segment_metrics(
        rows,
        start=date(2023, 8, 1),
        end=date(2026, 7, 1),
        calculated_at=CALCULATED_AT,
    )
    metric = next(
        row
        for row in segments
        if row.segment_name == "legacy_actionability"
        and row.segment_value == "actionable"
        and row.outcome_name == "future_downloads_share"
    )
    assert metric.eligible_row_count == 9
    assert metric.future_top_quintile_eligible_count == 5
    assert metric.future_top_quintile_count == 1
    assert metric.future_top_quintile_rate == pytest.approx(0.2)
    assert metric.future_top_quintile_base_rate == pytest.approx(0.2)
    assert metric.future_top_quintile_lift == pytest.approx(1.0)


def test_typed_aggregate_integrity_rejects_unreconciled_new_fields(
    five_theme_result: Any,
) -> None:
    outcome = five_theme_result[0].outcomes[0]
    with pytest.raises(AggregationValidationError, match="between 0 and 1"):
        replace(outcome, future_downloads_share=1.1)

    feature = five_theme_result[0].feature_metrics[0]
    with pytest.raises(AggregationValidationError, match="low_sample_warning"):
        replace(feature, low_sample_warning=not feature.low_sample_warning)

    segment = five_theme_result[0].segment_metrics[0]
    with pytest.raises(AggregationValidationError, match="future_top_quintile_eligible_count"):
        replace(
            segment,
            future_top_quintile_eligible_count=segment.eligible_row_count + 1,
        )
