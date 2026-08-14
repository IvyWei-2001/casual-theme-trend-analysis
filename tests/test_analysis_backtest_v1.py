"""Pure synthetic regression tests for the leakage-safe BACKTEST-001 analysis."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest
from test_analysis_theme_monthly import _metadata, _row

from src.analysis.backtest_v1 import calculate_theme_launch_window_backtest
from src.analysis.errors import BacktestValidationError
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
    first_outcome = result.outcomes[0]
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
    _baseline, model, scores = _calculate(payload)
    sources: dict[str, Any] = {
        "structures": payload.theme_market_structure_metrics,
        "growth_sources": payload.theme_growth_source_metrics,
        "scores": scores,
        "summaries": model.model_summaries,
    }
    if source_name == "structures":
        missing_identity = (
            scores[0].scope_name,
            scores[0].cadence,
            scores[0].period_start,
            scores[0].period_end,
            scores[0].game_theme,
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
    else:
        sources[source_name] = tuple(sources[source_name][1:])

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
