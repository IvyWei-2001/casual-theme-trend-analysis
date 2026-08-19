"""Pure deterministic DECISION-001 explainable policy calculation.

The calculator accepts only normalized typed evidence rows.  It does not read
DuckDB, Parquet, configuration, Sensor Tower, Feishu, future outcome rows, or
raw transport payloads.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from typing import Protocol, cast

from .backtest_models import BACKTEST_POLICY_VERSION
from .backtest_v1 import _average_ranks
from .decision_models import (
    DECISION_HORIZONS,
    DECISION_POLICY_VERSION,
    SEASONALITY_RISK_PERCENTILE,
    CategoryEvidenceLimitation,
    CategoryFitState,
    CompetitiveStructureRiskBand,
    DecisionConfidence,
    DecisionRecommendation,
    EvidenceAvailability,
    GrowthQualityState,
    LaunchWindowEvidenceState,
    MarketSizeBand,
    MigrationHypothesisStatus,
    NextValidationActionCode,
    PrimaryReasonCode,
    RiskCode,
    RiskSeverity,
    ThemeCategoryFitAssessment,
    ThemeDecisionResult,
    ThemeDecisionRisk,
    ThemeDecisionSummary,
    ThemeLaunchWindowAssessment,
    ThemeMigrationHypothesis,
)
from .errors import DecisionValidationError
from .model_v2_models import MODEL_POLICY_VERSION, ThemeModelSummary
from .models import MonthlyMarketTotal
from .monetization_models import (
    MONETIZATION_POLICY_VERSION,
    ThemeMonetizationObservabilityMetric,
)
from .opportunity_models import (
    OPPORTUNITY_DIMENSION_TYPES,
    ThemeDimensionMonthlyMetric,
    ThemeGrowthSourceMetric,
    ThemeMarketStructureMetric,
    ThemeRepresentativeGame,
)
from .trend_models import ThemeTrendScore

DECISION_SOURCE_POLICY_REFERENCES: tuple[str, ...] = (
    "AGG002_V1",
    MODEL_POLICY_VERSION,
    BACKTEST_POLICY_VERSION,
)
GROWTH_QUALITY_LIFECYCLE_MAP: Mapping[str, GrowthQualityState] = {
    "growing": GrowthQualityState.BALANCED_GROWTH,
    "accelerating": GrowthQualityState.OBSERVABLE_REVENUE_GROWTH_SUPPORT,
    "mature": GrowthQualityState.DURABLE_ESTABLISHED,
    "emerging": GrowthQualityState.EXPERIMENTAL_EMERGING,
    "recovering": GrowthQualityState.CAUTIOUS_RECOVERY,
    "declining": GrowthQualityState.DECLINING,
    "mixed": GrowthQualityState.MIXED_OR_UNCERTAIN,
    "insufficient_history": GrowthQualityState.INSUFFICIENT_EVIDENCE,
}

_MARKET_METRICS: tuple[tuple[str, str], ...] = (
    ("product_share", "market_size_product_share_percentile"),
    ("downloads_share", "market_size_downloads_share_percentile"),
    ("revenue_usd_share", "market_size_observable_revenue_share_percentile"),
)
_COMPETITIVE_METRICS: tuple[tuple[str, str], ...] = (
    ("downloads_product_hhi", "competitive_downloads_hhi_percentile"),
    ("revenue_usd_product_hhi", "competitive_observable_revenue_hhi_percentile"),
    (
        "downloads_top_10_positive_contribution_share",
        "competitive_downloads_top10_growth_percentile",
    ),
    (
        "revenue_usd_top_10_positive_contribution_share",
        "competitive_observable_revenue_top10_growth_percentile",
    ),
)
_POSITIVE_GROWTH_STATES = {
    GrowthQualityState.BALANCED_GROWTH,
    GrowthQualityState.OBSERVABLE_REVENUE_GROWTH_SUPPORT,
}
_HIGH_RISK_STABILITY_BANDS = {"volatile"}
_NON_ACTIONABLE_THEME_LABELS = frozenset(("", "Unknown", "N/A"))


def calculate_theme_decisions(
    monthly_market_total: MonthlyMarketTotal,
    theme_market_structure_metrics: Sequence[ThemeMarketStructureMetric],
    theme_growth_source_metrics: Sequence[ThemeGrowthSourceMetric],
    theme_model_summaries: Sequence[ThemeModelSummary],
    theme_dimension_monthly_metrics: Sequence[ThemeDimensionMonthlyMetric] = (),
    theme_representative_games: Sequence[ThemeRepresentativeGame] = (),
    theme_monetization_metrics: Sequence[ThemeMonetizationObservabilityMetric] = (),
    theme_trend_scores: Sequence[ThemeTrendScore] = (),
    *,
    calculated_at: datetime,
) -> ThemeDecisionResult:
    """Calculate one deterministic DECISION-001 result for one target month.

    The target population is the exact intersection of the supplied target
    month MODEL-002 summaries and AGG-002 market-structure rows.  Optional
    evidence families may be partial; missing families become explicit
    insufficient evidence or normalized risks rather than silently creating a
    recommendation from a different population.
    """

    _require_timestamp(calculated_at)
    target = _validate_target_month(monthly_market_total)
    structures = _index_target_rows(
        theme_market_structure_metrics,
        ThemeMarketStructureMetric,
        target=target,
        label="market structure",
    )
    summaries = _index_target_rows(
        theme_model_summaries,
        ThemeModelSummary,
        target=target,
        label="model summary",
    )
    if set(structures) != set(summaries):
        raise DecisionValidationError(
            "model summary and market-structure theme populations must reconcile exactly"
        )

    growth_sources = _index_optional_target_rows(
        theme_growth_source_metrics,
        ThemeGrowthSourceMetric,
        target=target,
        expected_themes=set(summaries),
        label="growth source",
    )
    trend_scores = _index_optional_target_rows(
        theme_trend_scores,
        ThemeTrendScore,
        target=target,
        expected_themes=set(summaries),
        label="legacy 6M Momentum",
    )
    monetization_metrics = _index_optional_target_rows(
        theme_monetization_metrics,
        ThemeMonetizationObservabilityMetric,
        target=target,
        expected_themes=set(summaries),
        label="monetization observability",
    )
    dimensions = _validate_dimension_rows(
        theme_dimension_monthly_metrics,
        target=target,
        expected_themes=set(summaries),
    )
    representative_games = _validate_representative_rows(
        theme_representative_games,
        target=target,
        expected_themes=set(summaries),
    )

    ordered_themes = tuple(sorted(summaries))
    market_percentiles = {
        field_name: _percentiles_by_theme(structures, source_field)
        for source_field, field_name in _MARKET_METRICS
    }
    competitive_values = {
        source_field: {
            theme: _competitive_value(
                structures[theme],
                growth_sources.get(theme),
                source_field,
            )
            for theme in ordered_themes
        }
        for source_field, _field_name in _COMPETITIVE_METRICS
    }
    competitive_percentiles = {
        field_name: _percentiles_for_values(
            competitive_values[source_field],
        )
        for source_field, field_name in _COMPETITIVE_METRICS
    }
    seasonality_percentiles = {
        field_name: _percentiles_for_values(
            {
                theme: getattr(summaries[theme], source_field)
                for theme in ordered_themes
            }
        )
        for source_field, field_name in (
            ("downloads_seasonality_amplitude", "downloads_seasonality_amplitude"),
            ("revenue_usd_seasonality_amplitude", "revenue_usd_seasonality_amplitude"),
        )
    }

    category_fits = _build_category_fits(
        target=target,
        expected_themes=set(summaries),
        dimension_rows=dimensions,
        representative_rows=representative_games,
        calculated_at=calculated_at,
    )
    fits_by_theme = _group_by_theme(category_fits)
    migrations = _build_migration_hypotheses(category_fits, calculated_at=calculated_at)
    migrations_by_theme = _group_by_theme(migrations)

    summaries_out: list[ThemeDecisionSummary] = []
    risks_out: list[ThemeDecisionRisk] = []
    launches_out: list[ThemeLaunchWindowAssessment] = []
    for theme in ordered_themes:
        structure = structures[theme]
        model_summary = summaries[theme]
        growth = growth_sources.get(theme)
        trend_score = trend_scores.get(theme)
        monetization = monetization_metrics.get(theme)
        market_size_percentile_values = {
            field_name: market_percentiles[field_name].get(theme)
            for _source_field, field_name in _MARKET_METRICS
        }
        market_size = _classify_market_size(tuple(market_size_percentile_values.values()))
        competitive_percentile_values = {
            field_name: competitive_percentiles[field_name].get(theme)
            for _source_field, field_name in _COMPETITIVE_METRICS
        }
        competitive_band = _classify_competitive_risk(
            tuple(competitive_percentile_values.values())
        )
        growth_quality = _map_growth_quality(model_summary.lifecycle_stage)
        theme_fits = fits_by_theme.get(theme, ())
        category_fit_summary = _summarize_category_fit(theme_fits)
        confidence = _classify_confidence(
            structure=structure,
            growth=growth,
            model_summary=model_summary,
            category_fit_summary=category_fit_summary,
        )
        revenue_evidence_used = _has_observable_revenue_evidence(
            structure=structure,
            growth=growth,
            monetization=monetization,
            category_fits=theme_fits,
        )
        non_actionable = _is_non_actionable_theme_label(theme)
        volatile = _has_volatile_stability(model_summary)
        recommendation = _recommend(
            market_size=market_size,
            growth_quality=growth_quality,
            competitive_band=competitive_band,
            confidence=confidence,
            lifecycle=model_summary.lifecycle_stage,
            non_actionable=non_actionable,
            volatile=volatile,
        )
        primary_reason = _primary_reason(
            market_size=market_size,
            lifecycle=model_summary.lifecycle_stage,
            volatile=volatile,
        )
        source_policy_references = _source_policy_references(
            revenue_evidence_used=revenue_evidence_used,
        )
        next_action = _next_action(
            recommendation=recommendation,
            category_fit_summary=category_fit_summary,
            has_migration_hypothesis=bool(migrations_by_theme.get(theme)),
        )
        summary = ThemeDecisionSummary(
            scope_name=target.scope_name,
            cadence=target.cadence,
            period_start=target.period_start,
            period_end=target.period_end,
            game_theme=theme,
            decision_policy_version=DECISION_POLICY_VERSION,
            market_size_band=market_size,
            growth_quality_state=growth_quality,
            competitive_structure_risk_band=competitive_band,
            category_fit_summary=category_fit_summary,
            confidence=confidence,
            recommendation=recommendation,
            primary_reason_code=primary_reason,
            next_validation_action_code=next_action,
            source_policy_references=source_policy_references,
            calculated_at=calculated_at,
            **market_size_percentile_values,
            **competitive_percentile_values,
            current_market_new_entry_share=(
                None if growth is None else growth.market_new_entry_share
            ),
            current_top_500_turnover_rate=(
                None if growth is None else growth.top_500_turnover_rate
            ),
            downloads_trend_slope_6m=model_summary.median_normalized_slope_6m,
            downloads_trend_slope_12m=model_summary.median_normalized_slope_12m,
            downloads_trend_slope_36m=model_summary.median_normalized_slope_36m,
            downloads_seasonality_amplitude=model_summary.downloads_seasonality_amplitude,
            observable_revenue_seasonality_amplitude=(
                model_summary.revenue_usd_seasonality_amplitude
            ),
            legacy_6m_momentum_score=(
                None if trend_score is None else trend_score.trend_score
            ),
        )
        summaries_out.append(summary)
        theme_risks = _build_risks(
            target=target,
            theme=theme,
            structure=structure,
            growth=growth,
            model_summary=model_summary,
            monetization=monetization,
            market_size=market_size,
            competitive_band=competitive_band,
            competitive_percentile_values=competitive_percentile_values,
            seasonality_percentiles=seasonality_percentiles,
            has_migration_hypothesis=bool(migrations_by_theme.get(theme)),
            revenue_evidence_used=revenue_evidence_used,
            calculated_at=calculated_at,
        )
        risks_out.extend(theme_risks)
        launch_state = _launch_window_state(
            market_size=market_size,
            growth_quality=growth_quality,
            competitive_band=competitive_band,
            lifecycle=model_summary.lifecycle_stage,
            volatile=volatile,
            non_actionable=non_actionable,
        )
        launch_reason = _launch_reason(
            state=launch_state,
            primary_reason=primary_reason,
            lifecycle=model_summary.lifecycle_stage,
        )
        launches_out.extend(
            ThemeLaunchWindowAssessment(
                scope_name=target.scope_name,
                cadence=target.cadence,
                period_start=target.period_start,
                period_end=target.period_end,
                game_theme=theme,
                decision_policy_version=DECISION_POLICY_VERSION,
                horizon_months=horizon,
                evidence_state=launch_state,
                confidence=confidence,
                reason_code=launch_reason,
                is_forecast=False,
                source_policy_references=source_policy_references,
                calculated_at=calculated_at,
            )
            for horizon in DECISION_HORIZONS
        )

    return ThemeDecisionResult(
        decision_summaries=tuple(summaries_out),
        launch_window_assessments=tuple(launches_out),
        decision_risks=tuple(risks_out),
        category_fit_assessments=tuple(category_fits),
        migration_hypotheses=tuple(migrations),
    )


def calculate_theme_decision_policy(*args: object, **kwargs: object) -> ThemeDecisionResult:
    """Compatibility alias for callers using the policy-oriented name."""

    return calculate_theme_decisions(*args, **kwargs)  # type: ignore[arg-type]


def calculate_theme_decision(*args: object, **kwargs: object) -> ThemeDecisionResult:
    """Compatibility alias for callers using the singular operation name."""

    return calculate_theme_decisions(*args, **kwargs)  # type: ignore[arg-type]


def _validate_target_month(row: MonthlyMarketTotal) -> MonthlyMarketTotal:
    if not isinstance(row, MonthlyMarketTotal):
        raise DecisionValidationError("target month must be a MonthlyMarketTotal")
    if row.cadence != "monthly" or row.period_start.day != 1:
        raise DecisionValidationError("target month must be a natural monthly period")
    if row.period_end != _natural_month_end(row.period_start):
        raise DecisionValidationError("target month must be a natural monthly period")
    return row


def _index_target_rows[T](
    rows: Sequence[T],
    expected_type: type[T],
    *,
    target: MonthlyMarketTotal,
    label: str,
) -> dict[str, T]:
    indexed: dict[str, T] = {}
    for row in tuple(rows):
        if not isinstance(row, expected_type):
            raise DecisionValidationError(f"{label} rows must use normalized typed models")
        _validate_row_period(row, target=target, label=label, allow_before=False)
        theme = _require_theme_label(row, label=label)
        if theme in indexed:
            raise DecisionValidationError(f"{label} rows contain duplicate identities")
        indexed[theme] = row
    return indexed


def _index_optional_target_rows[T](
    rows: Sequence[T],
    expected_type: type[T],
    *,
    target: MonthlyMarketTotal,
    expected_themes: set[str],
    label: str,
) -> dict[str, T]:
    indexed = _index_target_rows(rows, expected_type, target=target, label=label)
    if not set(indexed).issubset(expected_themes):
        raise DecisionValidationError(f"{label} rows contain themes outside the target population")
    return indexed


def _require_theme_label(row: object, *, label: str) -> str:
    theme = getattr(row, "game_theme", None)
    if not isinstance(theme, str):
        raise DecisionValidationError(f"{label} game_theme must be a raw string label")
    return theme


def _validate_row_period(
    row: object,
    *,
    target: MonthlyMarketTotal,
    label: str,
    allow_before: bool,
) -> None:
    if getattr(row, "scope_name", None) != target.scope_name:
        raise DecisionValidationError(f"{label} rows have incompatible scope")
    if getattr(row, "cadence", None) != "monthly":
        raise DecisionValidationError(f"{label} rows have incompatible cadence")
    period_start = getattr(row, "period_start", None)
    period_end = getattr(row, "period_end", None)
    if not isinstance(period_start, date) or not isinstance(period_end, date):
        raise DecisionValidationError(f"{label} rows must have date period identities")
    if period_start > target.period_start:
        raise DecisionValidationError(f"{label} rows after the target month are not allowed")
    if not allow_before and period_start != target.period_start:
        raise DecisionValidationError(f"{label} rows must use the target month")
    if period_end != _natural_month_end(period_start) or period_start.day != 1:
        raise DecisionValidationError(f"{label} rows must use natural calendar months")


def _validate_dimension_rows(
    rows: Sequence[ThemeDimensionMonthlyMetric],
    *,
    target: MonthlyMarketTotal,
    expected_themes: set[str],
) -> tuple[ThemeDimensionMonthlyMetric, ...]:
    window_start = _month_shift(target.period_start, -11)
    indexed: dict[tuple[str, date, str, str], ThemeDimensionMonthlyMetric] = {}
    seen_identities: set[tuple[str, date, str, str]] = set()
    for row in tuple(rows):
        if not isinstance(row, ThemeDimensionMonthlyMetric):
            raise DecisionValidationError("dimension rows must use normalized typed models")
        _validate_row_period(row, target=target, label="dimension", allow_before=True)
        if row.period_start < window_start:
            raise DecisionValidationError("dimension rows exceed the trailing 12-month window")
        if row.dimension_type not in OPPORTUNITY_DIMENSION_TYPES:
            raise DecisionValidationError("dimension row uses an unsupported dimension type")
        identity = (row.game_theme, row.period_start, row.dimension_type, row.dimension_value)
        if identity in seen_identities:
            raise DecisionValidationError("dimension rows contain duplicate identities")
        seen_identities.add(identity)
        if row.game_theme not in expected_themes:
            if row.period_start == target.period_start:
                raise DecisionValidationError(
                    "dimension rows contain themes outside the target population"
                )
            continue
        indexed[identity] = row
    return tuple(
        sorted(
            indexed.values(),
            key=lambda row: (
                row.game_theme,
                row.period_start,
                row.dimension_type,
                row.dimension_value,
            ),
        )
    )


def _validate_representative_rows(
    rows: Sequence[ThemeRepresentativeGame],
    *,
    target: MonthlyMarketTotal,
    expected_themes: set[str],
) -> tuple[ThemeRepresentativeGame, ...]:
    window_start = _month_shift(target.period_start, -11)
    indexed: dict[tuple[str, date, str, int], ThemeRepresentativeGame] = {}
    seen_identities: set[tuple[str, date, str, int]] = set()
    for row in tuple(rows):
        if not isinstance(row, ThemeRepresentativeGame):
            raise DecisionValidationError("representative rows must use normalized typed models")
        _validate_row_period(row, target=target, label="representative", allow_before=True)
        if row.period_start < window_start:
            raise DecisionValidationError(
                "representative rows exceed the trailing 12-month evidence window"
            )
        identity = (row.game_theme, row.period_start, row.evidence_type, row.evidence_rank)
        if identity in seen_identities:
            raise DecisionValidationError("representative rows contain duplicate identities")
        seen_identities.add(identity)
        if row.game_theme not in expected_themes:
            if row.period_start == target.period_start:
                raise DecisionValidationError(
                    "representative rows contain themes outside the target population"
                )
            continue
        indexed[identity] = row
    return tuple(
        sorted(
            indexed.values(),
            key=lambda row: (
                row.game_theme,
                row.period_start,
                row.evidence_type,
                row.evidence_rank,
                row.unified_app_id,
            ),
        )
    )


def _percentiles_by_theme(
    rows: Mapping[str, object],
    source_field: str,
) -> dict[str, float]:
    return _percentiles_for_values(
        {theme: getattr(row, source_field) for theme, row in rows.items()}
    )


def _percentiles_for_values(values: Mapping[str, float | None]) -> dict[str, float]:
    """Return BACKTEST-001 average-rank percentiles in the 0..1 range."""

    numeric_values = [(key, float(value)) for key, value in values.items() if value is not None]
    if not numeric_values:
        return {}
    ordered_values = sorted(value for _key, value in numeric_values)
    ranks = _average_ranks(ordered_values)
    by_value: dict[float, float] = {}
    count = len(ordered_values)
    for value, rank in zip(ordered_values, ranks, strict=True):
        by_value[value] = 0.5 if count == 1 else (rank - 1.0) / (count - 1.0)
    return {key: by_value[value] for key, value in numeric_values}


def _classify_market_size(values: Iterable[float | None]) -> MarketSizeBand:
    available = [value for value in values if value is not None]
    if len(available) < 2:
        return MarketSizeBand.INSUFFICIENT_EVIDENCE
    if sum(value >= 0.80 for value in available) >= 2:
        return MarketSizeBand.STRONG
    if sum(value >= 0.50 for value in available) >= 2:
        return MarketSizeBand.MODERATE
    return MarketSizeBand.LIMITED


def _classify_competitive_risk(
    values: Iterable[float | None],
) -> CompetitiveStructureRiskBand:
    available = [value for value in values if value is not None]
    high_count = sum(value >= 0.80 for value in available)
    if high_count >= 2:
        return CompetitiveStructureRiskBand.HIGHER_STRUCTURAL_RISK
    if len(available) >= 3 and high_count == 0 and sum(value <= 0.50 for value in available) >= 2:
        return CompetitiveStructureRiskBand.LOWER_STRUCTURAL_RISK
    if len(available) >= 2:
        return CompetitiveStructureRiskBand.MIXED_STRUCTURAL_RISK
    return CompetitiveStructureRiskBand.INSUFFICIENT_EVIDENCE


def _map_growth_quality(lifecycle_stage: str) -> GrowthQualityState:
    try:
        return GROWTH_QUALITY_LIFECYCLE_MAP[lifecycle_stage]
    except KeyError as error:
        raise DecisionValidationError("model summary lifecycle_stage is unsupported") from error


def _competitive_value(
    structure: ThemeMarketStructureMetric,
    growth: ThemeGrowthSourceMetric | None,
    source_field: str,
) -> float | None:
    if source_field in {"downloads_product_hhi", "revenue_usd_product_hhi"}:
        return cast(float | None, getattr(structure, source_field))
    return None if growth is None else cast(float | None, getattr(growth, source_field))


def _classify_confidence(
    *,
    structure: ThemeMarketStructureMetric,
    growth: ThemeGrowthSourceMetric | None,
    model_summary: ThemeModelSummary,
    category_fit_summary: CategoryFitState,
) -> DecisionConfidence:
    market_count = sum(
        getattr(structure, source_field) is not None
        for source_field, _field_name in _MARKET_METRICS
    )
    competition_count = sum(
        _competitive_value(structure, growth, source_field) is not None
        for source_field, _field_name in _COMPETITIVE_METRICS
    )
    if (
        market_count == 3
        and model_summary.has_12m_history
        and model_summary.lifecycle_stage != "insufficient_history"
        and competition_count >= 3
        and category_fit_summary == CategoryFitState.VALIDATED_FIT
    ):
        return DecisionConfidence.HIGH
    if (
        market_count >= 2
        and model_summary.lifecycle_stage != "insufficient_history"
        and competition_count >= 2
    ):
        return DecisionConfidence.MEDIUM
    return DecisionConfidence.LOW


def _summarize_category_fit(
    rows: Sequence[ThemeCategoryFitAssessment],
) -> CategoryFitState:
    if any(row.fit_state == CategoryFitState.VALIDATED_FIT for row in rows):
        return CategoryFitState.VALIDATED_FIT
    if any(row.fit_state == CategoryFitState.OBSERVED_FIT for row in rows):
        return CategoryFitState.OBSERVED_FIT
    return CategoryFitState.INSUFFICIENT_EVIDENCE


def _volatile_stability_source(summary: ThemeModelSummary) -> str | None:
    for field_name in (
        "stability_band_6m",
        "stability_band_12m",
        "stability_band_36m",
    ):
        if getattr(summary, field_name) in _HIGH_RISK_STABILITY_BANDS:
            return field_name
    return None


def _has_volatile_stability(summary: ThemeModelSummary) -> bool:
    return _volatile_stability_source(summary) is not None


def _is_non_actionable_theme_label(game_theme: str) -> bool:
    return game_theme in _NON_ACTIONABLE_THEME_LABELS


def _recommend(
    *,
    market_size: MarketSizeBand,
    growth_quality: GrowthQualityState,
    competitive_band: CompetitiveStructureRiskBand,
    confidence: DecisionConfidence,
    lifecycle: str,
    non_actionable: bool,
    volatile: bool,
) -> DecisionRecommendation:
    if lifecycle == "declining" and (
        market_size == MarketSizeBand.LIMITED
        or competitive_band == CompetitiveStructureRiskBand.HIGHER_STRUCTURAL_RISK
    ):
        return DecisionRecommendation.DEPRIORITIZE
    if (
        market_size == MarketSizeBand.INSUFFICIENT_EVIDENCE
        or growth_quality == GrowthQualityState.INSUFFICIENT_EVIDENCE
        or lifecycle == "mixed"
        or volatile
        or non_actionable
    ):
        return DecisionRecommendation.MONITOR
    if (
        growth_quality == GrowthQualityState.EXPERIMENTAL_EMERGING
    ):
        return DecisionRecommendation.SMALL_EXPERIMENT
    if (
        market_size == MarketSizeBand.STRONG
        and growth_quality in _POSITIVE_GROWTH_STATES
        and competitive_band != CompetitiveStructureRiskBand.HIGHER_STRUCTURAL_RISK
        and confidence != DecisionConfidence.LOW
    ):
        return DecisionRecommendation.PRIORITIZE_VALIDATION
    if (
        (
            market_size == MarketSizeBand.STRONG
            and growth_quality
            in {
                GrowthQualityState.DURABLE_ESTABLISHED,
                GrowthQualityState.CAUTIOUS_RECOVERY,
            }
        )
        or (
            market_size == MarketSizeBand.MODERATE
            and growth_quality in _POSITIVE_GROWTH_STATES
        )
    ):
        return DecisionRecommendation.SELECTIVE_VALIDATION
    return DecisionRecommendation.MONITOR


def _primary_reason(
    *,
    market_size: MarketSizeBand,
    lifecycle: str,
    volatile: bool,
) -> PrimaryReasonCode:
    if market_size == MarketSizeBand.INSUFFICIENT_EVIDENCE or lifecycle == "insufficient_history":
        return PrimaryReasonCode.INSUFFICIENT_EVIDENCE
    if lifecycle == "mixed" or volatile:
        return PrimaryReasonCode.MIXED_OR_VOLATILE_EVIDENCE
    if lifecycle == "declining":
        return PrimaryReasonCode.DECLINING_EVIDENCE
    if lifecycle == "emerging":
        return PrimaryReasonCode.EMERGING_REQUIRES_EXPERIMENT
    if lifecycle == "accelerating":
        return PrimaryReasonCode.OBSERVABLE_REVENUE_GROWTH_EVIDENCE
    if lifecycle == "growing":
        return PrimaryReasonCode.BALANCED_GROWING_EVIDENCE
    if lifecycle == "mature":
        return PrimaryReasonCode.DURABLE_ESTABLISHED_MARKET
    if lifecycle == "recovering":
        return PrimaryReasonCode.RECOVERY_REQUIRES_VALIDATION
    if market_size == MarketSizeBand.STRONG:
        return PrimaryReasonCode.STRONG_CURRENT_MARKET_SCALE
    return PrimaryReasonCode.INSUFFICIENT_EVIDENCE


def _next_action(
    *,
    recommendation: DecisionRecommendation,
    category_fit_summary: CategoryFitState,
    has_migration_hypothesis: bool,
) -> NextValidationActionCode:
    if recommendation == DecisionRecommendation.PRIORITIZE_VALIDATION:
        return NextValidationActionCode.PRIORITIZE_THEME_VALIDATION
    if recommendation == DecisionRecommendation.SELECTIVE_VALIDATION:
        return NextValidationActionCode.RUN_SELECTIVE_CONCEPT_VALIDATION
    if recommendation == DecisionRecommendation.SMALL_EXPERIMENT:
        return NextValidationActionCode.RUN_SMALL_CONTROLLED_EXPERIMENT
    if recommendation == DecisionRecommendation.DEPRIORITIZE:
        return NextValidationActionCode.DEPRIORITIZE_CURRENT_THEME
    if has_migration_hypothesis:
        return NextValidationActionCode.VALIDATE_MIGRATION_HYPOTHESIS
    if category_fit_summary != CategoryFitState.VALIDATED_FIT:
        return NextValidationActionCode.VALIDATE_CATEGORY_FIT
    return NextValidationActionCode.MONITOR_NEXT_COMPLETED_MONTH


def _launch_window_state(
    *,
    market_size: MarketSizeBand,
    growth_quality: GrowthQualityState,
    competitive_band: CompetitiveStructureRiskBand,
    lifecycle: str,
    volatile: bool,
    non_actionable: bool,
) -> LaunchWindowEvidenceState:
    if (
        market_size != MarketSizeBand.INSUFFICIENT_EVIDENCE
        and lifecycle == "emerging"
        and not volatile
        and not non_actionable
        and competitive_band != CompetitiveStructureRiskBand.HIGHER_STRUCTURAL_RISK
    ):
        return LaunchWindowEvidenceState.EXPERIMENTAL_WINDOW
    if (
        market_size == MarketSizeBand.INSUFFICIENT_EVIDENCE
        or competitive_band == CompetitiveStructureRiskBand.HIGHER_STRUCTURAL_RISK
        or lifecycle in {"declining", "mixed", "insufficient_history"}
        or volatile
        or non_actionable
    ):
        return LaunchWindowEvidenceState.CAUTION_OR_MONITOR
    if market_size == MarketSizeBand.STRONG and growth_quality in _POSITIVE_GROWTH_STATES:
        return LaunchWindowEvidenceState.SUPPORTED_VALIDATION_WINDOW
    if (
        market_size == MarketSizeBand.MODERATE
        or growth_quality
        in {
            GrowthQualityState.DURABLE_ESTABLISHED,
            GrowthQualityState.CAUTIOUS_RECOVERY,
        }
    ):
        return LaunchWindowEvidenceState.SELECTIVE_VALIDATION_WINDOW
    return LaunchWindowEvidenceState.CAUTION_OR_MONITOR


def _launch_reason(
    *,
    state: LaunchWindowEvidenceState,
    primary_reason: PrimaryReasonCode,
    lifecycle: str,
) -> PrimaryReasonCode:
    if state != LaunchWindowEvidenceState.CAUTION_OR_MONITOR:
        return primary_reason
    if lifecycle == "declining":
        return PrimaryReasonCode.DECLINING_EVIDENCE
    if lifecycle in {"mixed", "insufficient_history"}:
        return (
            PrimaryReasonCode.INSUFFICIENT_EVIDENCE
            if lifecycle == "insufficient_history"
            else PrimaryReasonCode.MIXED_OR_VOLATILE_EVIDENCE
        )
    return primary_reason


def _source_policy_references(
    *,
    revenue_evidence_used: bool,
) -> tuple[str, ...]:
    if revenue_evidence_used:
        return (*DECISION_SOURCE_POLICY_REFERENCES, MONETIZATION_POLICY_VERSION)
    return DECISION_SOURCE_POLICY_REFERENCES


def _has_observable_revenue_evidence(
    *,
    structure: ThemeMarketStructureMetric,
    growth: ThemeGrowthSourceMetric | None,
    monetization: ThemeMonetizationObservabilityMetric | None,
    category_fits: Sequence[ThemeCategoryFitAssessment],
) -> bool:
    """Return whether any supplied DECISION evidence uses observable Revenue."""

    if monetization is not None:
        return True
    if (
        structure.revenue_usd_coverage_count > 0
        or structure.revenue_usd_sum is not None
        or structure.revenue_usd_share is not None
        or structure.revenue_usd_product_hhi is not None
    ):
        return True
    if growth is not None and (
        growth.revenue_usd_current_coverage_count > 0
        or growth.revenue_usd_current_sum is not None
        or growth.revenue_usd_top_10_positive_contribution_share is not None
    ):
        return True
    return any(
        row.target_month_observable_revenue_coverage_count is not None
        or row.target_month_observable_revenue_usd_sum is not None
        for row in category_fits
    )


def _build_risks(
    *,
    target: MonthlyMarketTotal,
    theme: str,
    structure: ThemeMarketStructureMetric,
    growth: ThemeGrowthSourceMetric | None,
    model_summary: ThemeModelSummary,
    monetization: ThemeMonetizationObservabilityMetric | None,
    market_size: MarketSizeBand,
    competitive_band: CompetitiveStructureRiskBand,
    competitive_percentile_values: Mapping[str, float | None],
    seasonality_percentiles: Mapping[str, Mapping[str, float]],
    has_migration_hypothesis: bool,
    revenue_evidence_used: bool,
    calculated_at: datetime,
) -> tuple[ThemeDecisionRisk, ...]:
    specs: dict[RiskCode, tuple[RiskSeverity, EvidenceAvailability, str | None]] = {}

    if _has_volatile_stability(model_summary):
        specs[RiskCode.VOLATILE_EVIDENCE] = (
            RiskSeverity.HIGH,
            EvidenceAvailability.OBSERVED,
            _volatile_stability_source(model_summary),
        )
    if model_summary.lifecycle_stage == "mixed":
        specs[RiskCode.MIXED_LIFECYCLE] = (
            RiskSeverity.MEDIUM,
            EvidenceAvailability.OBSERVED,
            "lifecycle_stage",
        )
    if model_summary.lifecycle_stage == "declining":
        specs[RiskCode.DECLINING_LIFECYCLE] = (
            RiskSeverity.HIGH,
            EvidenceAvailability.OBSERVED,
            "lifecycle_stage",
        )
    high_hhi = _first_percentile_at_least(
        competitive_percentile_values,
        ("competitive_downloads_hhi_percentile", "competitive_observable_revenue_hhi_percentile"),
    )
    if high_hhi is not None:
        specs[RiskCode.HIGH_PRODUCT_CONCENTRATION] = (
            RiskSeverity.HIGH,
            EvidenceAvailability.OBSERVED,
            high_hhi,
        )
    high_top10 = _first_percentile_at_least(
        competitive_percentile_values,
        (
            "competitive_downloads_top10_growth_percentile",
            "competitive_observable_revenue_top10_growth_percentile",
        ),
    )
    if high_top10 is not None:
        specs[RiskCode.TOP10_GROWTH_CONCENTRATION] = (
            RiskSeverity.MEDIUM,
            EvidenceAvailability.OBSERVED,
            high_top10,
        )
    seasonality_metric = _seasonality_risk_metric(
        theme,
        seasonality_percentiles,
    )
    if seasonality_metric is not None:
        specs[RiskCode.SEASONALITY_TIMING_DEPENDENCE] = (
            RiskSeverity.MEDIUM,
            EvidenceAvailability.OBSERVED,
            seasonality_metric,
        )

    market_available = sum(
        getattr(structure, source_field) is not None
        for source_field, _field_name in _MARKET_METRICS
    )
    if market_size == MarketSizeBand.INSUFFICIENT_EVIDENCE:
        specs[RiskCode.INSUFFICIENT_MARKET_EVIDENCE] = (
            RiskSeverity.HIGH if market_available == 0 else RiskSeverity.MEDIUM,
            EvidenceAvailability.UNAVAILABLE
            if market_available == 0
            else EvidenceAvailability.PARTIAL,
            None,
        )
    if model_summary.lifecycle_stage == "insufficient_history" or not model_summary.has_12m_history:
        specs[RiskCode.INSUFFICIENT_MODEL_HISTORY] = (
            RiskSeverity.MEDIUM,
            EvidenceAvailability.PARTIAL,
            "has_12m_history",
        )
    if _is_non_actionable_theme_label(theme):
        specs[RiskCode.NON_ACTIONABLE_THEME_LABEL] = (
            RiskSeverity.MEDIUM,
            EvidenceAvailability.OBSERVED,
            "game_theme",
        )

    if revenue_evidence_used:
        specs[RiskCode.OBSERVABLE_REVENUE_ONLY] = (
            RiskSeverity.LOW,
            EvidenceAvailability.OBSERVED,
            "revenue_usd_share" if structure.revenue_usd_share is not None else "revenue_absolute",
        )
        specs[RiskCode.MONETIZATION_TYPE_UNVERIFIED] = (
            RiskSeverity.MEDIUM,
            EvidenceAvailability.PARTIAL
            if monetization is not None
            else EvidenceAvailability.UNAVAILABLE,
            "monetization_proxy" if monetization is not None else "revenue_absolute",
        )
        revenue_coverage_gap = (
            structure.revenue_usd_coverage_count < structure.product_count
            or (
                monetization is not None
                and monetization.observable_revenue_coverage_count < monetization.product_count
            )
        )
        if revenue_coverage_gap:
            specs[RiskCode.OBSERVABLE_REVENUE_COVERAGE_GAP] = (
                RiskSeverity.MEDIUM,
                EvidenceAvailability.PARTIAL,
                "observable_revenue_coverage_count",
            )
    if has_migration_hypothesis:
        specs[RiskCode.MIGRATION_NOT_VALIDATED] = (
            RiskSeverity.MEDIUM,
            EvidenceAvailability.PARTIAL,
            "game_subgenre_fit",
        )

    return tuple(
        ThemeDecisionRisk(
            scope_name=target.scope_name,
            cadence=target.cadence,
            period_start=target.period_start,
            period_end=target.period_end,
            game_theme=theme,
            decision_policy_version=DECISION_POLICY_VERSION,
            risk_code=risk_code,
            severity=severity,
            evidence_availability=availability,
            source_metric_name=source_metric_name,
            calculated_at=calculated_at,
        )
        for risk_code, (severity, availability, source_metric_name) in sorted(
            specs.items(), key=lambda item: item[0].value
        )
    )


def _first_percentile_at_least(
    values: Mapping[str, float | None],
    fields: Sequence[str],
) -> str | None:
    for field_name in fields:
        value = values.get(field_name)
        if value is not None and value >= 0.80:
            return field_name
    return None


def _seasonality_risk_metric(
    theme: str,
    percentiles: Mapping[str, Mapping[str, float]],
) -> str | None:
    for field_name in ("downloads_seasonality_amplitude", "revenue_usd_seasonality_amplitude"):
        value = percentiles[field_name].get(theme)
        if value is not None and value >= SEASONALITY_RISK_PERCENTILE:
            return field_name
    return None


def _build_category_fits(
    *,
    target: MonthlyMarketTotal,
    expected_themes: set[str],
    dimension_rows: Sequence[ThemeDimensionMonthlyMetric],
    representative_rows: Sequence[ThemeRepresentativeGame],
    calculated_at: datetime,
) -> tuple[ThemeCategoryFitAssessment, ...]:
    subgenre_rows = tuple(
        row for row in dimension_rows if row.dimension_type == "game_subgenre"
    )
    by_theme_value: dict[tuple[str, str], list[ThemeDimensionMonthlyMetric]] = {}
    for row in subgenre_rows:
        by_theme_value.setdefault((row.game_theme, row.dimension_value), []).append(row)
    representative_evidence_available = bool(representative_rows)
    output: list[ThemeCategoryFitAssessment] = []
    for theme, value in sorted(by_theme_value):
        rows = tuple(
            sorted(
                by_theme_value[(theme, value)],
                key=lambda row: row.period_start,
            )
        )
        target_row = next(
            (row for row in rows if row.period_start == target.period_start),
            None,
        )
        observation_month_count = len({row.period_start for row in rows})
        target_product_count = 0 if target_row is None else target_row.product_count
        target_downloads_coverage = (
            None if target_row is None else target_row.downloads_coverage_count
        )
        target_downloads_sum = None if target_row is None else target_row.downloads_sum
        target_revenue_coverage = (
            None if target_row is None else target_row.revenue_usd_coverage_count
        )
        target_revenue_sum = None if target_row is None else target_row.revenue_usd_sum
        reps_for_category = tuple(
            {
                row.unified_app_id: row
                for row in representative_rows
                if (
                    row.game_theme == theme
                    and row.period_start == target.period_start
                    and row.game_subgenre == value
                )
            }.values()
        )
        representative_count = (
            None
            if not representative_evidence_available
            else len(reps_for_category)
        )
        validated = (
            target_row is not None
            and target_product_count >= 2
            and observation_month_count >= 3
            and target_downloads_coverage is not None
            and target_downloads_coverage > 0
            and target_downloads_sum is not None
            and target_downloads_sum > 0
        )
        fit_state = (
            CategoryFitState.VALIDATED_FIT
            if validated
            else CategoryFitState.OBSERVED_FIT
            if rows
            else CategoryFitState.INSUFFICIENT_EVIDENCE
        )
        limitations: list[CategoryEvidenceLimitation] = []
        if target_row is None:
            limitations.append(CategoryEvidenceLimitation.TARGET_MONTH_NOT_OBSERVED)
        if observation_month_count < 3:
            limitations.append(CategoryEvidenceLimitation.INSUFFICIENT_OBSERVATION_HISTORY)
        if target_product_count < 2:
            limitations.append(CategoryEvidenceLimitation.INSUFFICIENT_TARGET_PRODUCT_COUNT)
        if (
            target_downloads_coverage is None
            or target_downloads_coverage <= 0
            or target_downloads_sum is None
            or target_downloads_sum <= 0
        ):
            limitations.append(CategoryEvidenceLimitation.INSUFFICIENT_DOWNLOADS_EVIDENCE)
        if target_revenue_coverage is None or target_revenue_sum is None:
            limitations.append(CategoryEvidenceLimitation.OBSERVABLE_REVENUE_UNAVAILABLE)
        elif target_revenue_coverage < target_product_count:
            limitations.append(CategoryEvidenceLimitation.OBSERVABLE_REVENUE_COVERAGE_GAP)
        if representative_count is None:
            limitations.append(CategoryEvidenceLimitation.REPRESENTATIVE_EVIDENCE_UNAVAILABLE)
        output.append(
            ThemeCategoryFitAssessment(
                scope_name=target.scope_name,
                cadence=target.cadence,
                period_start=target.period_start,
                period_end=target.period_end,
                game_theme=theme,
                decision_policy_version=DECISION_POLICY_VERSION,
                game_subgenre=value,
                fit_state=fit_state,
                observation_month_count=observation_month_count,
                target_month_product_count=target_product_count,
                target_month_downloads_coverage_count=target_downloads_coverage,
                target_month_downloads_sum=target_downloads_sum,
                target_month_observable_revenue_coverage_count=target_revenue_coverage,
                target_month_observable_revenue_usd_sum=target_revenue_sum,
                supporting_representative_product_count=representative_count,
                evidence_limitations=tuple(limitations),
                calculated_at=calculated_at,
            )
        )
    return tuple(sorted(output, key=lambda row: row.identity))


def _build_migration_hypotheses(
    category_fits: Sequence[ThemeCategoryFitAssessment],
    *,
    calculated_at: datetime,
) -> tuple[ThemeMigrationHypothesis, ...]:
    by_theme = _group_by_theme(category_fits)
    output: list[ThemeMigrationHypothesis] = []
    for theme in sorted(by_theme):
        rows = by_theme[theme]
        validated_sources = tuple(
            sorted(
                row.game_subgenre
                for row in rows
                if row.fit_state == CategoryFitState.VALIDATED_FIT
            )
        )
        observed_targets = tuple(
            sorted(
                row.game_subgenre
                for row in rows
                if row.fit_state == CategoryFitState.OBSERVED_FIT
            )
        )
        for source in validated_sources:
            for target in observed_targets:
                if source == target:
                    continue
                row = next(row for row in rows if row.game_subgenre == target)
                output.append(
                    ThemeMigrationHypothesis(
                        scope_name=row.scope_name,
                        cadence=row.cadence,
                        period_start=row.period_start,
                        period_end=row.period_end,
                        game_theme=row.game_theme,
                        decision_policy_version=DECISION_POLICY_VERSION,
                        validated_source_game_subgenre=source,
                        target_observed_game_subgenre=target,
                        hypothesis_status=MigrationHypothesisStatus.REQUIRES_PRODUCT_VALIDATION,
                        supporting_evidence_codes=(
                            "validated_source_fit",
                            "observed_target_fit",
                        ),
                        risk_limitation_codes=(RiskCode.MIGRATION_NOT_VALIDATED,),
                        is_validated_fit=False,
                        requires_product_validation=True,
                        calculated_at=calculated_at,
                    )
                )
    return tuple(sorted(output, key=lambda row: row.identity))


class _ThemeOutputRow(Protocol):
    @property
    def game_theme(self) -> str: ...

    @property
    def identity(self) -> tuple[object, ...]: ...


def _group_by_theme[TTheme: _ThemeOutputRow](
    rows: Sequence[TTheme],
) -> dict[str, tuple[TTheme, ...]]:
    grouped: dict[str, list[TTheme]] = {}
    for row in rows:
        grouped.setdefault(row.game_theme, []).append(row)
    return {
        theme: tuple(sorted(values, key=lambda row: row.identity))
        for theme, values in grouped.items()
    }


def _natural_month_end(month_start: date) -> date:
    return _month_shift(month_start, 1).fromordinal(
        _month_shift(month_start, 1).toordinal() - 1
    )


def _month_shift(month_start: date, offset: int) -> date:
    month_index = month_start.year * 12 + month_start.month - 1 + offset
    year, zero_month = divmod(month_index, 12)
    return date(year, zero_month + 1, 1)


def _require_timestamp(value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DecisionValidationError("calculated_at must be timezone-aware")


__all__ = [
    "DECISION_SOURCE_POLICY_REFERENCES",
    "GROWTH_QUALITY_LIFECYCLE_MAP",
    "calculate_theme_decision",
    "calculate_theme_decision_policy",
    "calculate_theme_decisions",
]
