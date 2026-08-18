"""Immutable DECISION-001 policy outputs.

These models are the pure contract for the explainable theme-opportunity
decision layer.  They intentionally contain no database, configuration,
network, Sensor Tower, or Feishu fields.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from math import isfinite
from typing import Protocol, cast

from .errors import DecisionValidationError

DECISION_POLICY_VERSION = "DECISION001_V1"
DECISION_HORIZONS: tuple[int, ...] = (1, 2, 3)
SEASONALITY_RISK_PERCENTILE = 0.80


class MarketSizeBand(StrEnum):
    """Current-month cross-theme market-size classification."""

    STRONG = "strong"
    MODERATE = "moderate"
    LIMITED = "limited"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class GrowthQualityState(StrEnum):
    """Decision-facing interpretation of MODEL-002 lifecycle evidence."""

    BALANCED_GROWTH = "balanced_growth"
    OBSERVABLE_REVENUE_GROWTH_SUPPORT = "observable_revenue_growth_support"
    DURABLE_ESTABLISHED = "durable_established"
    EXPERIMENTAL_EMERGING = "experimental_emerging"
    CAUTIOUS_RECOVERY = "cautious_recovery"
    DECLINING = "declining"
    MIXED_OR_UNCERTAIN = "mixed_or_uncertain"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class CompetitiveStructureRiskBand(StrEnum):
    """Current-month cross-theme concentration-risk classification."""

    LOWER_STRUCTURAL_RISK = "lower_structural_risk"
    MIXED_STRUCTURAL_RISK = "mixed_structural_risk"
    HIGHER_STRUCTURAL_RISK = "higher_structural_risk"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class CategoryFitState(StrEnum):
    """Observed Game Sub-genre fit state."""

    VALIDATED_FIT = "validated_fit"
    OBSERVED_FIT = "observed_fit"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class DecisionRecommendation(StrEnum):
    """Theme-exploration recommendation, never a Product Greenlight."""

    PRIORITIZE_VALIDATION = "prioritize_validation"
    SELECTIVE_VALIDATION = "selective_validation"
    SMALL_EXPERIMENT = "small_experiment"
    MONITOR = "monitor"
    DEPRIORITIZE = "deprioritize"


class DecisionConfidence(StrEnum):
    """Completeness of compatible evidence in the selected market sample."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class LaunchWindowEvidenceState(StrEnum):
    """Non-forecast evidence state for one launch horizon."""

    SUPPORTED_VALIDATION_WINDOW = "supported_validation_window"
    SELECTIVE_VALIDATION_WINDOW = "selective_validation_window"
    EXPERIMENTAL_WINDOW = "experimental_window"
    CAUTION_OR_MONITOR = "caution_or_monitor"


class RiskCode(StrEnum):
    """Stable normalized risk identifiers."""

    VOLATILE_EVIDENCE = "volatile_evidence"
    MIXED_LIFECYCLE = "mixed_lifecycle"
    DECLINING_LIFECYCLE = "declining_lifecycle"
    HIGH_PRODUCT_CONCENTRATION = "high_product_concentration"
    TOP10_GROWTH_CONCENTRATION = "top10_growth_concentration"
    SEASONALITY_TIMING_DEPENDENCE = "seasonality_timing_dependence"
    INSUFFICIENT_MARKET_EVIDENCE = "insufficient_market_evidence"
    INSUFFICIENT_MODEL_HISTORY = "insufficient_model_history"
    NON_ACTIONABLE_THEME_LABEL = "non_actionable_theme_label"
    OBSERVABLE_REVENUE_ONLY = "observable_revenue_only"
    OBSERVABLE_REVENUE_COVERAGE_GAP = "observable_revenue_coverage_gap"
    MONETIZATION_TYPE_UNVERIFIED = "monetization_type_unverified"
    MIGRATION_NOT_VALIDATED = "migration_not_validated"


class RiskSeverity(StrEnum):
    """Normalized risk severity."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EvidenceAvailability(StrEnum):
    """Availability state for the evidence behind a risk row."""

    OBSERVED = "observed"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class PrimaryReasonCode(StrEnum):
    """Stable primary rationale identifiers."""

    STRONG_CURRENT_MARKET_SCALE = "strong_current_market_scale"
    BALANCED_GROWING_EVIDENCE = "balanced_growing_evidence"
    OBSERVABLE_REVENUE_GROWTH_EVIDENCE = "observable_revenue_growth_evidence"
    DURABLE_ESTABLISHED_MARKET = "durable_established_market"
    EMERGING_REQUIRES_EXPERIMENT = "emerging_requires_experiment"
    RECOVERY_REQUIRES_VALIDATION = "recovery_requires_validation"
    MIXED_OR_VOLATILE_EVIDENCE = "mixed_or_volatile_evidence"
    DECLINING_EVIDENCE = "declining_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class NextValidationActionCode(StrEnum):
    """Stable next-action identifiers."""

    PRIORITIZE_THEME_VALIDATION = "prioritize_theme_validation"
    RUN_SELECTIVE_CONCEPT_VALIDATION = "run_selective_concept_validation"
    RUN_SMALL_CONTROLLED_EXPERIMENT = "run_small_controlled_experiment"
    MONITOR_NEXT_COMPLETED_MONTH = "monitor_next_completed_month"
    DEPRIORITIZE_CURRENT_THEME = "deprioritize_current_theme"
    VALIDATE_CATEGORY_FIT = "validate_category_fit"
    VALIDATE_MIGRATION_HYPOTHESIS = "validate_migration_hypothesis"


class CategoryEvidenceLimitation(StrEnum):
    """Stable limitations attached to observed category-fit rows."""

    TARGET_MONTH_NOT_OBSERVED = "target_month_not_observed"
    INSUFFICIENT_OBSERVATION_HISTORY = "insufficient_observation_history"
    INSUFFICIENT_TARGET_PRODUCT_COUNT = "insufficient_target_product_count"
    INSUFFICIENT_DOWNLOADS_EVIDENCE = "insufficient_downloads_evidence"
    OBSERVABLE_REVENUE_UNAVAILABLE = "observable_revenue_unavailable"
    OBSERVABLE_REVENUE_COVERAGE_GAP = "observable_revenue_coverage_gap"
    REPRESENTATIVE_EVIDENCE_UNAVAILABLE = "representative_evidence_unavailable"


class MigrationHypothesisStatus(StrEnum):
    """Status for a non-validated but observed target category."""

    REQUIRES_PRODUCT_VALIDATION = "requires_product_validation"


def _require_scope(value: object, *, field_name: str = "scope_name") -> str:
    if not isinstance(value, str) or not value.strip():
        raise DecisionValidationError(f"{field_name} must be a non-empty string")
    return value


def _require_raw_label(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise DecisionValidationError(f"{field_name} must be a string")
    return value


def _require_date(value: object, *, field_name: str) -> date:
    if type(value) is not date:
        raise DecisionValidationError(f"{field_name} must be a date")
    return value


def _require_natural_month(period_start: object, period_end: object) -> tuple[date, date]:
    start = _require_date(period_start, field_name="period_start")
    end = _require_date(period_end, field_name="period_end")
    if start.day != 1:
        raise DecisionValidationError("period_start must be the first day of a month")
    if end != _month_end(start):
        raise DecisionValidationError("period_end must be the last day of a month")
    return start, end


def _month_end(month_start: date) -> date:
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    return next_month.fromordinal(next_month.toordinal() - 1)


def _require_timestamp(value: object, *, field_name: str = "calculated_at") -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DecisionValidationError(f"{field_name} must be timezone-aware")
    return value


def _require_non_negative_count(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DecisionValidationError(f"{field_name} must be a non-negative integer")
    return value


def _require_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionValidationError(f"{field_name} must be a number")
    numeric_value = float(value)
    if not isfinite(numeric_value):
        raise DecisionValidationError(f"{field_name} must be finite")
    return numeric_value


def _optional_percentile(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    numeric_value = _require_number(value, field_name=field_name)
    if not 0 <= numeric_value <= 1:
        raise DecisionValidationError(f"{field_name} must be between 0 and 1")
    return numeric_value


def _optional_finite_number(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    return _require_number(value, field_name=field_name)


def _normalize_enum[T: StrEnum](value: object, enum_type: type[T], *, field_name: str) -> T:
    try:
        normalized = value if isinstance(value, enum_type) else enum_type(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise DecisionValidationError(f"{field_name} is not supported") from error
    return normalized


def _normalize_text_tuple(value: Iterable[object], *, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise DecisionValidationError(f"{field_name} must be a sequence of strings")
    normalized = tuple(value)
    if any(not isinstance(item, str) or not item for item in normalized):
        raise DecisionValidationError(f"{field_name} must contain non-empty strings")
    return cast(tuple[str, ...], normalized)


def _normalize_enum_tuple[T: StrEnum](
    value: Iterable[object],
    enum_type: type[T],
    *,
    field_name: str,
) -> tuple[T, ...]:
    if isinstance(value, (str, bytes)):
        raise DecisionValidationError(f"{field_name} must be a sequence")
    return tuple(
        _normalize_enum(item, enum_type, field_name=field_name) for item in value
    )


def _validate_identity(
    scope_name: object,
    cadence: object,
    period_start: object,
    period_end: object,
    game_theme: object,
) -> tuple[str, str, date, date, str]:
    scope = _require_scope(scope_name)
    if cadence != "monthly":
        raise DecisionValidationError("cadence must equal monthly")
    start, end = _require_natural_month(period_start, period_end)
    theme = _require_raw_label(game_theme, field_name="game_theme")
    return scope, "monthly", start, end, theme


class _DecisionOutputRow(Protocol):
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

    @property
    def decision_policy_version(self) -> str: ...

    @property
    def calculated_at(self) -> datetime: ...


def _validate_policy_and_identity(row: _DecisionOutputRow) -> tuple[str, str, date, date, str]:
    identity = _validate_identity(
        row.scope_name,
        row.cadence,
        row.period_start,
        row.period_end,
        row.game_theme,
    )
    if row.decision_policy_version != DECISION_POLICY_VERSION:
        raise DecisionValidationError(
            f"decision_policy_version must equal {DECISION_POLICY_VERSION}"
        )
    _require_timestamp(row.calculated_at)
    return identity


@dataclass(frozen=True, slots=True)
class ThemeDecisionSummary:
    """One explainable recommendation row for one target-month theme."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    decision_policy_version: str
    market_size_band: MarketSizeBand
    growth_quality_state: GrowthQualityState
    competitive_structure_risk_band: CompetitiveStructureRiskBand
    category_fit_summary: CategoryFitState
    confidence: DecisionConfidence
    recommendation: DecisionRecommendation
    primary_reason_code: PrimaryReasonCode
    next_validation_action_code: NextValidationActionCode
    source_policy_references: tuple[str, ...]
    calculated_at: datetime
    market_size_product_share_percentile: float | None = None
    market_size_downloads_share_percentile: float | None = None
    market_size_observable_revenue_share_percentile: float | None = None
    competitive_downloads_hhi_percentile: float | None = None
    competitive_observable_revenue_hhi_percentile: float | None = None
    competitive_downloads_top10_growth_percentile: float | None = None
    competitive_observable_revenue_top10_growth_percentile: float | None = None
    current_market_new_entry_share: float | None = None
    current_top_500_turnover_rate: float | None = None
    downloads_trend_slope_6m: float | None = None
    downloads_trend_slope_12m: float | None = None
    downloads_trend_slope_36m: float | None = None
    downloads_seasonality_amplitude: float | None = None
    observable_revenue_seasonality_amplitude: float | None = None
    legacy_6m_momentum_score: float | None = None

    @property
    def period_key(self) -> tuple[str, str, date, date]:
        """Return the target-month identity without the raw theme."""

        return (self.scope_name, self.cadence, self.period_start, self.period_end)

    @property
    def identity(self) -> tuple[str, str, date, date, str]:
        """Return the complete decision identity."""

        return (*self.period_key, self.game_theme)

    @property
    def evidence_confidence(self) -> DecisionConfidence:
        """Compatibility alias for callers using the longer business name."""

        return self.confidence

    def __post_init__(self) -> None:
        _validate_policy_and_identity(self)
        for field_name, enum_type in (
            ("market_size_band", MarketSizeBand),
            ("growth_quality_state", GrowthQualityState),
            ("competitive_structure_risk_band", CompetitiveStructureRiskBand),
            ("category_fit_summary", CategoryFitState),
            ("confidence", DecisionConfidence),
            ("recommendation", DecisionRecommendation),
            ("primary_reason_code", PrimaryReasonCode),
            ("next_validation_action_code", NextValidationActionCode),
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_enum(getattr(self, field_name), enum_type, field_name=field_name),
            )
        references = _normalize_text_tuple(
            self.source_policy_references,
            field_name="source_policy_references",
        )
        if not references:
            raise DecisionValidationError("source_policy_references must not be empty")
        object.__setattr__(self, "source_policy_references", references)
        for field_name in (
            "market_size_product_share_percentile",
            "market_size_downloads_share_percentile",
            "market_size_observable_revenue_share_percentile",
            "competitive_downloads_hhi_percentile",
            "competitive_observable_revenue_hhi_percentile",
            "competitive_downloads_top10_growth_percentile",
            "competitive_observable_revenue_top10_growth_percentile",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_percentile(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "current_market_new_entry_share",
            "current_top_500_turnover_rate",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_percentile(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "downloads_trend_slope_6m",
            "downloads_trend_slope_12m",
            "downloads_trend_slope_36m",
            "downloads_seasonality_amplitude",
            "observable_revenue_seasonality_amplitude",
            "legacy_6m_momentum_score",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_finite_number(getattr(self, field_name), field_name=field_name),
            )


@dataclass(frozen=True, slots=True)
class ThemeLaunchWindowAssessment:
    """Evidence-only T+1/T+2/T+3 assessment with no forecast values."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    decision_policy_version: str
    horizon_months: int
    evidence_state: LaunchWindowEvidenceState
    confidence: DecisionConfidence
    reason_code: PrimaryReasonCode
    is_forecast: bool
    calculated_at: datetime

    @property
    def identity(self) -> tuple[str, str, date, date, str, int]:
        """Return the launch-window row identity."""

        return (*self.period_key, self.game_theme, self.horizon_months)

    @property
    def period_key(self) -> tuple[str, str, date, date]:
        """Return the target-month identity."""

        return (self.scope_name, self.cadence, self.period_start, self.period_end)

    @property
    def horizon(self) -> int:
        """Compatibility alias for callers using ``horizon``."""

        return self.horizon_months

    def __post_init__(self) -> None:
        _validate_policy_and_identity(self)
        if self.horizon_months not in DECISION_HORIZONS:
            raise DecisionValidationError("horizon_months must be 1, 2, or 3")
        object.__setattr__(
            self,
            "evidence_state",
            _normalize_enum(
                self.evidence_state,
                LaunchWindowEvidenceState,
                field_name="evidence_state",
            ),
        )
        object.__setattr__(
            self,
            "confidence",
            _normalize_enum(self.confidence, DecisionConfidence, field_name="confidence"),
        )
        object.__setattr__(
            self,
            "reason_code",
            _normalize_enum(self.reason_code, PrimaryReasonCode, field_name="reason_code"),
        )
        if self.is_forecast is not False:
            raise DecisionValidationError("is_forecast must always be false")


@dataclass(frozen=True, slots=True)
class ThemeDecisionRisk:
    """One normalized risk code for a target-month theme."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    decision_policy_version: str
    risk_code: RiskCode
    severity: RiskSeverity
    evidence_availability: EvidenceAvailability
    source_metric_name: str | None
    calculated_at: datetime

    @property
    def identity(self) -> tuple[str, str, date, date, str, str, str | None]:
        """Return the normalized risk identity."""

        return (
            self.scope_name,
            self.cadence,
            self.period_start,
            self.period_end,
            self.game_theme,
            self.risk_code.value,
            self.source_metric_name,
        )

    def __post_init__(self) -> None:
        _validate_policy_and_identity(self)
        for field_name, enum_type in (
            ("risk_code", RiskCode),
            ("severity", RiskSeverity),
            ("evidence_availability", EvidenceAvailability),
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_enum(getattr(self, field_name), enum_type, field_name=field_name),
            )
        if self.source_metric_name is not None and not isinstance(self.source_metric_name, str):
            raise DecisionValidationError("source_metric_name must be a string or NULL")


@dataclass(frozen=True, slots=True)
class ThemeCategoryFitAssessment:
    """Observed target-theme Game Sub-genre fit evidence."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    decision_policy_version: str
    game_subgenre: str
    fit_state: CategoryFitState
    observation_month_count: int
    target_month_product_count: int
    target_month_downloads_coverage_count: int | None
    target_month_downloads_sum: float | None
    target_month_observable_revenue_coverage_count: int | None
    target_month_observable_revenue_usd_sum: float | None
    supporting_representative_product_count: int | None
    evidence_limitations: tuple[CategoryEvidenceLimitation, ...]
    calculated_at: datetime

    @property
    def identity(self) -> tuple[str, str, date, date, str, str]:
        """Return the theme/category identity."""

        return (*self.period_key, self.game_theme, self.game_subgenre)

    @property
    def period_key(self) -> tuple[str, str, date, date]:
        """Return the target-month identity."""

        return (self.scope_name, self.cadence, self.period_start, self.period_end)

    @property
    def target_month_observable_revenue_sum(self) -> float | None:
        """Compatibility alias using the shorter business field name."""

        return self.target_month_observable_revenue_usd_sum

    def __post_init__(self) -> None:
        _validate_policy_and_identity(self)
        if not isinstance(self.game_subgenre, str):
            raise DecisionValidationError("game_subgenre must be a string")
        _require_non_negative_count(
            self.observation_month_count,
            field_name="observation_month_count",
        )
        _require_non_negative_count(
            self.target_month_product_count,
            field_name="target_month_product_count",
        )
        for field_name in (
            "target_month_downloads_coverage_count",
            "target_month_observable_revenue_coverage_count",
            "supporting_representative_product_count",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_non_negative_count(value, field_name=field_name)
        for field_name in (
            "target_month_downloads_sum",
            "target_month_observable_revenue_usd_sum",
        ):
            value = getattr(self, field_name)
            if value is not None and _require_number(value, field_name=field_name) < 0:
                raise DecisionValidationError(f"{field_name} must be non-negative")
        object.__setattr__(
            self,
            "fit_state",
            _normalize_enum(self.fit_state, CategoryFitState, field_name="fit_state"),
        )
        limitations = _normalize_enum_tuple(
            self.evidence_limitations,
            CategoryEvidenceLimitation,
            field_name="evidence_limitations",
        )
        object.__setattr__(self, "evidence_limitations", limitations)


@dataclass(frozen=True, slots=True)
class ThemeMigrationHypothesis:
    """A weaker observed target category requiring product validation."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    decision_policy_version: str
    validated_source_game_subgenre: str
    target_observed_game_subgenre: str
    hypothesis_status: MigrationHypothesisStatus
    supporting_evidence_codes: tuple[str, ...]
    risk_limitation_codes: tuple[RiskCode, ...]
    is_validated_fit: bool
    requires_product_validation: bool
    calculated_at: datetime

    @property
    def identity(self) -> tuple[str, str, date, date, str, str, str]:
        """Return the source/target migration identity."""

        return (
            *self.period_key,
            self.game_theme,
            self.validated_source_game_subgenre,
            self.target_observed_game_subgenre,
        )

    @property
    def period_key(self) -> tuple[str, str, date, date]:
        """Return the target-month identity."""

        return (self.scope_name, self.cadence, self.period_start, self.period_end)

    @property
    def source_game_subgenre(self) -> str:
        """Compatibility alias for the validated source value."""

        return self.validated_source_game_subgenre

    @property
    def target_game_subgenre(self) -> str:
        """Compatibility alias for the observed target value."""

        return self.target_observed_game_subgenre

    def __post_init__(self) -> None:
        _validate_policy_and_identity(self)
        for field_name in (
            "validated_source_game_subgenre",
            "target_observed_game_subgenre",
        ):
            if not isinstance(getattr(self, field_name), str):
                raise DecisionValidationError(f"{field_name} must be a string")
        if self.validated_source_game_subgenre == self.target_observed_game_subgenre:
            raise DecisionValidationError("migration source and target must differ")
        object.__setattr__(
            self,
            "hypothesis_status",
            _normalize_enum(
                self.hypothesis_status,
                MigrationHypothesisStatus,
                field_name="hypothesis_status",
            ),
        )
        object.__setattr__(
            self,
            "supporting_evidence_codes",
            _normalize_text_tuple(
                self.supporting_evidence_codes,
                field_name="supporting_evidence_codes",
            ),
        )
        object.__setattr__(
            self,
            "risk_limitation_codes",
            _normalize_enum_tuple(
                self.risk_limitation_codes,
                RiskCode,
                field_name="risk_limitation_codes",
            ),
        )
        if self.is_validated_fit is not False:
            raise DecisionValidationError("migration hypotheses cannot be validated fit")
        if self.requires_product_validation is not True:
            raise DecisionValidationError("migration hypotheses require product validation")


@dataclass(frozen=True, slots=True)
class ThemeDecisionResult:
    """Complete immutable DECISION-001 pure calculation result."""

    decision_summaries: tuple[ThemeDecisionSummary, ...]
    launch_window_assessments: tuple[ThemeLaunchWindowAssessment, ...]
    decision_risks: tuple[ThemeDecisionRisk, ...]
    category_fit_assessments: tuple[ThemeCategoryFitAssessment, ...]
    migration_hypotheses: tuple[ThemeMigrationHypothesis, ...]

    @property
    def summaries(self) -> tuple[ThemeDecisionSummary, ...]:
        """Compatibility alias for the primary decision rows."""

        return self.decision_summaries

    @property
    def launch_windows(self) -> tuple[ThemeLaunchWindowAssessment, ...]:
        """Compatibility alias for launch-window rows."""

        return self.launch_window_assessments

    @property
    def risks(self) -> tuple[ThemeDecisionRisk, ...]:
        """Compatibility alias for normalized risks."""

        return self.decision_risks

    @property
    def category_fits(self) -> tuple[ThemeCategoryFitAssessment, ...]:
        """Compatibility alias for category-fit rows."""

        return self.category_fit_assessments

    def __post_init__(self) -> None:
        summaries = tuple(self.decision_summaries)
        launches = tuple(self.launch_window_assessments)
        risks = tuple(self.decision_risks)
        fits = tuple(self.category_fit_assessments)
        migrations = tuple(self.migration_hypotheses)
        if any(not isinstance(row, ThemeDecisionSummary) for row in summaries):
            raise DecisionValidationError("decision_summaries contain invalid rows")
        if any(not isinstance(row, ThemeLaunchWindowAssessment) for row in launches):
            raise DecisionValidationError("launch_window_assessments contain invalid rows")
        if any(not isinstance(row, ThemeDecisionRisk) for row in risks):
            raise DecisionValidationError("decision_risks contain invalid rows")
        if any(not isinstance(row, ThemeCategoryFitAssessment) for row in fits):
            raise DecisionValidationError("category_fit_assessments contain invalid rows")
        if any(not isinstance(row, ThemeMigrationHypothesis) for row in migrations):
            raise DecisionValidationError("migration_hypotheses contain invalid rows")

        summary_ids = tuple(row.identity for row in summaries)
        if len(set(summary_ids)) != len(summary_ids):
            raise DecisionValidationError("decision summaries contain duplicate identities")
        summary_set = set(summary_ids)

        launch_ids = tuple(row.identity for row in launches)
        if len(set(launch_ids)) != len(launch_ids):
            raise DecisionValidationError("launch-window rows contain duplicate identities")
        for summary_id in summary_set:
            theme_launches = [row for row in launches if row.identity[:-1] == summary_id]
            if {row.horizon_months for row in theme_launches} != set(DECISION_HORIZONS):
                raise DecisionValidationError(
                    "every decision summary must have exactly T+1, T+2, and T+3 rows"
                )
        if any(row.identity[:-1] not in summary_set for row in launches):
            raise DecisionValidationError("launch-window row has no decision summary")

        risk_ids = tuple(row.identity for row in risks)
        if len(set(risk_ids)) != len(risk_ids):
            raise DecisionValidationError("decision risks contain duplicate identities")
        if any(row.identity[:5] not in summary_set for row in risks):
            raise DecisionValidationError("risk row has no decision summary")

        fit_ids = tuple(row.identity for row in fits)
        if len(set(fit_ids)) != len(fit_ids):
            raise DecisionValidationError("category-fit rows contain duplicate identities")
        if any(row.identity[:5] not in summary_set for row in fits):
            raise DecisionValidationError("category-fit row has no decision summary")

        migration_ids = tuple(row.identity for row in migrations)
        if len(set(migration_ids)) != len(migration_ids):
            raise DecisionValidationError("migration hypotheses contain duplicate identities")
        if any(row.identity[:5] not in summary_set for row in migrations):
            raise DecisionValidationError("migration hypothesis has no decision summary")

        timestamped_rows: tuple[_DecisionOutputRow, ...] = (
            *summaries,
            *launches,
            *risks,
            *fits,
            *migrations,
        )
        timestamps = {row.calculated_at for row in timestamped_rows}
        if len(timestamps) > 1:
            raise DecisionValidationError("all DECISION-001 outputs must share calculated_at")

        object.__setattr__(
            self,
            "decision_summaries",
            tuple(sorted(summaries, key=lambda row: row.identity)),
        )
        object.__setattr__(
            self,
            "launch_window_assessments",
            tuple(sorted(launches, key=lambda row: row.identity)),
        )
        object.__setattr__(
            self,
            "decision_risks",
            tuple(sorted(risks, key=lambda row: row.identity)),
        )
        object.__setattr__(
            self,
            "category_fit_assessments",
            tuple(sorted(fits, key=lambda row: row.identity)),
        )
        object.__setattr__(
            self,
            "migration_hypotheses",
            tuple(sorted(migrations, key=lambda row: row.identity)),
        )


__all__ = [
    "DECISION_HORIZONS",
    "DECISION_POLICY_VERSION",
    "SEASONALITY_RISK_PERCENTILE",
    "CategoryEvidenceLimitation",
    "CategoryFitState",
    "CompetitiveStructureRiskBand",
    "DecisionConfidence",
    "DecisionRecommendation",
    "EvidenceAvailability",
    "GrowthQualityState",
    "LaunchWindowEvidenceState",
    "MarketSizeBand",
    "MigrationHypothesisStatus",
    "NextValidationActionCode",
    "PrimaryReasonCode",
    "RiskCode",
    "RiskSeverity",
    "ThemeCategoryFitAssessment",
    "ThemeDecisionResult",
    "ThemeDecisionRisk",
    "ThemeDecisionSummary",
    "ThemeLaunchWindowAssessment",
    "ThemeMigrationHypothesis",
]
