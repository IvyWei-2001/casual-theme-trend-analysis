"""Synthetic tests for MODEL-002 horizons, seasonality, and lifecycle evidence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime
from math import isclose

import pytest
from test_analysis_theme_monthly import _metadata, _row

from src.analysis.errors import AggregationValidationError
from src.analysis.model_v2 import _lifecycle_stage, calculate_theme_model_metrics
from src.analysis.opportunity_aggregation import aggregate_theme_opportunity_metrics
from src.storage import MonthlyMarketTotal

CALCULATED_AT = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
SCOPE = "casual_puzzle_tabletop"
THEME = "Theme"
BASE_MONTH = date(2023, 8, 1)
FLAT_SERIES = (0.200, 0.201, 0.202, 0.203, 0.204, 0.205)
CONSTANT_POSITIVE_SERIES = (0.20,) * 6


def _month_start(index: int) -> date:
    month_number = BASE_MONTH.year * 12 + BASE_MONTH.month - 1 + index
    year, month_zero_based = divmod(month_number, 12)
    return date(year, month_zero_based + 1, 1)


def _period_end(period_start: date) -> date:
    if period_start.month == 12:
        next_start = date(period_start.year + 1, 1, 1)
    else:
        next_start = date(period_start.year, period_start.month + 1, 1)
    return next_start.fromordinal(next_start.toordinal() - 1)


def _total(period_start: date, *, revenue: float | None = 100.0) -> MonthlyMarketTotal:
    return MonthlyMarketTotal(
        scope_name=SCOPE,
        cadence="monthly",
        period_start=period_start,
        period_end=_period_end(period_start),
        snapshot_count=1,
        theme_present_count=1,
        theme_missing_count=0,
        metadata_coverage_count=1,
        units_absolute_coverage_count=1,
        units_absolute_sum=100.0,
        revenue_absolute_coverage_count=1 if revenue is not None else 0,
        revenue_absolute_sum=revenue,
        calculated_at=CALCULATED_AT,
    )


def _structure(
    index: int,
    *,
    theme: str = THEME,
    product_share: float = 1.0,
    downloads_share: float | None = 1.0,
    revenue_share: float | None = 1.0,
    downloads: float | None = 100.0,
    revenue: float | None = 100.0,
):
    month = _month_start(index)
    source_row = _row(
        f"app-{index}",
        1,
        month=f"{month.year:04d}-{month.month:02d}",
        theme=theme,
        units=downloads,
        revenue=revenue,
    )
    result = aggregate_theme_opportunity_metrics(
        [[source_row]],
        {source_row.unified_app_id: _metadata(source_row.unified_app_id, "Publisher")},
        calculated_at=CALCULATED_AT,
    )
    return replace(
        result.theme_market_structure_metrics[0],
        product_share=product_share,
        downloads_share=downloads_share,
        revenue_usd_share=revenue_share,
    )


def _history(
    count: int,
    *,
    product_shares: Iterable[float] | None = None,
    downloads_shares: Iterable[float | None] | None = None,
    revenue_shares: Iterable[float | None] | None = None,
    downloads_values: Iterable[float | None] | None = None,
    revenue_values: Iterable[float | None] | None = None,
    present_from: int = 0,
    theme: str = THEME,
) -> tuple[tuple[MonthlyMarketTotal, ...], tuple[object, ...]]:
    product_values = tuple(product_shares or (1.0 for _ in range(count)))
    download_share_values = tuple(downloads_shares or (1.0 for _ in range(count)))
    revenue_share_values = tuple(revenue_shares or (1.0 for _ in range(count)))
    download_values = tuple(downloads_values or (100.0 for _ in range(count)))
    revenue_values = tuple(revenue_values or (100.0 for _ in range(count)))
    totals = tuple(
        _total(
            _month_start(index),
            revenue=revenue_values[index],
        )
        for index in range(count)
    )
    structures = tuple(
        _structure(
            index,
            theme=theme,
            product_share=product_values[index],
            downloads_share=download_share_values[index],
            revenue_share=revenue_share_values[index],
            downloads=download_values[index],
            revenue=revenue_values[index],
        )
        for index in range(present_from, count)
    )
    return totals, structures


def _horizon(result, *, target: date, horizon: int, metric: str):
    return next(
        row
        for row in result.horizon_metrics
        if row.period_start == target
        and row.horizon_month_count == horizon
        and row.metric_name == metric
    )


def _summary(result, *, target: date):
    return next(row for row in result.model_summaries if row.period_start == target)


def test_horizon_rows_require_complete_market_history() -> None:
    for count, expected_horizons in (
        (5, ()),
        (6, (6,)),
        (11, (6,)),
        (12, (6, 12)),
        (35, (6, 12)),
        (36, (6, 12, 36)),
    ):
        totals, structures = _history(count)
        result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
        assert {row.horizon_month_count for row in result.horizon_metrics} == set(
            expected_horizons
        )
        assert len(result.horizon_metrics) == 6 * sum(
            max(0, count - horizon + 1) for horizon in (6, 12, 36)
        )


def test_absent_history_zero_fills_but_present_null_stays_unavailable() -> None:
    totals, structures = _history(6, present_from=5)
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    target = _month_start(5)
    product_row = _horizon(result, target=target, horizon=6, metric="product_count")
    assert product_row.metric_coverage_count == 6
    assert product_row.first_value == 0.0
    assert product_row.latest_value == 1.0

    totals, structures = _history(
        6,
        downloads_shares=(1.0, 1.0, 1.0, 1.0, 1.0, None),
        downloads_values=(100.0, 100.0, 100.0, 100.0, 100.0, None),
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    downloads_row = _horizon(result, target=target, horizon=6, metric="downloads_sum")
    assert downloads_row.metric_coverage_count == 5
    assert downloads_row.is_complete is False
    assert downloads_row.linear_slope is None
    assert downloads_row.maximum_drawdown is None

    totals, structures = _history(
        6,
        revenue_shares=(1.0, 1.0, 1.0, 1.0, 1.0, None),
        revenue_values=(100.0, 100.0, 100.0, 100.0, 100.0, None),
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    revenue_row = _horizon(result, target=target, horizon=6, metric="revenue_usd_sum")
    assert revenue_row.metric_coverage_count == 5
    assert revenue_row.is_complete is False
    assert revenue_row.normalized_slope is None


def test_horizon_formulas_use_population_statistics_and_latest_peak_tie() -> None:
    totals, structures = _history(
        6,
        downloads_values=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
        revenue_values=(2.0, 4.0, 6.0, 8.0, 10.0, 12.0),
        product_shares=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6),
        downloads_shares=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6),
        revenue_shares=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6),
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    row = _horizon(result, target=_month_start(5), horizon=6, metric="downloads_sum")
    assert row.mean_value == pytest.approx(3.5)
    assert row.median_value == pytest.approx(3.5)
    assert row.minimum_value == pytest.approx(1.0)
    assert row.maximum_value == pytest.approx(6.0)
    assert row.absolute_change == pytest.approx(5.0)
    assert row.relative_change == pytest.approx(5.0)
    assert row.linear_slope == pytest.approx(1.0)
    assert row.normalized_slope == pytest.approx(1 / 3.5)
    assert row.r_squared == pytest.approx(1.0)
    assert row.latest_to_mean_ratio == pytest.approx(6 / 3.5)
    assert row.transition_coverage_count == 5
    assert row.positive_change_count == 5
    assert row.positive_change_ratio == pytest.approx(1.0)
    assert row.standard_deviation == pytest.approx(1.7078251277)
    assert row.coefficient_of_variation == pytest.approx(1.7078251277 / 3.5)
    assert row.maximum_drawdown == pytest.approx(0.0)
    assert row.months_since_peak == 0

    totals, structures = _history(
        6,
        downloads_values=(10.0, 5.0, 8.0, 4.0, 4.0, 6.0),
        revenue_values=(10.0, 5.0, 8.0, 4.0, 4.0, 6.0),
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    drawdown = _horizon(result, target=_month_start(5), horizon=6, metric="downloads_sum")
    assert drawdown.maximum_drawdown == pytest.approx(0.6)
    assert drawdown.months_since_peak == 5

    totals, structures = _history(
        6,
        downloads_values=(0.0, 2.0, 3.0, 4.0, 5.0, 6.0),
        revenue_values=(0.0, 2.0, 3.0, 4.0, 5.0, 6.0),
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    first_zero = _horizon(result, target=_month_start(5), horizon=6, metric="downloads_sum")
    assert first_zero.relative_change is None

    totals, structures = _history(
        6,
        downloads_values=(1.0, 3.0, 2.0, 3.0, 2.0, 3.0),
        revenue_values=(1.0, 3.0, 2.0, 3.0, 2.0, 3.0),
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    tied = _horizon(result, target=_month_start(5), horizon=6, metric="downloads_sum")
    assert tied.months_since_peak == 0


def test_constant_and_zero_series_keep_undefined_fit_fields_and_zero_drawdown() -> None:
    totals, structures = _history(
        6,
        downloads_values=(0.0,) * 6,
        revenue_values=(0.0,) * 6,
        product_shares=(0.0,) * 6,
        downloads_shares=(0.0,) * 6,
        revenue_shares=(0.0,) * 6,
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    row = _horizon(result, target=_month_start(5), horizon=6, metric="downloads_sum")
    assert row.r_squared is None
    assert row.normalized_slope is None
    assert row.coefficient_of_variation is None
    assert row.latest_to_mean_ratio is None
    assert row.maximum_drawdown == 0.0


@pytest.mark.parametrize("row_kind", ("horizon", "summary"))
@pytest.mark.parametrize("bad_timestamp", (datetime(2026, 8, 10, 12, 0), "not-a-timestamp"))
def test_model_rows_require_timezone_aware_calculated_at(
    row_kind: str,
    bad_timestamp: object,
) -> None:
    totals, structures = _history(6)
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    row = result.horizon_metrics[0] if row_kind == "horizon" else result.model_summaries[0]

    with pytest.raises(AggregationValidationError, match="calculated_at must be timezone-aware"):
        replace(row, calculated_at=bad_timestamp)  # type: ignore[arg-type]


def test_transition_coverage_uses_only_adjacent_numeric_pairs() -> None:
    totals, structures = _history(
        6,
        downloads_shares=(1.0, None, 1.0, 1.0, 1.0, 1.0),
        downloads_values=(1.0, None, 1.0, 2.0, 2.0, 3.0),
        revenue_values=(1.0,) * 6,
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    row = _horizon(result, target=_month_start(5), horizon=6, metric="downloads_sum")
    assert row.transition_count == 5
    assert row.transition_coverage_count == 3
    assert row.positive_change_count == 2
    assert row.negative_change_count == 0
    assert row.unchanged_change_count == 1
    assert row.positive_change_ratio == pytest.approx(2 / 3)


def test_direction_uses_only_share_metrics_and_ignores_noisy_nonflat_evidence() -> None:
    totals, structures = _history(
        6,
        product_shares=(0.1, 0.9, 0.1, 0.9, 0.1, 0.9),
        downloads_shares=FLAT_SERIES,
        revenue_shares=FLAT_SERIES,
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    summary = _summary(result, target=_month_start(5))
    noisy_product = _horizon(
        result,
        target=_month_start(5),
        horizon=6,
        metric="product_share",
    )
    assert noisy_product.normalized_slope is not None
    assert noisy_product.r_squared is None or noisy_product.r_squared < 0.20
    assert summary.direction_6m == "flat"
    assert summary.direction_evidence_count_6m == 3
    assert summary.direction_12m == "insufficient_history"
    assert summary.stability_band_6m == "stable"


def test_constant_positive_share_series_are_flat_and_available_evidence() -> None:
    totals, structures = _history(
        6,
        product_shares=CONSTANT_POSITIVE_SERIES,
        downloads_shares=CONSTANT_POSITIVE_SERIES,
        revenue_shares=CONSTANT_POSITIVE_SERIES,
    )
    summary = _summary(
        calculate_theme_model_metrics(totals, structures, CALCULATED_AT),
        target=_month_start(5),
    )
    assert summary.direction_6m == "flat"
    assert summary.direction_evidence_count_6m == 3


def test_constant_positive_twelve_month_history_is_mature() -> None:
    series = (0.20,) * 12
    totals, structures = _history(
        12,
        product_shares=series,
        downloads_shares=series,
        revenue_shares=series,
        present_from=0,
    )
    summary = _summary(
        calculate_theme_model_metrics(totals, structures, CALCULATED_AT),
        target=_month_start(11),
    )
    assert summary.direction_6m == "flat"
    assert summary.direction_12m == "flat"
    assert summary.lifecycle_stage == "mature"


def test_flat_noisy_and_unavailable_metrics_are_mixed_with_two_evidence() -> None:
    totals, structures = _history(
        6,
        product_shares=CONSTANT_POSITIVE_SERIES,
        downloads_shares=(0.1, 0.9, 0.1, 0.9, 0.1, 0.9),
        revenue_shares=(None,) * 6,
    )
    summary = _summary(
        calculate_theme_model_metrics(totals, structures, CALCULATED_AT),
        target=_month_start(5),
    )
    assert summary.direction_6m == "mixed"
    assert summary.direction_evidence_count_6m == 2


@pytest.mark.parametrize(
    ("product", "downloads", "revenue", "expected_direction", "expected_evidence"),
    (
        (
            (0.1, 0.2, 0.3, 0.4, 0.5, 0.6),
            (0.1, 0.9, 0.1, 0.9, 0.1, 0.9),
            (None,) * 6,
            "mixed",
            2,
        ),
        (
            (0.1, 0.9, 0.1, 0.9, 0.1, 0.9),
            (0.1, 0.9, 0.1, 0.9, 0.1, 0.9),
            (None,) * 6,
            "mixed",
            2,
        ),
        (
            (0.1, 0.2, 0.3, 0.4, 0.5, 0.6),
            (0.1, 0.9, 0.1, 0.9, 0.1, 0.9),
            (0.9, 0.1, 0.9, 0.1, 0.9, 0.1),
            "mixed",
            3,
        ),
        (
            (0.1, 0.2, 0.3, 0.4, 0.5, 0.6),
            (None,) * 6,
            (None,) * 6,
            "insufficient_history",
            1,
        ),
        (
            FLAT_SERIES,
            FLAT_SERIES,
            (0.1, 0.9, 0.1, 0.9, 0.1, 0.9),
            "flat",
            3,
        ),
    ),
)
def test_direction_evidence_counts_noisy_metrics_as_available(
    product: tuple[float | None, ...],
    downloads: tuple[float | None, ...],
    revenue: tuple[float | None, ...],
    expected_direction: str,
    expected_evidence: int,
) -> None:
    totals, structures = _history(
        6,
        product_shares=product,
        downloads_shares=downloads,
        revenue_shares=revenue,
    )
    summary = _summary(
        calculate_theme_model_metrics(totals, structures, CALCULATED_AT),
        target=_month_start(5),
    )
    assert summary.direction_6m == expected_direction
    assert summary.direction_evidence_count_6m == expected_evidence


@pytest.mark.parametrize(
    ("product", "downloads", "revenue", "expected_direction"),
    (
        ((0.1, 0.2, 0.3, 0.4, 0.5, 0.6),) * 3 + ("up",),
        ((0.6, 0.5, 0.4, 0.3, 0.2, 0.1),) * 3 + ("down",),
        (FLAT_SERIES,) * 3 + ("flat",),
        (
            (0.1, 0.2, 0.3, 0.4, 0.5, 0.6),
            (0.6, 0.5, 0.4, 0.3, 0.2, 0.1),
            (0.2,) * 6,
            "mixed",
        ),
        ((0.1, 0.2, 0.3, 0.4, 0.5, 0.6), (None,) * 6, (None,) * 6, "insufficient_history"),
    ),
)
def test_all_composite_directions_are_explicit(
    product: tuple[float, ...],
    downloads: tuple[float | None, ...],
    revenue: tuple[float | None, ...],
    expected_direction: str,
) -> None:
    totals, structures = _history(
        6,
        product_shares=product,
        downloads_shares=downloads,
        revenue_shares=revenue,
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    assert _summary(result, target=_month_start(5)).direction_6m == expected_direction


@pytest.mark.parametrize(
    ("series", "expected_band"),
    (
        ((0.2,) * 6, "stable"),
        ((0.1, 0.2, 0.1, 0.2, 0.1, 0.2), "variable"),
        ((0.01, 0.5, 0.01, 0.5, 0.01, 0.5), "volatile"),
    ),
)
def test_stability_bands_follow_median_share_cv(
    series: tuple[float, ...],
    expected_band: str,
) -> None:
    totals, structures = _history(
        6,
        product_shares=series,
        downloads_shares=series,
        revenue_shares=series,
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    assert _summary(result, target=_month_start(5)).stability_band_6m == expected_band


def test_empty_unknown_and_na_labels_remain_target_groups() -> None:
    totals, structures = _history(6)
    structures = structures[:-1] + (
        _structure(5, theme=""),
        _structure(5, theme="Unknown"),
        _structure(5, theme="N/A"),
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    assert {row.game_theme for row in result.model_summaries[-3:]} == {"", "Unknown", "N/A"}


@pytest.mark.parametrize(
    ("series", "present_from", "expected_stage"),
    (
        ((0.1,) * 6 + (0.1, 0.2, 0.3, 0.4, 0.5, 0.6), 6, "emerging"),
        ((0.1, 0.101, 0.102, 0.103, 0.104, 0.105, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7), 0, "accelerating"),
        ((0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.61, 0.62, 0.63, 0.64, 0.65, 0.66), 0, "growing"),
        (FLAT_SERIES + (0.206, 0.207, 0.208, 0.209, 0.210, 0.211), 0, "mature"),
    ),
)
def test_lifecycle_policy_order_is_deterministic(
    series: tuple[float, ...],
    present_from: int,
    expected_stage: str,
) -> None:
    totals, structures = _history(
        12,
        product_shares=series,
        downloads_shares=series,
        revenue_shares=series,
        present_from=present_from,
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    summary = _summary(result, target=_month_start(11))
    assert summary.lifecycle_stage == expected_stage


@pytest.mark.parametrize(
    ("kwargs", "expected_stage"),
    (
        (
            {
                "direction_6m": "insufficient_history",
                "direction_12m": "insufficient_history",
            },
            "insufficient_history",
        ),
        (
            {
                "direction_6m": "up",
                "direction_12m": "up",
                "first_active_left_censored": False,
                "months_since_first_active": 5,
            },
            "emerging",
        ),
        (
            {
                "direction_6m": "up",
                "direction_12m": "up",
                "median_slope_6m": 0.02,
                "median_slope_12m": 0.01,
            },
            "accelerating",
        ),
        (
            {"direction_6m": "up", "direction_12m": "flat"},
            "recovering",
        ),
        (
            {"direction_6m": "flat", "direction_12m": "down"},
            "declining",
        ),
        (
            {
                "direction_6m": "flat",
                "direction_12m": "flat",
                "active_months_12m": 12,
                "stability_band_12m": "stable",
            },
            "mature",
        ),
        (
            {"direction_6m": "flat", "direction_12m": "up"},
            "growing",
        ),
        (
            {"direction_6m": "flat", "direction_12m": "mixed"},
            "mixed",
        ),
    ),
)
def test_each_lifecycle_value_is_reachable_in_documented_order(
    kwargs: dict[str, object],
    expected_stage: str,
) -> None:
    defaults: dict[str, object] = {
        "direction_6m": "flat",
        "direction_12m": "flat",
        "median_slope_6m": None,
        "median_slope_12m": None,
        "first_active_left_censored": True,
        "months_since_first_active": None,
        "active_months_12m": 0,
        "stability_band_12m": "insufficient_history",
    }
    defaults.update(kwargs)
    assert _lifecycle_stage(**defaults) == expected_stage  # type: ignore[arg-type]


def test_seasonality_uses_only_recent_complete_blocks_and_has_twelve_rows_per_profile() -> None:
    pattern = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0)
    values = pattern * 3
    totals, structures = _history(
        36,
        downloads_values=values,
        revenue_values=values,
        product_shares=tuple(value / 12 for value in pattern) * 3,
        downloads_shares=tuple(value / 12 for value in pattern) * 3,
        revenue_shares=tuple(value / 12 for value in pattern) * 3,
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    target_24 = _month_start(23)
    profile_24 = [row for row in result.seasonality_profiles if row.period_start == target_24]
    assert len(profile_24) == 6 * 12
    assert {row.history_month_count for row in profile_24} == {24}
    assert {row.complete_year_count for row in profile_24} == {2}
    assert isclose(
        sum(row.seasonal_index for row in profile_24 if row.metric_name == "downloads_sum") / 12,
        1.0,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )
    downloads_profile = [row for row in profile_24 if row.metric_name == "downloads_sum"]
    assert [row.calendar_month for row in downloads_profile if row.is_peak_month] == [7]
    assert [row.calendar_month for row in downloads_profile if row.is_trough_month] == [8]

    target_36 = _month_start(35)
    profile_36 = [row for row in result.seasonality_profiles if row.period_start == target_36]
    assert len(profile_36) == 6 * 12
    assert {row.history_month_count for row in profile_36} == {36}
    assert {row.complete_year_count for row in profile_36} == {3}

    totals_25, structures_25 = _history(
        25,
        downloads_values=values[:25],
        revenue_values=values[:25],
    )
    result_25 = calculate_theme_model_metrics(totals_25, structures_25, CALCULATED_AT)
    profile_25 = [
        row for row in result_25.seasonality_profiles if row.period_start == _month_start(24)
    ]
    assert {row.history_month_count for row in profile_25} == {24}
    assert {row.history_start for row in profile_25} == {_month_start(1)}

    totals_48, structures_48 = _history(48)
    result_48 = calculate_theme_model_metrics(totals_48, structures_48, CALCULATED_AT)
    profile_48 = [
        row for row in result_48.seasonality_profiles if row.period_start == _month_start(47)
    ]
    assert {row.history_month_count for row in profile_48} == {36}
    assert {row.history_start for row in profile_48} == {_month_start(12)}


def test_seasonality_requires_valid_nonzero_blocks() -> None:
    totals, structures = _history(
        24,
        downloads_values=(0.0,) * 24,
        revenue_values=(0.0,) * 24,
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    assert not [
        row
        for row in result.seasonality_profiles
        if row.metric_name in {"downloads_sum", "revenue_usd_sum"}
    ]

    totals, structures = _history(
        24,
        downloads_values=(100.0,) * 12 + (None,) * 12,
        revenue_values=(100.0,) * 12 + (None,) * 12,
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    assert not [
        row
        for row in result.seasonality_profiles
        if row.metric_name in {"downloads_sum", "revenue_usd_sum"}
    ]


def test_seasonality_distinguishes_selected_complete_years_from_valid_observations() -> None:
    pattern = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0)
    values = pattern + (None,) * 12 + pattern
    totals, structures = _history(
        36,
        downloads_values=values,
        revenue_values=values,
    )
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    target = _month_start(35)
    downloads_profile = [
        row
        for row in result.seasonality_profiles
        if row.period_start == target and row.metric_name == "downloads_sum"
    ]
    assert len(downloads_profile) == 12
    assert {row.history_month_count for row in downloads_profile} == {36}
    assert {row.complete_year_count for row in downloads_profile} == {3}
    assert {row.observation_count for row in downloads_profile} == {2}
    assert _summary(result, target=target).seasonality_complete_year_count == 3

    totals_24, structures_24 = _history(
        24,
        downloads_values=pattern + (None,) * 12,
        revenue_values=pattern + (None,) * 12,
    )
    result_24 = calculate_theme_model_metrics(totals_24, structures_24, CALCULATED_AT)
    assert not [
        row
        for row in result_24.seasonality_profiles
        if row.metric_name in {"downloads_sum", "revenue_usd_sum"}
    ]


@pytest.mark.parametrize(
    ("history_month_count", "bad_complete_year_count"),
    ((36, 2), (24, 3)),
)
def test_seasonality_profile_requires_exact_complete_year_count(
    history_month_count: int,
    bad_complete_year_count: int,
) -> None:
    totals, structures = _history(history_month_count)
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    profile = next(
        row
        for row in result.seasonality_profiles
        if row.history_month_count == history_month_count
    )
    with pytest.raises(AggregationValidationError, match="complete_year_count"):
        replace(profile, complete_year_count=bad_complete_year_count)


@pytest.mark.parametrize(
    ("history_month_count", "bad_complete_year_count"),
    ((36, 2), (24, 3)),
)
def test_model_summary_requires_exact_complete_year_count(
    history_month_count: int,
    bad_complete_year_count: int,
) -> None:
    totals, structures = _history(history_month_count)
    result = calculate_theme_model_metrics(totals, structures, CALCULATED_AT)
    summary = _summary(result, target=_month_start(history_month_count - 1))
    with pytest.raises(AggregationValidationError, match="seasonality year count"):
        replace(
            summary,
            seasonality_complete_year_count=bad_complete_year_count,
        )

def test_historical_target_is_unchanged_when_future_months_change() -> None:
    base_totals, base_structures = _history(36)
    future_totals, future_structures = _history(
        36,
        downloads_values=(100.0,) * 24 + (1000.0,) * 12,
        revenue_values=(100.0,) * 24 + (1000.0,) * 12,
    )
    base_result = calculate_theme_model_metrics(base_totals, base_structures, CALCULATED_AT)
    future_result = calculate_theme_model_metrics(future_totals, future_structures, CALCULATED_AT)
    target = _month_start(23)
    assert _summary(base_result, target=target) == _summary(future_result, target=target)
    assert [row for row in base_result.horizon_metrics if row.period_start == target] == [
        row for row in future_result.horizon_metrics if row.period_start == target
    ]
    assert [row for row in base_result.seasonality_profiles if row.period_start == target] == [
        row for row in future_result.seasonality_profiles if row.period_start == target
    ]
