"""Stored-evidence-only orchestration for DECISION-001."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

from ..analysis.decision_models import (
    DECISION_POLICY_VERSION,
    ThemeCategoryFitAssessment,
    ThemeDecisionResult,
    ThemeDecisionRisk,
    ThemeDecisionSummary,
    ThemeLaunchWindowAssessment,
    ThemeMigrationHypothesis,
)
from ..analysis.decision_v1 import calculate_theme_decisions
from ..analysis.errors import DecisionValidationError
from ..analysis.model_v2_models import ThemeModelSummary
from ..analysis.models import MonthlyMarketTotal
from ..analysis.monetization_models import ThemeMonetizationObservabilityMetric
from ..analysis.opportunity_models import (
    ThemeDimensionMonthlyMetric,
    ThemeGrowthSourceMetric,
    ThemeMarketStructureMetric,
    ThemeRepresentativeGame,
)
from ..analysis.trend_models import ThemeTrendScore
from ..config import AppConfig
from ..storage import DuckDBRepository, SnapshotPeriodKey
from .errors import DecisionReadbackVerificationError, DecisionThemesError, WorkflowError
from .models import DecideThemesRequest, DecideThemesSummary, MonthlyPeriod

LOGGER = logging.getLogger(__name__)


class DecisionThemesRepository(Protocol):
    """Minimal local repository boundary used by the decision workflow."""

    def open(self) -> object:
        """Open the configured local database."""

    def initialize_schema(self) -> None:
        """Create or migrate the supported schema."""

    def get_monthly_market_totals(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> list[MonthlyMarketTotal]:
        """Read the target month-wide total."""

    def get_theme_market_structure_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeMarketStructureMetric]:
        """Read target AGG-002 market structure evidence."""

    def get_theme_growth_source_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeGrowthSourceMetric]:
        """Read target AGG-002 growth-source evidence."""

    def get_theme_trend_scores(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeTrendScore]:
        """Read the stored legacy 6M score evidence for the target month."""

    def get_theme_model_summaries(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeModelSummary]:
        """Read target MODEL-002 summaries."""

    def get_theme_dimension_monthly_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
        dimension_type: str | None = None,
        dimension_value: str | None = None,
    ) -> list[ThemeDimensionMonthlyMetric]:
        """Read at most the approved trailing category-evidence window."""

    def get_theme_representative_games(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
        evidence_type: str | None = None,
    ) -> list[ThemeRepresentativeGame]:
        """Read at most the approved trailing representative-game window."""

    def get_theme_monetization_observability_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeMonetizationObservabilityMetric]:
        """Read stored observable-Revenue evidence for the target month."""

    def replace_theme_decision_result(
        self,
        result: ThemeDecisionResult,
        *,
        target_period: SnapshotPeriodKey,
    ) -> None:
        """Atomically replace all five decision output sets for one month."""

    def get_theme_decision_summaries(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
        decision_policy_version: str | None = None,
    ) -> list[ThemeDecisionSummary]:
        """Read persisted summaries for post-commit verification."""

    def get_theme_launch_window_assessments(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
        decision_policy_version: str | None = None,
        horizon_months: int | None = None,
    ) -> list[ThemeLaunchWindowAssessment]:
        """Read persisted launch-window rows for post-commit verification."""

    def get_theme_decision_risks(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
        decision_policy_version: str | None = None,
        risk_code: str | None = None,
    ) -> list[ThemeDecisionRisk]:
        """Read persisted risks for post-commit verification."""

    def get_theme_category_fit_assessments(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
        decision_policy_version: str | None = None,
        game_subgenre: str | None = None,
    ) -> list[ThemeCategoryFitAssessment]:
        """Read persisted category-fit rows for post-commit verification."""

    def get_theme_migration_hypotheses(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
        decision_policy_version: str | None = None,
        validated_source_game_subgenre: str | None = None,
        target_observed_game_subgenre: str | None = None,
    ) -> list[ThemeMigrationHypothesis]:
        """Read persisted migration rows for post-commit verification."""

    def export_theme_decision_summaries_to_parquet(self, path: str | Path) -> None:
        """Export the complete persisted summary table."""

    def export_theme_launch_window_assessments_to_parquet(self, path: str | Path) -> None:
        """Export the complete persisted launch-window table."""

    def export_theme_decision_risks_to_parquet(self, path: str | Path) -> None:
        """Export the complete persisted risk table."""

    def export_theme_category_fit_assessments_to_parquet(self, path: str | Path) -> None:
        """Export the complete persisted category-fit table."""

    def export_theme_migration_hypotheses_to_parquet(self, path: str | Path) -> None:
        """Export the complete persisted migration table."""

    def close(self) -> None:
        """Close the local database."""


RepositoryFactory = Callable[[Path], DecisionThemesRepository]


def run_theme_decision_workflow(
    request: DecideThemesRequest,
    config: AppConfig | None = None,
    *,
    current_utc: datetime | date | None = None,
    utc_clock: Callable[[], datetime] | None = None,
    repository: DecisionThemesRepository | None = None,
    repository_factory: RepositoryFactory | None = None,
    repository_initialized: bool = False,
) -> DecideThemesSummary:
    """Calculate and persist one target month from stored upstream evidence.

    Plan-only validation returns before configuration, repository, schema, or
    export access. Normal execution has no network boundary and calls the
    accepted pure DECISION-001 calculation exactly once.
    """

    if repository is not None and repository_factory is not None:
        raise WorkflowError("provide either repository or repository_factory, not both")
    if not isinstance(repository_initialized, bool):
        raise WorkflowError("repository_initialized must be a boolean")

    started_at = _resolve_started_at(current_utc, utc_clock)
    period = MonthlyPeriod.parse(request.month, current_utc=started_at)
    if request.plan_only:
        return _build_summary(
            request=request,
            period=period,
            scope_name=None,
            result=None,
            verification_passed=False,
            started_at=started_at,
            completed_at=_completion_timestamp(started_at, utc_clock),
        )
    if config is None:
        raise DecisionThemesError("application configuration is required for execution")

    active_repository = repository
    owns_repository = False
    try:
        if active_repository is None:
            builder = DuckDBRepository if repository_factory is None else repository_factory
            active_repository = builder(request.database_path)
            owns_repository = True
        active_repository.open()
        if not repository_initialized:
            active_repository.initialize_schema()

        scope_name = config.sensor_tower_selection_config.scope_name
        target_key = SnapshotPeriodKey(
            scope_name=scope_name,
            cadence=period.cadence,
            period_start=period.period_start,
            period_end=period.period_end,
        )
        trailing_start = _month_shift(period.period_start, -11)
        monthly_total = _require_one_target_row(
            active_repository.get_monthly_market_totals(
                scope_name=scope_name,
                cadence="monthly",
                period_start=period.period_start,
                period_end=period.period_end,
            ),
            target_key=target_key,
            label="monthly market total",
        )
        structures = _require_target_rows(
            active_repository.get_theme_market_structure_metrics(
                scope_name=scope_name,
                cadence="monthly",
                period_start=period.period_start,
                period_end=period.period_end,
            ),
            target_key=target_key,
            label="market structure",
        )
        model_summaries = _require_target_rows(
            active_repository.get_theme_model_summaries(
                scope_name=scope_name,
                cadence="monthly",
                period_start=period.period_start,
                period_end=period.period_end,
            ),
            target_key=target_key,
            label="model summary",
        )
        growth_sources = _require_optional_target_rows(
            active_repository.get_theme_growth_source_metrics(
                scope_name=scope_name,
                cadence="monthly",
                period_start=period.period_start,
                period_end=period.period_end,
            ),
            target_key=target_key,
            label="growth source",
        )
        trend_scores = _require_optional_target_rows(
            active_repository.get_theme_trend_scores(
                scope_name=scope_name,
                cadence="monthly",
                period_start=period.period_start,
                period_end=period.period_end,
            ),
            target_key=target_key,
            label="legacy 6M score",
        )
        monetization_metrics = _require_optional_target_rows(
            active_repository.get_theme_monetization_observability_metrics(
                scope_name=scope_name,
                cadence="monthly",
                period_start=period.period_start,
                period_end=period.period_end,
            ),
            target_key=target_key,
            label="observable-Revenue evidence",
        )
        dimensions = _require_trailing_rows(
            active_repository.get_theme_dimension_monthly_metrics(
                scope_name=scope_name,
                cadence="monthly",
                period_start=trailing_start,
                period_end=period.period_end,
            ),
            target_key=target_key,
            window_start=trailing_start,
            label="category dimension",
        )
        representative_games = _require_trailing_rows(
            active_repository.get_theme_representative_games(
                scope_name=scope_name,
                cadence="monthly",
                period_start=trailing_start,
                period_end=period.period_end,
            ),
            target_key=target_key,
            window_start=trailing_start,
            label="representative game",
        )

        try:
            result = calculate_theme_decisions(
                monthly_total,
                structures,
                growth_sources,
                model_summaries,
                dimensions,
                representative_games,
                monetization_metrics,
                trend_scores,
                calculated_at=started_at,
            )
        except DecisionValidationError as error:
            raise DecisionThemesError(
                "stored decision evidence failed policy validation"
            ) from error

        active_repository.replace_theme_decision_result(result, target_period=target_key)
        _verify_post_commit(active_repository, result, target_key)

        export_paths: tuple[Path | None, ...]
        if request.skip_export:
            export_paths = (None, None, None, None, None)
        else:
            export_paths = _export_decision_tables(active_repository, request.export_directory)
        return _build_summary(
            request=request,
            period=period,
            scope_name=scope_name,
            result=result,
            verification_passed=True,
            started_at=started_at,
            completed_at=_completion_timestamp(started_at, utc_clock),
            export_paths=export_paths,
        )
    finally:
        if owns_repository and active_repository is not None:
            try:
                active_repository.close()
            except Exception:
                LOGGER.warning("DuckDB repository close failed")


def format_decide_themes_summary(summary: DecideThemesSummary) -> str:
    """Format a sanitized DECISION-001 plan or completion summary."""

    if summary.plan_only:
        return "\n".join(
            (
                "Theme decision plan:",
                "mode=plan-only",
                f"month={summary.month}",
                f"decision_policy_version={summary.decision_policy_version}",
                "network=disabled",
                "configuration=disabled",
                "database=disabled",
                "file_writes=disabled",
            )
        )
    export_text = "parquet_export=skipped" if summary.skip_export else "parquet_export=written"
    return "\n".join(
        (
            "Theme decision workflow complete:",
            f"month={summary.month}",
            f"decision_policy_version={summary.decision_policy_version}",
            f"summary_count={summary.summary_row_count}",
            f"launch_window_count={summary.launch_window_row_count}",
            f"risk_count={summary.risk_row_count}",
            f"category_fit_count={summary.category_fit_row_count}",
            f"migration_hypothesis_count={summary.migration_hypothesis_row_count}",
            f"recommendation_distribution={_format_distribution(summary.recommendation_distribution)}",
            f"confidence_distribution={_format_distribution(summary.confidence_distribution)}",
            f"market_size_distribution={_format_distribution(summary.market_size_distribution)}",
            f"growth_quality_distribution={_format_distribution(summary.growth_quality_distribution)}",
            f"verification={summary.verification}",
            "network=disabled",
            "feishu=disabled",
            export_text,
        )
    )


def _export_decision_tables(
    repository: DecisionThemesRepository,
    export_directory: Path,
) -> tuple[Path, Path, Path, Path, Path]:
    paths = (
        export_directory / "theme_decision_summaries.parquet",
        export_directory / "theme_launch_window_assessments.parquet",
        export_directory / "theme_decision_risks.parquet",
        export_directory / "theme_category_fit_assessments.parquet",
        export_directory / "theme_migration_hypotheses.parquet",
    )
    repository.export_theme_decision_summaries_to_parquet(paths[0])
    repository.export_theme_launch_window_assessments_to_parquet(paths[1])
    repository.export_theme_decision_risks_to_parquet(paths[2])
    repository.export_theme_category_fit_assessments_to_parquet(paths[3])
    repository.export_theme_migration_hypotheses_to_parquet(paths[4])
    return paths


def _verify_post_commit(
    repository: DecisionThemesRepository,
    expected: ThemeDecisionResult,
    target_key: SnapshotPeriodKey,
) -> None:
    try:
        actual = ThemeDecisionResult(
            decision_summaries=tuple(
                repository.get_theme_decision_summaries(
                    scope_name=target_key.scope_name,
                    cadence=target_key.cadence,
                    period_start=target_key.period_start,
                    period_end=target_key.period_end,
                    decision_policy_version=DECISION_POLICY_VERSION,
                )
            ),
            launch_window_assessments=tuple(
                repository.get_theme_launch_window_assessments(
                    scope_name=target_key.scope_name,
                    cadence=target_key.cadence,
                    period_start=target_key.period_start,
                    period_end=target_key.period_end,
                    decision_policy_version=DECISION_POLICY_VERSION,
                )
            ),
            decision_risks=tuple(
                repository.get_theme_decision_risks(
                    scope_name=target_key.scope_name,
                    cadence=target_key.cadence,
                    period_start=target_key.period_start,
                    period_end=target_key.period_end,
                    decision_policy_version=DECISION_POLICY_VERSION,
                )
            ),
            category_fit_assessments=tuple(
                repository.get_theme_category_fit_assessments(
                    scope_name=target_key.scope_name,
                    cadence=target_key.cadence,
                    period_start=target_key.period_start,
                    period_end=target_key.period_end,
                    decision_policy_version=DECISION_POLICY_VERSION,
                )
            ),
            migration_hypotheses=tuple(
                repository.get_theme_migration_hypotheses(
                    scope_name=target_key.scope_name,
                    cadence=target_key.cadence,
                    period_start=target_key.period_start,
                    period_end=target_key.period_end,
                    decision_policy_version=DECISION_POLICY_VERSION,
                )
            ),
        )
    except Exception as error:
        raise DecisionReadbackVerificationError(
            "post-commit decision verification failed"
        ) from error
    if actual != expected:
        raise DecisionReadbackVerificationError(
            "post-commit decision counts or identities did not match"
        )


def _require_one_target_row[TDecisionRow](
    rows: Sequence[TDecisionRow],
    *,
    target_key: SnapshotPeriodKey,
    label: str,
) -> TDecisionRow:
    values = tuple(rows)
    if len(values) != 1:
        raise DecisionThemesError(f"required {label} evidence is missing or ambiguous")
    period_start = _validate_row_period(values[0], target_key=target_key, label=label)
    if period_start != target_key.period_start:
        raise DecisionThemesError(f"{label} evidence does not match the target month")
    return values[0]


def _require_target_rows[TDecisionRow](
    rows: Sequence[TDecisionRow],
    *,
    target_key: SnapshotPeriodKey,
    label: str,
) -> tuple[TDecisionRow, ...]:
    values = tuple(rows)
    if not values:
        raise DecisionThemesError(f"required {label} evidence is missing")
    for row in values:
        period_start = _validate_row_period(row, target_key=target_key, label=label)
        if period_start != target_key.period_start:
            raise DecisionThemesError(f"{label} evidence does not match the target month")
    return values


def _require_optional_target_rows[TDecisionRow](
    rows: Sequence[TDecisionRow],
    *,
    target_key: SnapshotPeriodKey,
    label: str,
) -> tuple[TDecisionRow, ...]:
    values = tuple(rows)
    for row in values:
        period_start = _validate_row_period(row, target_key=target_key, label=label)
        if period_start != target_key.period_start:
            raise DecisionThemesError(f"{label} evidence does not match the target month")
    return values


def _require_trailing_rows[TDecisionRow](
    rows: Sequence[TDecisionRow],
    *,
    target_key: SnapshotPeriodKey,
    window_start: date,
    label: str,
) -> tuple[TDecisionRow, ...]:
    values = tuple(rows)
    for row in values:
        period_start = _validate_row_period(row, target_key=target_key, label=label)
        if period_start < window_start:
            raise DecisionThemesError(f"{label} evidence exceeds the trailing 12-month window")
    return values


def _validate_row_period(row: object, *, target_key: SnapshotPeriodKey, label: str) -> date:
    row_key = (
        getattr(row, "scope_name", None),
        getattr(row, "cadence", None),
        getattr(row, "period_start", None),
        getattr(row, "period_end", None),
    )
    if row_key[0] != target_key.scope_name or row_key[1] != target_key.cadence:
        raise DecisionThemesError(f"{label} evidence has a mixed scope or cadence")
    row_start = row_key[2]
    row_end = row_key[3]
    if not isinstance(row_start, date) or not isinstance(row_end, date):
        raise DecisionThemesError(f"{label} evidence has an invalid period")
    if row_end != _month_end(row_start) or row_start.day != 1:
        raise DecisionThemesError(f"{label} evidence is not a natural month")
    if row_start > target_key.period_start:
        raise DecisionThemesError(f"{label} evidence contains a future month")
    if row_start == target_key.period_start and row_end != target_key.period_end:
        raise DecisionThemesError(f"{label} evidence does not match the target month")
    if row_start < target_key.period_start and row_end >= target_key.period_end:
        raise DecisionThemesError(f"{label} evidence has an invalid target identity")
    return row_start


def _build_summary(
    *,
    request: DecideThemesRequest,
    period: MonthlyPeriod,
    scope_name: str | None,
    result: ThemeDecisionResult | None,
    verification_passed: bool,
    started_at: datetime,
    completed_at: datetime,
    export_paths: tuple[Path | None, ...] = (None, None, None, None, None),
) -> DecideThemesSummary:
    summaries = () if result is None else result.decision_summaries
    return DecideThemesSummary(
        month=period.month,
        period_start=period.period_start,
        period_end=period.period_end,
        scope_name=scope_name,
        decision_policy_version=DECISION_POLICY_VERSION,
        summary_row_count=len(summaries),
        launch_window_row_count=0 if result is None else len(result.launch_window_assessments),
        risk_row_count=0 if result is None else len(result.decision_risks),
        category_fit_row_count=0 if result is None else len(result.category_fit_assessments),
        migration_hypothesis_row_count=0 if result is None else len(result.migration_hypotheses),
        recommendation_distribution=_distribution(
            row.recommendation.value for row in summaries
        ),
        confidence_distribution=_distribution(row.confidence.value for row in summaries),
        market_size_distribution=_distribution(row.market_size_band.value for row in summaries),
        growth_quality_distribution=_distribution(
            row.growth_quality_state.value for row in summaries
        ),
        verification_passed=verification_passed,
        database_path=request.database_path,
        summaries_parquet_path=export_paths[0],
        launch_windows_parquet_path=export_paths[1],
        risks_parquet_path=export_paths[2],
        category_fits_parquet_path=export_paths[3],
        migrations_parquet_path=export_paths[4],
        plan_only=request.plan_only,
        skip_export=request.skip_export,
        started_at=started_at,
        completed_at=completed_at,
    )


def _distribution(values: Iterable[str]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(values).items()))


def _format_distribution(values: Sequence[tuple[str, int]]) -> str:
    return ",".join(f"{key}:{count}" for key, count in values) or "none"


def _resolve_started_at(
    current_utc: datetime | date | None,
    utc_clock: Callable[[], datetime] | None,
) -> datetime:
    if current_utc is not None:
        value = (
            datetime.combine(current_utc, datetime.min.time(), tzinfo=UTC)
            if isinstance(current_utc, date) and not isinstance(current_utc, datetime)
            else current_utc
        )
    elif utc_clock is not None:
        value = utc_clock()
    else:
        value = datetime.now(UTC)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowError("workflow clock must be timezone-aware")
    return value


def _completion_timestamp(
    started_at: datetime,
    utc_clock: Callable[[], datetime] | None,
) -> datetime:
    if utc_clock is None:
        return datetime.now(UTC)
    value = utc_clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowError("workflow clock must be timezone-aware")
    return value


def _month_end(month_start: date) -> date:
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    return next_month.fromordinal(next_month.toordinal() - 1)


def _month_shift(month_start: date, offset: int) -> date:
    month_index = month_start.year * 12 + month_start.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)
