"""Synthetic unit tests for the explainable monthly trend score."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.analysis.errors import AggregationValidationError
from src.analysis.trend_score import calculate_theme_trend_scores
from src.storage import MonthlyMarketTotal, ThemeMonthlyMetric

CALCULATED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
SCOPE = "casual_puzzle_tabletop"
MONTHS = ("2025-08", "2025-09", "2025-10", "2025-11", "2025-12", "2026-01")


def _period(month: str) -> tuple[date, date]:
    year, month_number = (int(value) for value in month.split("-"))
    start = date(year, month_number, 1)
    if month_number == 12:
        end = date(year, month_number, 31)
    elif month_number in (4, 6, 9, 11):
        end = date(year, month_number, 30)
    elif month_number == 2:
        end = date(year, month_number, 29 if year % 4 == 0 else 28)
    else:
        end = date(year, month_number, 31)
    return start, end


def _total(month: str) -> MonthlyMarketTotal:
    period_start, period_end = _period(month)
    return MonthlyMarketTotal(
        scope_name=SCOPE,
        cadence="monthly",
        period_start=period_start,
        period_end=period_end,
        snapshot_count=10,
        theme_present_count=10,
        theme_missing_count=0,
        metadata_coverage_count=10,
        units_absolute_coverage_count=10,
        units_absolute_sum=100.0,
        revenue_absolute_coverage_count=10,
        revenue_absolute_sum=100.0,
        calculated_at=CALCULATED_AT,
    )


def _metric(
    theme: str,
    month: str,
    *,
    product_share: float,
    units_share: float | None = 0.5,
    revenue_share: float | None = 0.5,
    new_entry_share: float | None = 0.1,
    product_count: int = 5,
    median_rank: float = 100.0,
    publisher_count: int = 2,
) -> ThemeMonthlyMetric:
    period_start, period_end = _period(month)
    has_previous_month = new_entry_share is not None
    new_entry_count = (
        round(product_count * new_entry_share) if new_entry_share is not None else None
    )
    return ThemeMonthlyMetric(
        scope_name=SCOPE,
        cadence="monthly",
        period_start=period_start,
        period_end=period_end,
        game_theme=theme,
        product_count=product_count,
        product_share=product_share,
        top_100_count=product_count,
        top_500_count=product_count,
        average_rank=median_rank,
        median_rank=median_rank,
        units_absolute_coverage_count=(product_count if units_share is not None else 0),
        units_absolute_sum=(units_share * 100 if units_share is not None else None),
        units_absolute_share=units_share,
        revenue_absolute_coverage_count=(product_count if revenue_share is not None else 0),
        revenue_absolute_sum=(revenue_share * 100 if revenue_share is not None else None),
        revenue_absolute_share=revenue_share,
        has_previous_month=has_previous_month,
        new_entry_count=new_entry_count,
        returning_product_count=(
            product_count - new_entry_count if new_entry_count is not None else None
        ),
        new_entry_share=new_entry_share,
        publisher_coverage_count=product_count,
        publisher_count=publisher_count,
        top_publisher_product_share=0.4,
        calculated_at=CALCULATED_AT,
    )


def _history() -> tuple[list[MonthlyMarketTotal], list[ThemeMonthlyMetric]]:
    totals = [_total(month) for month in MONTHS]
    metrics: list[ThemeMonthlyMetric] = []
    growth_shares = {
        "2025-09": 0.2,
        "2025-10": 0.3,
        "2025-11": 0.3,
        "2025-12": 0.4,
        "2026-01": 0.5,
    }
    growth_ranks = {
        "2025-09": 100.0,
        "2025-10": 90.0,
        "2025-11": 80.0,
        "2025-12": 70.0,
        "2026-01": 60.0,
    }
    growth_units = {
        "2025-09": 0.1,
        "2025-10": 0.2,
        "2025-11": 0.3,
        "2025-12": 0.4,
        "2026-01": 0.5,
    }
    for month in MONTHS:
        if month in growth_shares:
            metrics.append(
                _metric(
                    "Growth",
                    month,
                    product_share=growth_shares[month],
                    units_share=growth_units[month],
                    revenue_share=growth_units[month],
                    median_rank=growth_ranks[month],
                )
            )
        metrics.append(
            _metric(
                "Flat",
                month,
                product_share=0.5,
                units_share=0.5,
                revenue_share=0.5,
                median_rank=80.0,
            )
        )
        metrics.append(
            _metric("Unknown", month, product_share=0.5, median_rank=100.0)
        )
        metrics.append(
            _metric("Small", month, product_share=0.4, product_count=4, median_rank=120.0)
        )
        if month in ("2025-12", "2026-01"):
            metrics.append(
                _metric("Short", month, product_share=0.5, median_rank=100.0)
            )
    return totals, metrics


def test_six_month_features_zero_fill_absent_theme_and_preserve_raw_label() -> None:
    totals, metrics = _history()
    scores = calculate_theme_trend_scores(totals, metrics, calculated_at=CALCULATED_AT)

    january = {
        row.game_theme: row
        for row in scores
        if row.period_start == date(2026, 1, 1)
    }
    growth = january["Growth"]
    assert growth.is_actionable is True
    assert growth.active_months_6m == 5
    assert growth.product_share_gain_3m == pytest.approx(0.2333333333)
    assert growth.product_share_acceleration == pytest.approx(-0.05)
    assert growth.median_rank_improvement == pytest.approx(25.0)
    assert growth.units_absolute_overindex == pytest.approx(1.0)
    assert growth.revenue_absolute_overindex == pytest.approx(1.0)
    assert growth.trend_rank == 1
    assert january["Unknown"].is_actionable is False
    assert january["Unknown"].exclusion_reason == "non_actionable_source_label"
    assert january["Small"].exclusion_reason == "insufficient_latest_product_count"
    assert january["Short"].exclusion_reason == "insufficient_active_history"


def test_percentiles_ties_and_single_actionable_theme_are_deterministic() -> None:
    totals = [_total(month) for month in MONTHS]
    metrics = [
        _metric("Only", month, product_share=0.5, units_share=None, revenue_share=None)
        for month in MONTHS
    ]
    score = calculate_theme_trend_scores(totals, metrics, calculated_at=CALCULATED_AT)[0]
    assert score.growth_score == pytest.approx(50.0)
    assert score.acceleration_score == pytest.approx(50.0)
    assert score.new_product_score == pytest.approx(50.0)
    assert score.concentration_penalty == pytest.approx(50.0)
    assert score.confidence_score < 100.0


def test_missing_calendar_month_is_not_zero_filled() -> None:
    totals = [_total(month) for month in MONTHS if month != "2025-10"]
    metrics = [
        _metric("Growth", month, product_share=0.5)
        for month in MONTHS
        if month != "2025-10"
    ]
    with pytest.raises(AggregationValidationError, match="missing calendar month"):
        calculate_theme_trend_scores(totals, metrics, calculated_at=CALCULATED_AT)


def test_unavailable_new_entry_metric_is_non_actionable_and_scores_are_null() -> None:
    totals = [_total(month) for month in MONTHS]
    metrics = [
        _metric(
            "No Entries",
            month,
            product_share=0.5,
            new_entry_share=(None if month in ("2025-11", "2025-12", "2026-01") else 0.1),
        )
        for month in MONTHS
    ]
    score = calculate_theme_trend_scores(totals, metrics, calculated_at=CALCULATED_AT)[0]
    assert score.is_actionable is False
    assert score.exclusion_reason == "insufficient_metric_coverage"
    assert score.growth_score is None
    assert score.trend_score is None
    assert score.trend_rank is None
