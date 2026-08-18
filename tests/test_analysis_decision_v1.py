"""Focused synthetic contract tests for the DECISION-001 pure policy layer."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from test_analysis_theme_monthly import _metadata, _row

from src.analysis.decision_models import (
    DECISION_POLICY_VERSION,
    CategoryEvidenceLimitation,
    CategoryFitState,
    CompetitiveStructureRiskBand,
    DecisionConfidence,
    DecisionRecommendation,
    GrowthQualityState,
    LaunchWindowEvidenceState,
    MarketSizeBand,
    RiskCode,
)
from src.analysis.decision_v1 import (
    _classify_competitive_risk,
    _classify_market_size,
    _launch_window_state,
    _percentiles_for_values,
    _recommend,
    calculate_theme_decisions,
)
from src.analysis.errors import DecisionValidationError
from src.analysis.model_v2_models import MODEL_POLICY_VERSION, ThemeModelSummary
from src.analysis.opportunity_aggregation import aggregate_theme_opportunity_metrics
from src.analysis.opportunity_models import ThemeMarketStructureMetric
from src.storage import MonthlyMarketTotal

CALCULATED_AT = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
TARGET_MONTH = date(2026, 7, 1)
SCOPE = "casual_puzzle_tabletop"


def _period_end(month_start: date) -> date:
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    return next_month.fromordinal(next_month.toordinal() - 1)


def _summary(
    theme: str,
    *,
    lifecycle: str = "growing",
    volatile: bool = False,
    has_12m_history: bool = True,
) -> ThemeModelSummary:
    history_start = date(2025, 8, 1) if has_12m_history else date(2026, 2, 1)
    history_count = 12 if has_12m_history else 6
    return ThemeModelSummary(
        scope_name=SCOPE,
        cadence="monthly",
        period_start=TARGET_MONTH,
        period_end=_period_end(TARGET_MONTH),
        game_theme=theme,
        model_policy_version=MODEL_POLICY_VERSION,
        history_start=history_start,
        history_month_count=history_count,
        first_active_month=history_start,
        first_active_left_censored=True,
        months_since_first_active=history_count - 1,
        active_months_to_date=history_count,
        has_6m_history=True,
        has_12m_history=has_12m_history,
        has_36m_history=False,
        active_months_6m=6,
        active_months_12m=12 if has_12m_history else None,
        active_months_36m=None,
        direction_6m="up",
        direction_12m="up" if has_12m_history else "insufficient_history",
        direction_36m="insufficient_history",
        direction_evidence_count_6m=3,
        direction_evidence_count_12m=3 if has_12m_history else 0,
        direction_evidence_count_36m=0,
        median_normalized_slope_6m=0.1,
        median_normalized_slope_12m=0.1 if has_12m_history else None,
        median_normalized_slope_36m=None,
        median_r_squared_6m=0.5,
        median_r_squared_12m=0.5 if has_12m_history else None,
        median_r_squared_36m=None,
        stability_cv_median_6m=0.1,
        stability_cv_median_12m=0.1 if has_12m_history else None,
        stability_cv_median_36m=None,
        stability_band_6m="volatile" if volatile else "stable",
        stability_band_12m="volatile" if volatile else "stable",
        stability_band_36m="insufficient_history",
        lifecycle_stage=lifecycle,
        seasonality_history_month_count=None,
        seasonality_complete_year_count=None,
        downloads_peak_calendar_month=None,
        downloads_trough_calendar_month=None,
        downloads_seasonality_amplitude=None,
        revenue_usd_peak_calendar_month=None,
        revenue_usd_trough_calendar_month=None,
        revenue_usd_seasonality_amplitude=None,
        calculated_at=CALCULATED_AT,
    )


def _aggregate(
    themes: tuple[str, ...],
    *,
    missing_downloads: frozenset[str] = frozenset(),
    missing_revenue: frozenset[str] = frozenset(),
    subgenres: dict[str, str | None] | None = None,
) -> tuple[MonthlyMarketTotal, tuple[ThemeMarketStructureMetric, ...], object]:
    current = []
    previous = []
    metadata = {}
    for index, theme in enumerate(sorted(themes)):
        app_id = f"current-{index}"
        previous_id = f"previous-{index}"
        current_row = _row(
            app_id,
            index + 1,
            month="2026-07",
            theme=theme,
            units=None if theme in missing_downloads else 100 + index,
            revenue=None if theme in missing_revenue else 100 + index,
        )
        previous_row = _row(
            previous_id,
            index + 1,
            month="2026-06",
            theme=theme,
            units=None if theme in missing_downloads else 50 + index,
            revenue=None if theme in missing_revenue else 50 + index,
        )
        if subgenres is not None:
            current_row = replace(
                current_row,
                game_subgenre=subgenres.get(theme),
            )
            previous_row = replace(
                previous_row,
                game_subgenre=subgenres.get(theme),
            )
        current.append(current_row)
        previous.append(previous_row)
        metadata[app_id] = _metadata(app_id, f"Publisher {index}")
        metadata[previous_id] = _metadata(previous_id, f"Publisher {index}")
    aggregate = aggregate_theme_opportunity_metrics(
        [previous, current],
        metadata,
        calculated_at=CALCULATED_AT,
    )
    total = next(row for row in aggregate.monthly_totals if row.period_start == TARGET_MONTH)
    structures = tuple(
        row
        for row in aggregate.theme_market_structure_metrics
        if row.period_start == TARGET_MONTH
    )
    return total, structures, aggregate


def _decision(
    themes: tuple[str, ...] = ("Theme",),
    *,
    structures: tuple[ThemeMarketStructureMetric, ...] | None = None,
    summaries: tuple[ThemeModelSummary, ...] | None = None,
    missing_downloads: frozenset[str] = frozenset(),
    missing_revenue: frozenset[str] = frozenset(),
    growth_override: tuple | None = None,
):
    total, default_structures, aggregate = _aggregate(
        themes,
        missing_downloads=missing_downloads,
        missing_revenue=missing_revenue,
    )
    target_structures = structures or default_structures
    target_summaries = summaries or tuple(_summary(theme) for theme in themes)
    target_growth = tuple(
        row
        for row in aggregate.theme_growth_source_metrics
        if row.period_start == TARGET_MONTH
    )
    if growth_override is not None:
        target_growth = growth_override
    target_dimensions = tuple(
        row
        for row in aggregate.theme_dimension_monthly_metrics
        if row.period_start == TARGET_MONTH
    )
    target_representatives = tuple(
        row
        for row in aggregate.theme_representative_games
        if row.period_start == TARGET_MONTH
    )
    return calculate_theme_decisions(
        total,
        target_structures,
        target_growth,
        target_summaries,
        target_dimensions,
        target_representatives,
        calculated_at=CALCULATED_AT,
    )


def _category_decision(*, revenue: bool = False, include_observed: bool = True):
    current_specs = [
        ("valid-a", 1, "Validated", 100, 100 if revenue else None),
        ("valid-b", 2, "Validated", 80, 80 if revenue else None),
    ]
    if include_observed:
        current_specs.append(("observed", 3, "Observed", 10, 10 if revenue else None))
    previous_specs = [
        ("previous-valid-a", 1, "Validated", 60, 60 if revenue else None),
        ("previous-valid-b", 2, "Validated", 50, 50 if revenue else None),
    ]
    current = []
    previous = []
    metadata = {}
    for app_id, rank, subgenre, units, revenue_value in current_specs:
        current.append(
            replace(
                _row(
                    app_id,
                    rank,
                    month="2026-07",
                    theme="Theme",
                    units=units,
                    revenue=revenue_value,
                ),
                game_subgenre=subgenre,
            )
        )
        metadata[app_id] = _metadata(app_id, "Publisher")
    for app_id, rank, subgenre, units, revenue_value in previous_specs:
        previous.append(
            replace(
                _row(
                    app_id,
                    rank,
                    month="2026-06",
                    theme="Theme",
                    units=units,
                    revenue=revenue_value,
                ),
                game_subgenre=subgenre,
            )
        )
        metadata[app_id] = _metadata(app_id, "Publisher")
    aggregate = aggregate_theme_opportunity_metrics(
        [previous, current],
        metadata,
        calculated_at=CALCULATED_AT,
    )
    target_total = next(row for row in aggregate.monthly_totals if row.period_start == TARGET_MONTH)
    target_structures = tuple(
        row
        for row in aggregate.theme_market_structure_metrics
        if row.period_start == TARGET_MONTH
    )
    target_growth = tuple(
        row
        for row in aggregate.theme_growth_source_metrics
        if row.period_start == TARGET_MONTH
    )
    target_dimensions = tuple(aggregate.theme_dimension_monthly_metrics)
    validated_previous = next(
        row
        for row in target_dimensions
        if row.period_start == date(2026, 6, 1) and row.dimension_value == "Validated"
    )
    target_dimensions = (*target_dimensions, replace(
        validated_previous,
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
    ))
    target_representatives = tuple(
        row
        for row in aggregate.theme_representative_games
        if row.period_start == TARGET_MONTH
    )
    return calculate_theme_decisions(
        target_total,
        target_structures,
        target_growth,
        (_summary("Theme"),),
        target_dimensions,
        target_representatives,
        calculated_at=CALCULATED_AT,
    )


def test_average_rank_percentiles_preserve_ties_nulls_zero_and_boundaries() -> None:
    percentiles = _percentiles_for_values(
        {"zero-a": 0, "zero-b": 0, "middle": 0.5, "high": 1, "missing": None}
    )
    assert percentiles["zero-a"] == pytest.approx(1 / 6)
    assert percentiles["zero-b"] == pytest.approx(1 / 6)
    assert percentiles["middle"] == pytest.approx(2 / 3)
    assert percentiles["high"] == pytest.approx(1.0)
    assert "missing" not in percentiles
    assert _percentiles_for_values({"one": 0})["one"] == pytest.approx(0.5)

    assert _classify_market_size((0.80, 0.80, 0.49)) == MarketSizeBand.STRONG
    assert _classify_market_size((0.50, 0.50, 0.49)) == MarketSizeBand.MODERATE
    assert _classify_market_size((0.49, 0.49, None)) == MarketSizeBand.LIMITED
    assert _classify_market_size((0.80, None)) == MarketSizeBand.INSUFFICIENT_EVIDENCE


def test_every_lifecycle_maps_to_the_frozen_growth_quality_state() -> None:
    expected = {
        "growing": GrowthQualityState.BALANCED_GROWTH,
        "accelerating": GrowthQualityState.OBSERVABLE_REVENUE_GROWTH_SUPPORT,
        "mature": GrowthQualityState.DURABLE_ESTABLISHED,
        "emerging": GrowthQualityState.EXPERIMENTAL_EMERGING,
        "recovering": GrowthQualityState.CAUTIOUS_RECOVERY,
        "declining": GrowthQualityState.DECLINING,
        "mixed": GrowthQualityState.MIXED_OR_UNCERTAIN,
        "insufficient_history": GrowthQualityState.INSUFFICIENT_EVIDENCE,
    }
    for lifecycle, growth_quality in expected.items():
        summary = _summary(
            "Theme",
            lifecycle=lifecycle,
            has_12m_history=lifecycle != "insufficient_history",
        )
        result = _decision(summaries=(summary,))
        assert result.summaries[0].growth_quality_state == growth_quality


def test_every_competitive_boundary_is_explicit() -> None:
    assert (
        _classify_competitive_risk((0.80, 0.80, None, None))
        == CompetitiveStructureRiskBand.HIGHER_STRUCTURAL_RISK
    )
    assert (
        _classify_competitive_risk((0.50, 0.50, 0.49, None))
        == CompetitiveStructureRiskBand.LOWER_STRUCTURAL_RISK
    )
    assert (
        _classify_competitive_risk((0.80, 0.50, None, None))
        == CompetitiveStructureRiskBand.MIXED_STRUCTURAL_RISK
    )
    assert (
        _classify_competitive_risk((0.80, None, None, None))
        == CompetitiveStructureRiskBand.INSUFFICIENT_EVIDENCE
    )


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            dict(
                market_size=MarketSizeBand.STRONG,
                growth_quality=GrowthQualityState.BALANCED_GROWTH,
                competitive_band=CompetitiveStructureRiskBand.MIXED_STRUCTURAL_RISK,
                confidence=DecisionConfidence.MEDIUM,
                lifecycle="growing",
                non_actionable=False,
                volatile=False,
            ),
            DecisionRecommendation.PRIORITIZE_VALIDATION,
        ),
        (
            dict(
                market_size=MarketSizeBand.STRONG,
                growth_quality=GrowthQualityState.EXPERIMENTAL_EMERGING,
                competitive_band=CompetitiveStructureRiskBand.MIXED_STRUCTURAL_RISK,
                confidence=DecisionConfidence.MEDIUM,
                lifecycle="emerging",
                non_actionable=False,
                volatile=False,
            ),
            DecisionRecommendation.SMALL_EXPERIMENT,
        ),
        (
            dict(
                market_size=MarketSizeBand.LIMITED,
                growth_quality=GrowthQualityState.DECLINING,
                competitive_band=CompetitiveStructureRiskBand.MIXED_STRUCTURAL_RISK,
                confidence=DecisionConfidence.MEDIUM,
                lifecycle="declining",
                non_actionable=False,
                volatile=False,
            ),
            DecisionRecommendation.DEPRIORITIZE,
        ),
        (
            dict(
                market_size=MarketSizeBand.STRONG,
                growth_quality=GrowthQualityState.BALANCED_GROWTH,
                competitive_band=CompetitiveStructureRiskBand.HIGHER_STRUCTURAL_RISK,
                confidence=DecisionConfidence.HIGH,
                lifecycle="growing",
                non_actionable=False,
                volatile=False,
            ),
            DecisionRecommendation.MONITOR,
        ),
        (
            dict(
                market_size=MarketSizeBand.STRONG,
                growth_quality=GrowthQualityState.BALANCED_GROWTH,
                competitive_band=CompetitiveStructureRiskBand.MIXED_STRUCTURAL_RISK,
                confidence=DecisionConfidence.HIGH,
                lifecycle="mixed",
                non_actionable=False,
                volatile=False,
            ),
            DecisionRecommendation.MONITOR,
        ),
        (
            dict(
                market_size=MarketSizeBand.STRONG,
                growth_quality=GrowthQualityState.BALANCED_GROWTH,
                competitive_band=CompetitiveStructureRiskBand.MIXED_STRUCTURAL_RISK,
                confidence=DecisionConfidence.HIGH,
                lifecycle="growing",
                non_actionable=True,
                volatile=False,
            ),
            DecisionRecommendation.MONITOR,
        ),
    ],
)
def test_recommendation_gate_order_is_deterministic(kwargs, expected) -> None:
    assert _recommend(**kwargs) == expected


def test_low_hhi_new_entry_turnover_seasonality_and_trend_evidence_cannot_upgrade() -> None:
    baseline = _recommend(
        market_size=MarketSizeBand.MODERATE,
        growth_quality=GrowthQualityState.BALANCED_GROWTH,
        competitive_band=CompetitiveStructureRiskBand.MIXED_STRUCTURAL_RISK,
        confidence=DecisionConfidence.MEDIUM,
        lifecycle="growing",
        non_actionable=False,
        volatile=False,
    )
    lower_risk = _recommend(
        market_size=MarketSizeBand.MODERATE,
        growth_quality=GrowthQualityState.BALANCED_GROWTH,
        competitive_band=CompetitiveStructureRiskBand.LOWER_STRUCTURAL_RISK,
        confidence=DecisionConfidence.MEDIUM,
        lifecycle="growing",
        non_actionable=False,
        volatile=False,
    )
    assert baseline == lower_risk == DecisionRecommendation.SELECTIVE_VALIDATION

    structure = _decision().summaries[0]
    assert structure.recommendation == DecisionRecommendation.SELECTIVE_VALIDATION
    assert structure.growth_quality_state == GrowthQualityState.BALANCED_GROWTH
    assert (
        structure.competitive_structure_risk_band
        != CompetitiveStructureRiskBand.HIGHER_STRUCTURAL_RISK
    )
    assert structure.current_market_new_entry_share is not None
    assert structure.current_top_500_turnover_rate is not None

    altered_summary = replace(
        _summary("Theme"),
        median_normalized_slope_6m=99.0,
        median_normalized_slope_12m=99.0,
        median_normalized_slope_36m=99.0,
        downloads_seasonality_amplitude=99.0,
        revenue_usd_seasonality_amplitude=99.0,
    )
    altered_growth = _aggregate(("Theme",))[2].theme_growth_source_metrics[-1]
    altered_growth = replace(
        altered_growth,
        market_new_entry_share=1.0,
        top_500_turnover_rate=1.0,
    )
    altered = _decision(
        summaries=(altered_summary,),
        growth_override=(altered_growth,),
    )
    assert altered.summaries[0].recommendation == structure.recommendation
    assert altered.summaries[0].downloads_trend_slope_36m == 99.0
    assert altered.summaries[0].downloads_seasonality_amplitude == 99.0
    assert altered.summaries[0].current_market_new_entry_share == 1.0
    assert altered.summaries[0].current_top_500_turnover_rate == 1.0


def test_observable_revenue_limitations_remain_with_complete_field_coverage() -> None:
    result = _decision()
    codes = {row.risk_code for row in result.risks}
    assert RiskCode.OBSERVABLE_REVENUE_ONLY in codes
    assert RiskCode.MONETIZATION_TYPE_UNVERIFIED in codes
    assert RiskCode.OBSERVABLE_REVENUE_COVERAGE_GAP not in codes


def test_category_fit_uses_exact_thresholds_and_does_not_require_observable_revenue() -> None:
    result = _category_decision()
    validated = next(row for row in result.category_fits if row.game_subgenre == "Validated")
    observed = next(row for row in result.category_fits if row.game_subgenre == "Observed")
    assert validated.fit_state == CategoryFitState.VALIDATED_FIT
    assert validated.observation_month_count == 3
    assert validated.target_month_product_count == 2
    assert validated.target_month_downloads_coverage_count == 2
    assert validated.target_month_downloads_sum == 180
    assert validated.target_month_observable_revenue_usd_sum is None
    assert (
        CategoryEvidenceLimitation.OBSERVABLE_REVENUE_UNAVAILABLE
        in validated.evidence_limitations
    )
    assert observed.fit_state == CategoryFitState.OBSERVED_FIT
    assert observed.target_month_product_count == 1
    assert result.summaries[0].category_fit_summary == CategoryFitState.VALIDATED_FIT


def test_migration_requires_validated_source_and_observed_target_only() -> None:
    result = _category_decision()
    assert len(result.migration_hypotheses) == 1
    hypothesis = result.migration_hypotheses[0]
    assert hypothesis.validated_source_game_subgenre == "Validated"
    assert hypothesis.target_observed_game_subgenre == "Observed"
    assert hypothesis.is_validated_fit is False
    assert hypothesis.requires_product_validation is True
    assert RiskCode.MIGRATION_NOT_VALIDATED in hypothesis.risk_limitation_codes
    assert RiskCode.MIGRATION_NOT_VALIDATED in {row.risk_code for row in result.risks}


def test_no_unobserved_migration_target_and_empty_migration_output_are_valid() -> None:
    result = _category_decision(include_observed=False)
    assert result.migration_hypotheses == ()
    assert not any(
        row.target_observed_game_subgenre == "Unobserved"
        for row in result.migration_hypotheses
    )


def test_confidence_high_medium_low_boundaries() -> None:
    assert _category_decision(revenue=True).summaries[0].confidence == DecisionConfidence.HIGH
    assert _decision().summaries[0].confidence == DecisionConfidence.MEDIUM
    assert (
        _decision(
            missing_downloads=frozenset({"Theme"}),
            missing_revenue=frozenset({"Theme"}),
        ).summaries[0].confidence
        == DecisionConfidence.LOW
    )


def test_volatile_lifecycle_concentration_and_seasonality_are_normalized_risks() -> None:
    volatile = _decision(summaries=(_summary("Theme", volatile=True),))
    assert RiskCode.VOLATILE_EVIDENCE in {row.risk_code for row in volatile.risks}
    assert volatile.summaries[0].recommendation == DecisionRecommendation.MONITOR

    themes = tuple(f"Theme {index}" for index in range(6))
    total, structures, aggregate = _aggregate(themes)
    ordered_structures = tuple(sorted(structures, key=lambda row: row.game_theme))
    concentration_values = (0.1, 0.2, 0.3, 0.4, 0.8, 1.0)
    concentration_structures = tuple(
        replace(
            row,
            downloads_product_hhi=concentration_values[index],
            revenue_usd_product_hhi=concentration_values[index],
        )
        for index, row in enumerate(ordered_structures)
    )
    summaries = tuple(_summary(theme) for theme in themes)
    growth = tuple(
        row
        for row in aggregate.theme_growth_source_metrics
        if row.period_start == TARGET_MONTH
    )
    ordered_growth = tuple(sorted(growth, key=lambda row: row.game_theme))
    concentration_growth = tuple(
        replace(
            row,
            downloads_top_10_positive_contribution_share=concentration_values[index],
            revenue_usd_top_10_positive_contribution_share=concentration_values[index],
        )
        for index, row in enumerate(ordered_growth)
    )
    result = calculate_theme_decisions(
        total,
        concentration_structures,
        concentration_growth,
        summaries,
        calculated_at=CALCULATED_AT,
    )
    high_concentration = next(
        row for row in result.summaries if row.game_theme == "Theme 4"
    )
    assert high_concentration.competitive_structure_risk_band == (
        CompetitiveStructureRiskBand.HIGHER_STRUCTURAL_RISK
    )
    assert high_concentration.recommendation != DecisionRecommendation.PRIORITIZE_VALIDATION
    assert RiskCode.HIGH_PRODUCT_CONCENTRATION in {
        row.risk_code for row in result.risks if row.game_theme == "Theme 4"
    }
    assert RiskCode.TOP10_GROWTH_CONCENTRATION in {
        row.risk_code for row in result.risks if row.game_theme == "Theme 4"
    }


def test_emerging_launch_windows_obey_market_and_actionability_gates() -> None:
    assert (
        _launch_window_state(
            market_size=MarketSizeBand.INSUFFICIENT_EVIDENCE,
            growth_quality=GrowthQualityState.EXPERIMENTAL_EMERGING,
            competitive_band=CompetitiveStructureRiskBand.MIXED_STRUCTURAL_RISK,
            lifecycle="emerging",
            volatile=False,
            non_actionable=False,
        )
        == LaunchWindowEvidenceState.CAUTION_OR_MONITOR
    )
    assert (
        _launch_window_state(
            market_size=MarketSizeBand.MODERATE,
            growth_quality=GrowthQualityState.EXPERIMENTAL_EMERGING,
            competitive_band=CompetitiveStructureRiskBand.MIXED_STRUCTURAL_RISK,
            lifecycle="emerging",
            volatile=False,
            non_actionable=True,
        )
        == LaunchWindowEvidenceState.CAUTION_OR_MONITOR
    )
    assert (
        _launch_window_state(
            market_size=MarketSizeBand.MODERATE,
            growth_quality=GrowthQualityState.EXPERIMENTAL_EMERGING,
            competitive_band=CompetitiveStructureRiskBand.MIXED_STRUCTURAL_RISK,
            lifecycle="emerging",
            volatile=False,
            non_actionable=False,
        )
        == LaunchWindowEvidenceState.EXPERIMENTAL_WINDOW
    )


def test_raw_labels_are_preserved_and_null_theme_creates_no_row() -> None:
    result = _decision(themes=("", "Unknown", "N/A"))
    assert [row.game_theme for row in result.summaries] == ["", "N/A", "Unknown"]
    assert all(row.game_theme is not None for row in result.summaries)


def test_launch_window_is_exactly_three_non_forecast_rows() -> None:
    result = _decision()
    assert len(result.launch_windows) == 3
    assert [row.horizon_months for row in result.launch_windows] == [1, 2, 3]
    assert all(row.is_forecast is False for row in result.launch_windows)
    assert all(not hasattr(row, "predicted_downloads") for row in result.launch_windows)
    assert all(
        row.decision_policy_version == DECISION_POLICY_VERSION
        for row in result.launch_windows
    )


def test_output_order_and_injected_timestamp_are_deterministic() -> None:
    first = _decision(themes=("B", "A"))
    second = _decision(themes=("A", "B"))
    assert first == second
    assert all(
        row.calculated_at == CALCULATED_AT
        for row in (
            *first.summaries,
            *first.launch_windows,
            *first.risks,
            *first.category_fits,
            *first.migration_hypotheses,
        )
    )


def test_duplicate_mixed_period_scope_and_future_rows_fail_before_calculation() -> None:
    total, structures, aggregate = _aggregate(("Theme",))
    summaries = (_summary("Theme"),)
    growth = tuple(
        row
        for row in aggregate.theme_growth_source_metrics
        if row.period_start == TARGET_MONTH
    )
    with pytest.raises(DecisionValidationError, match="duplicate"):
        calculate_theme_decisions(
            total,
            (*structures, structures[0]),
            growth,
            summaries,
            calculated_at=CALCULATED_AT,
        )
    with pytest.raises(DecisionValidationError, match="after the target"):
        calculate_theme_decisions(
            total,
            (
                replace(
                    structures[0],
                    period_start=date(2026, 8, 1),
                    period_end=date(2026, 8, 31),
                ),
            ),
            growth,
            summaries,
            calculated_at=CALCULATED_AT,
        )
    with pytest.raises(DecisionValidationError, match="incompatible scope"):
        calculate_theme_decisions(
            total,
            (replace(structures[0], scope_name="other-scope"),),
            growth,
            summaries,
            calculated_at=CALCULATED_AT,
        )
    with pytest.raises(DecisionValidationError, match="populations must reconcile exactly"):
        calculate_theme_decisions(
            total,
            structures,
            growth,
            (_summary("Other"),),
            calculated_at=CALCULATED_AT,
        )


def test_policies_and_pure_boundary_have_no_storage_or_external_service_imports() -> None:
    from pathlib import Path

    source = (Path(__file__).parents[1] / "src/analysis/decision_v1.py").read_text(
        encoding="utf-8"
    )
    assert "from ..storage" not in source
    assert "from ..config" not in source
    assert "from ..feishu" not in source
    assert "from ..sensor_tower" not in source
    assert "httpx" not in source
    assert "import duckdb" not in source.lower()
    assert "BACKTEST_POLICY_VERSION" in source
