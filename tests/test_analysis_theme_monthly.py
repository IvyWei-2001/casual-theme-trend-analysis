"""Pure synthetic tests for AGG-001 monthly theme calculations."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.analysis.errors import AggregationValidationError
from src.analysis.theme_monthly import aggregate_monthly_theme_metrics
from src.storage import AppMetadataRow, MarketSnapshotRow, SnapshotPeriodKey

CALCULATED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _row(
    app_id: str,
    rank: int,
    *,
    month: str,
    theme: str | None,
    units: float | None,
    revenue: float | None,
) -> MarketSnapshotRow:
    year, month_number = (int(value) for value in month.split("-"))
    period_start = date(year, month_number, 1)
    period_end = date(
        year,
        month_number,
        28,
    )
    if month_number == 2:
        period_end = date(year, month_number, 29 if year % 4 == 0 else 28)
    elif month_number in (4, 6, 9, 11):
        period_end = date(year, month_number, 30)
    else:
        period_end = date(year, month_number, 31)
    return MarketSnapshotRow(
        scope_name="casual_puzzle_tabletop",
        cadence="monthly",
        period_start=period_start,
        period_end=period_end,
        rank_position=rank,
        source_app_id=app_id,
        unified_app_id=app_id,
        scope_country="WW",
        device_type="total",
        category=7012,
        data_model="DM_2025_Q2",
        source_date=datetime(year, month_number, 15, tzinfo=UTC),
        source_country=None,
        current_units_value=None,
        units_absolute=units,
        comparison_units_value=None,
        units_delta=None,
        units_transformed_delta=None,
        current_revenue_value=None,
        revenue_absolute=revenue,
        comparison_revenue_value=None,
        revenue_delta=None,
        revenue_transformed_delta=None,
        absolute=None,
        delta=None,
        transformed_delta=None,
        game_theme=theme,
        game_genre="Puzzle",
        game_subgenre=None,
        game_product_model=None,
        game_art_style=None,
        game_setting=None,
        earliest_release_date=None,
        release_date_ww=None,
        publisher_country=None,
        most_popular_country_by_revenue=None,
        is_unified_source_value=None,
        collected_at=CALCULATED_AT,
    )


def _metadata(
    app_id: str,
    publisher: str | None,
) -> AppMetadataRow:
    return AppMetadataRow(
        unified_app_id=app_id,
        name=None,
        publisher_display_name=publisher,
        publisher_resolution_source="publisher_name" if publisher else "unavailable",
        android_app_id=None,
        ios_app_id=None,
        fetched_at=CALCULATED_AT,
    )


def test_monthly_metrics_preserve_raw_themes_and_use_actual_population_denominators() -> None:
    current = (
        _row("app-a", 1, month="2026-07", theme="Unknown", units=10, revenue=100),
        _row("app-b", 100, month="2026-07", theme="Unknown", units=20, revenue=None),
        _row("app-c", 500, month="2026-07", theme="N/A", units=30, revenue=300),
        _row("app-d", 501, month="2026-07", theme="", units=None, revenue=400),
        _row("app-e", 600, month="2026-07", theme=None, units=40, revenue=500),
    )
    previous = (
        _row("app-a", 1, month="2026-06", theme="Unknown", units=None, revenue=None),
        _row("app-x", 2, month="2026-06", theme="Unknown", units=None, revenue=None),
    )

    result = aggregate_monthly_theme_metrics(
        [current],
        {
            "app-a": _metadata("app-a", "Publisher 1"),
            "app-b": _metadata("app-b", "Publisher 1"),
            "app-c": _metadata("app-c", "Publisher 2"),
            "app-d": _metadata("app-d", None),
        },
        previous_periods={
            SnapshotPeriodKey(
                scope_name="casual_puzzle_tabletop",
                cadence="monthly",
                period_start=date(2026, 6, 1),
                period_end=date(2026, 6, 30),
            ): previous
        },
        calculated_at=CALCULATED_AT,
    )

    total = result.monthly_totals[0]
    assert total.snapshot_count == 5
    assert total.theme_present_count == 4
    assert total.theme_missing_count == 1
    assert total.metadata_coverage_count == 4
    assert total.units_absolute_coverage_count == 4
    assert total.units_absolute_sum == 100.0
    assert total.revenue_absolute_coverage_count == 4
    assert total.revenue_absolute_sum == 1300.0

    metrics = {row.game_theme: row for row in result.theme_metrics}
    assert set(metrics) == {"Unknown", "N/A", ""}
    unknown = metrics["Unknown"]
    assert unknown.product_count == 2
    assert unknown.product_share == pytest.approx(0.4)
    assert unknown.top_100_count == 2
    assert unknown.top_500_count == 2
    assert unknown.average_rank == pytest.approx(50.5)
    assert unknown.median_rank == pytest.approx(50.5)
    assert unknown.units_absolute_sum == 30.0
    assert unknown.units_absolute_share == pytest.approx(0.3)
    assert unknown.revenue_absolute_sum == 100.0
    assert unknown.revenue_absolute_share == pytest.approx(100 / 1300)
    assert unknown.has_previous_month is True
    assert unknown.new_entry_count == 1
    assert unknown.returning_product_count == 1
    assert unknown.new_entry_share == pytest.approx(0.5)
    assert unknown.publisher_coverage_count == 2
    assert unknown.publisher_count == 1
    assert unknown.top_publisher_product_share == 1.0
    assert metrics[""].publisher_coverage_count == 0
    assert metrics[""].top_publisher_product_share is None


def test_missing_previous_month_leaves_new_entry_fields_null() -> None:
    rows = (
        _row("app-a", 1, month="2026-07", theme="Decoration", units=0, revenue=None),
        _row("app-b", 2, month="2026-07", theme=None, units=0, revenue=None),
    )
    result = aggregate_monthly_theme_metrics(
        [rows],
        {},
        calculated_at=CALCULATED_AT,
    )

    total = result.monthly_totals[0]
    metric = result.theme_metrics[0]
    assert total.units_absolute_sum == 0.0
    assert total.revenue_absolute_sum is None
    assert metric.units_absolute_share is None
    assert metric.revenue_absolute_share is None
    assert metric.has_previous_month is False
    assert metric.new_entry_count is None
    assert metric.returning_product_count is None
    assert metric.new_entry_share is None


def test_invalid_rank_and_metadata_types_fail_before_derived_rows_are_returned() -> None:
    rows = (
        _row("app-a", 1, month="2026-07", theme="Decoration", units=1, revenue=1),
        _row("app-b", 1, month="2026-07", theme="Decoration", units=1, revenue=1),
    )
    with pytest.raises(AggregationValidationError, match="rank"):
        aggregate_monthly_theme_metrics([rows], {}, calculated_at=CALCULATED_AT)

    with pytest.raises(AggregationValidationError, match="publisher metadata"):
        aggregate_monthly_theme_metrics(
            [[rows[0]]],
            {"app-a": object()},  # type: ignore[dict-item]
            calculated_at=CALCULATED_AT,
        )
