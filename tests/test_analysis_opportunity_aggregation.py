"""Synthetic unit coverage for AGG-002 pure calculations."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest
from test_analysis_theme_monthly import CALCULATED_AT, _metadata, _row

from src.analysis.opportunity_aggregation import aggregate_theme_opportunity_metrics
from src.storage import SnapshotPeriodKey

SCOPE = "casual_puzzle_tabletop"


def _previous_key() -> SnapshotPeriodKey:
    return SnapshotPeriodKey(
        scope_name=SCOPE,
        cadence="monthly",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )


def test_market_structure_preserves_usd_zero_coverage_publishers_and_age() -> None:
    current = (
        replace(
            _row("app-a", 1, month="2026-07", theme="Theme", units=10, revenue=100),
            game_subgenre="Match 3",
            game_product_model="Free",
            game_art_style="Illustration",
            game_setting="Garden",
            release_date_ww=date(2026, 1, 1),
        ),
        replace(
            _row("app-b", 2, month="2026-07", theme="Theme", units=0, revenue=0),
            game_subgenre="Match 3",
            game_product_model="Paid",
            game_art_style="Illustration",
            game_setting="Garden",
            release_date_ww=date(2026, 8, 1),
        ),
        replace(
            _row("app-c", 101, month="2026-07", theme="Theme", units=None, revenue=300),
            game_subgenre="Unknown",
            game_product_model="Free",
            game_art_style="",
            game_setting="N/A",
            release_date_ww=None,
        ),
        replace(
            _row("app-d", 501, month="2026-07", theme="Theme", units=20, revenue=None),
            game_subgenre=None,
            game_product_model=None,
            game_art_style=None,
            game_setting=None,
            release_date_ww=date(2025, 7, 31),
        ),
        _row("app-market-only", 600, month="2026-07", theme=None, units=10, revenue=50),
    )
    result = aggregate_theme_opportunity_metrics(
        [current],
        {
            "app-a": _metadata("app-a", "Publisher 1"),
            "app-b": _metadata("app-b", "Publisher 1"),
            "app-c": _metadata("app-c", "Publisher 2"),
        },
        calculated_at=CALCULATED_AT,
    )

    structure = result.theme_market_structure_metrics[0]
    assert structure.product_count == 4
    assert structure.product_share == pytest.approx(0.8)
    assert structure.downloads_coverage_count == 3
    assert structure.downloads_sum == pytest.approx(30)
    assert structure.downloads_mean_per_covered_product == pytest.approx(10)
    assert structure.downloads_median_per_covered_product == pytest.approx(10)
    assert structure.downloads_top_1_product_share == pytest.approx(2 / 3)
    assert structure.downloads_product_hhi == pytest.approx(5 / 9)
    assert structure.revenue_usd_sum == pytest.approx(400)
    assert structure.revenue_usd_top_1_product_share == pytest.approx(0.75)
    assert structure.publisher_coverage_count == 3
    assert structure.publisher_count == 2
    assert structure.publisher_downloads_coverage_count == 2
    assert structure.top_1_publisher_downloads_share == pytest.approx(1)
    assert structure.publisher_revenue_usd_coverage_count == 3
    assert structure.top_1_publisher_revenue_usd_share == pytest.approx(0.75)
    assert structure.release_date_ww_coverage_count == 3
    assert structure.release_date_ww_valid_age_count == 2
    assert structure.release_date_ww_future_count == 1
    assert structure.median_product_age_days == pytest.approx(288)

    dimensions = {
        (row.dimension_type, row.dimension_value): row
        for row in result.theme_dimension_monthly_metrics
    }
    assert ("game_subgenre", "Unknown") in dimensions
    assert ("game_art_style", "") in dimensions
    assert dimensions[("game_product_model", "Free")].product_count == 2

    revenue_leaders = [
        row for row in result.theme_representative_games if row.evidence_type == "revenue_leader"
    ]
    assert [row.unified_app_id for row in revenue_leaders] == ["app-c", "app-a", "app-b"]
    assert revenue_leaders[-1].revenue_usd == 0


def test_market_structure_keeps_revenue_as_usd_and_nulls_zero_sum_concentration() -> None:
    large = _row(
        "app-large",
        1,
        month="2026-07",
        theme="Theme",
        units=0,
        revenue=978768951,
    )
    result = aggregate_theme_opportunity_metrics(
        [[large]],
        {},
        calculated_at=CALCULATED_AT,
    )
    structure = result.theme_market_structure_metrics[0]
    assert structure.revenue_usd_sum == 978768951
    assert structure.revenue_usd_top_1_product_share == 1

    zero = _row("app-zero", 1, month="2026-07", theme="Theme", units=0, revenue=0)
    zero_result = aggregate_theme_opportunity_metrics(
        [[zero]],
        {},
        calculated_at=CALCULATED_AT,
    )
    zero_structure = zero_result.theme_market_structure_metrics[0]
    assert zero_structure.downloads_coverage_count == 1
    assert zero_structure.downloads_sum == 0
    assert zero_structure.downloads_top_1_product_share is None
    assert zero_structure.downloads_product_hhi is None


def test_growth_source_decomposes_membership_and_metric_change() -> None:
    current = (
        _row("app-a", 1, month="2026-07", theme="Theme", units=10, revenue=100),
        _row("app-b", 2, month="2026-07", theme="Theme", units=8, revenue=80),
        _row("app-c", 3, month="2026-07", theme="Theme", units=0, revenue=0),
    )
    previous = (
        _row("app-a", 1, month="2026-06", theme="Theme", units=6, revenue=60),
        _row("app-b", 2, month="2026-06", theme="Other", units=10, revenue=100),
        _row("app-old", 3, month="2026-06", theme="Theme", units=2, revenue=20),
    )
    result = aggregate_theme_opportunity_metrics(
        [current],
        {app_id: _metadata(app_id, "Publisher") for app_id in ("app-a", "app-b", "app-c")},
        previous_periods={_previous_key(): previous},
        calculated_at=CALCULATED_AT,
    )
    growth = result.theme_growth_source_metrics[0]
    assert growth.market_new_entry_count == 1
    assert growth.market_returning_product_count == 2
    assert growth.theme_entry_count == 2
    assert growth.theme_exit_count == 1
    assert growth.continuing_theme_product_count == 1
    assert growth.downloads_decomposition_complete is True
    assert growth.downloads_current_sum == pytest.approx(18)
    assert growth.downloads_previous_sum == pytest.approx(8)
    assert growth.downloads_mom_change == pytest.approx(10)
    assert growth.downloads_theme_entry_contribution == pytest.approx(8)
    assert growth.downloads_continuing_contribution == pytest.approx(4)
    assert growth.downloads_theme_exit_contribution == pytest.approx(-2)
    assert growth.downloads_positive_contribution_sum == pytest.approx(12)
    assert growth.downloads_negative_contribution_sum == pytest.approx(-2)


def test_missing_previous_month_leaves_previous_evidence_null() -> None:
    result = aggregate_theme_opportunity_metrics(
        [[_row("app-a", 1, month="2026-07", theme="Theme", units=0, revenue=0)]],
        {},
        calculated_at=CALCULATED_AT,
    )
    growth = result.theme_growth_source_metrics[0]
    assert growth.has_previous_month is False
    assert growth.current_product_count == 1
    assert growth.previous_product_count is None
    assert growth.downloads_current_coverage_count == 1
    assert growth.downloads_current_sum == 0
    assert growth.downloads_previous_coverage_count is None
    assert growth.downloads_decomposition_complete is None
    assert growth.downloads_mom_change is None
    assert all(row.is_market_new_entry is None for row in result.theme_representative_games)


def test_source_order_does_not_change_opportunity_rows() -> None:
    rows = [
        _row("app-a", 1, month="2026-07", theme="Theme", units=10, revenue=10),
        _row("app-b", 2, month="2026-07", theme="Theme", units=10, revenue=10),
    ]
    metadata = {"app-a": _metadata("app-a", "Publisher"), "app-b": _metadata("app-b", "Publisher")}
    first = aggregate_theme_opportunity_metrics([rows], metadata, calculated_at=CALCULATED_AT)
    second = aggregate_theme_opportunity_metrics(
        [list(reversed(rows))], metadata, calculated_at=CALCULATED_AT
    )
    assert first == second
