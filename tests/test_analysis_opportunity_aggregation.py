"""Synthetic unit coverage for AGG-002 pure calculations."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest
from test_analysis_theme_monthly import CALCULATED_AT, _metadata, _row

from src.analysis.errors import AggregationValidationError
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


@pytest.mark.parametrize(
    ("metric", "structure_share", "dimension_share"),
    (
        ("downloads", "downloads_share", "downloads_share_within_theme"),
        ("revenue_usd", "revenue_usd_share", "revenue_usd_share_within_theme"),
    ),
)
def test_zero_metric_shares_distinguish_observed_zero_from_unavailable(
    metric: str,
    structure_share: str,
    dimension_share: str,
) -> None:
    target_zero = _row(
        "app-zero",
        1,
        month="2026-07",
        theme="Theme",
        units=0 if metric == "downloads" else None,
        revenue=0 if metric == "revenue_usd" else None,
    )
    target_positive = _row(
        "app-positive",
        2,
        month="2026-07",
        theme="Theme",
        units=10 if metric == "downloads" else None,
        revenue=10 if metric == "revenue_usd" else None,
    )
    target_zero = replace(target_zero, game_subgenre="Zero")
    target_positive = replace(target_positive, game_subgenre="Positive")
    market_only = _row(
        "app-market-only",
        3,
        month="2026-07",
        theme=None,
        units=10 if metric == "downloads" else None,
        revenue=10 if metric == "revenue_usd" else None,
    )

    structure_result = aggregate_theme_opportunity_metrics(
        [[target_zero, market_only]],
        {},
        calculated_at=CALCULATED_AT,
    )
    structure = structure_result.theme_market_structure_metrics[0]
    assert getattr(structure, structure_share) == pytest.approx(0)
    result = aggregate_theme_opportunity_metrics(
        [[target_zero, target_positive, market_only]],
        {},
        calculated_at=CALCULATED_AT,
    )
    zero_dimension = next(
        row
        for row in result.theme_dimension_monthly_metrics
        if row.dimension_type == "game_subgenre" and row.dimension_value == "Zero"
    )
    assert getattr(zero_dimension, dimension_share) == pytest.approx(0)
    market_dimension_share = dimension_share.replace("within_theme", "within_market")
    assert getattr(zero_dimension, market_dimension_share) == pytest.approx(0)

    zero_only = _row(
        "app-zero-only",
        1,
        month="2026-07",
        theme="Theme",
        units=0 if metric == "downloads" else None,
        revenue=0 if metric == "revenue_usd" else None,
    )
    zero_only_result = aggregate_theme_opportunity_metrics(
        [[zero_only]],
        {},
        calculated_at=CALCULATED_AT,
    )
    zero_only_structure = zero_only_result.theme_market_structure_metrics[0]
    assert getattr(zero_only_structure, structure_share) is None

    unavailable = _row(
        "app-unavailable",
        1,
        month="2026-07",
        theme="Theme",
        units=None if metric == "downloads" else 1,
        revenue=None if metric == "revenue_usd" else 1,
    )
    unavailable_result = aggregate_theme_opportunity_metrics(
        [[unavailable]],
        {},
        calculated_at=CALCULATED_AT,
    )
    unavailable_structure = unavailable_result.theme_market_structure_metrics[0]
    assert getattr(unavailable_structure, f"{metric}_coverage_count") == 0
    assert getattr(unavailable_structure, f"{metric}_sum") is None
    assert getattr(unavailable_structure, structure_share) is None


def test_representative_evidence_covers_all_types_and_uses_fixed_deterministic_limit() -> None:
    current = [
        _row("app-a", 1, month="2026-07", theme="Theme", units=100, revenue=2),
        _row("app-b", 2, month="2026-07", theme="Theme", units=100, revenue=1),
        _row("app-c", 3, month="2026-07", theme="Theme", units=90, revenue=300),
        _row("app-d", 101, month="2026-07", theme="Theme", units=80, revenue=300),
        _row("app-e", 501, month="2026-07", theme="Theme", units=70, revenue=50),
        _row("app-f", 502, month="2026-07", theme="Theme", units=60, revenue=40),
    ]
    previous = [
        _row("app-a", 1, month="2026-06", theme="Theme", units=90, revenue=1),
        _row("app-b", 2, month="2026-06", theme="Theme", units=100, revenue=10),
        _row("app-d", 101, month="2026-06", theme="Theme", units=90, revenue=310),
        _row("app-e", 500, month="2026-06", theme="Theme", units=80, revenue=60),
        _row("app-x", 100, month="2026-06", theme="Theme", units=20, revenue=20),
    ]
    result = aggregate_theme_opportunity_metrics(
        [list(reversed(current))],
        {},
        previous_periods={_previous_key(): previous},
        calculated_at=CALCULATED_AT,
    )
    representatives = result.theme_representative_games
    by_type = {
        evidence_type: [row for row in representatives if row.evidence_type == evidence_type]
        for evidence_type in (
            "downloads_leader",
            "revenue_leader",
            "market_new_entry_downloads_leader",
            "market_new_entry_revenue_leader",
            "downloads_growth_leader",
            "revenue_growth_leader",
        )
    }
    assert set(by_type) == {
        "downloads_leader",
        "revenue_leader",
        "market_new_entry_downloads_leader",
        "market_new_entry_revenue_leader",
        "downloads_growth_leader",
        "revenue_growth_leader",
    }
    assert [row.unified_app_id for row in by_type["downloads_leader"]] == [
        "app-a",
        "app-b",
        "app-c",
    ]
    assert [row.unified_app_id for row in by_type["revenue_leader"]] == [
        "app-c",
        "app-d",
        "app-e",
    ]
    assert [row.unified_app_id for row in by_type["market_new_entry_downloads_leader"]] == [
        "app-c",
        "app-f",
    ]
    assert [row.unified_app_id for row in by_type["market_new_entry_revenue_leader"]] == [
        "app-c",
        "app-f",
    ]
    assert [row.unified_app_id for row in by_type["downloads_growth_leader"]] == [
        "app-c",
        "app-f",
        "app-a",
    ]
    assert [row.unified_app_id for row in by_type["revenue_growth_leader"]] == [
        "app-c",
        "app-f",
        "app-a",
    ]
    assert all(len(rows) <= 3 for rows in by_type.values())
    assert {
        row.evidence_type for row in representatives if row.unified_app_id == "app-c"
    } == set(by_type)
    assert all(
        getattr(
            row,
            "downloads_change"
            if row.evidence_type.startswith("downloads")
            else "revenue_usd_change",
        )
        > 0
        for row in representatives
        if row.evidence_type.endswith("growth_leader")
    )

    growth = result.theme_growth_source_metrics[0]
    assert (
        growth.top_100_entry_count,
        growth.top_100_exit_count,
        growth.top_100_retained_count,
    ) == (
        1,
        1,
        2,
    )
    assert growth.top_100_turnover_rate == pytest.approx(1 / 3)
    assert (
        growth.top_500_entry_count,
        growth.top_500_exit_count,
        growth.top_500_retained_count,
    ) == (
        1,
        2,
        3,
    )
    assert growth.top_500_turnover_rate == pytest.approx(1 / 4)
    assert growth.downloads_top_10_retained_count == 4
    assert growth.downloads_top_10_retention_rate == pytest.approx(4 / 6)
    assert growth.revenue_usd_top_10_retained_count == 4
    assert growth.revenue_usd_top_10_retention_rate == pytest.approx(4 / 6)
    assert growth.downloads_top_1_positive_contribution_share == pytest.approx(90 / 160)
    assert growth.downloads_top_3_positive_contribution_share == pytest.approx(1)
    assert growth.downloads_top_10_positive_contribution_share == pytest.approx(1)
    assert growth.downloads_positive_contribution_sum == pytest.approx(160)
    assert growth.downloads_market_new_entry_positive_contribution_share == pytest.approx(150 / 160)
    assert growth.downloads_continuing_positive_contribution_share == pytest.approx(10 / 160)


def test_growth_and_retention_rates_are_null_for_empty_current_sets() -> None:
    current = _row("app-a", 501, month="2026-07", theme="Theme", units=None, revenue=None)
    previous = _row("app-a", 501, month="2026-06", theme="Theme", units=10, revenue=10)
    result = aggregate_theme_opportunity_metrics(
        [[current]],
        {},
        previous_periods={_previous_key(): [previous]},
        calculated_at=CALCULATED_AT,
    )
    growth = result.theme_growth_source_metrics[0]
    assert growth.top_100_turnover_rate is None
    assert growth.top_500_turnover_rate is None
    assert growth.downloads_top_10_retention_rate is None
    assert growth.revenue_usd_top_10_retention_rate is None


@pytest.mark.parametrize(
    ("current_units", "previous_units"),
    ((None, 10), (10, None)),
)
def test_present_null_growth_metric_leaves_decomposition_fields_null(
    current_units: float | None,
    previous_units: float | None,
) -> None:
    current = _row("app-a", 1, month="2026-07", theme="Theme", units=current_units, revenue=1)
    previous = _row("app-a", 1, month="2026-06", theme="Theme", units=previous_units, revenue=1)
    result = aggregate_theme_opportunity_metrics(
        [[current]],
        {},
        previous_periods={_previous_key(): [previous]},
        calculated_at=CALCULATED_AT,
    )
    growth = result.theme_growth_source_metrics[0]
    assert growth.downloads_decomposition_complete is False
    assert growth.downloads_mom_change is None
    assert growth.downloads_positive_contribution_sum is None
    assert growth.downloads_top_1_positive_contribution_share is None


def test_no_previous_month_emits_no_growth_representatives() -> None:
    result = aggregate_theme_opportunity_metrics(
        [[_row("app-a", 1, month="2026-07", theme="Theme", units=10, revenue=10)]],
        {},
        calculated_at=CALCULATED_AT,
    )
    assert not any(
        row.evidence_type.endswith("growth_leader")
        for row in result.theme_representative_games
    )


def test_representative_model_accepts_ranks_one_to_three_and_rejects_rank_four() -> None:
    result = aggregate_theme_opportunity_metrics(
        [[_row("app-a", 1, month="2026-07", theme="Theme", units=10, revenue=10)]],
        {},
        calculated_at=CALCULATED_AT,
    )
    representative = result.theme_representative_games[0]
    assert [replace(representative, evidence_rank=rank).evidence_rank for rank in (1, 2, 3)] == [
        1,
        2,
        3,
    ]
    with pytest.raises(AggregationValidationError, match="evidence_rank"):
        replace(representative, evidence_rank=4)


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
