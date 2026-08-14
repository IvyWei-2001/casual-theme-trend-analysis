"""Local, no-network orchestration for BACKTEST-001."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from datetime import time as datetime_time
from pathlib import Path
from typing import Protocol

from ..analysis.backtest_models import (
    BACKTEST_OUTCOME_HORIZONS,
    FEATURE_DEFINITIONS,
    PRIMARY_OUTCOME_NAMES,
    ThemeBacktestFeatureMetric,
    ThemeBacktestSegmentMetric,
    ThemeLaunchWindowBacktestResult,
    ThemeLaunchWindowOutcome,
)
from ..analysis.backtest_v1 import (
    calculate_theme_launch_window_backtest,
    validate_backtest_source_identity_compatibility,
)
from ..analysis.errors import BacktestValidationError, MissingSourcePeriodError
from ..analysis.model_v2_models import ThemeModelSummary, ThemeSeasonalityProfile
from ..analysis.models import MonthlyMarketTotal
from ..analysis.opportunity_models import ThemeGrowthSourceMetric, ThemeMarketStructureMetric
from ..analysis.trend_models import ThemeTrendScore
from ..config import AppConfig
from ..storage import DuckDBRepository
from .errors import (
    BacktestReadbackVerificationError,
    BacktestThemesError,
    InvalidMonthError,
    WorkflowError,
)
from .models import BackfillMonthRange, BacktestThemesRequest, BacktestThemesSummary

LOGGER = logging.getLogger(__name__)


class BacktestThemesRepository(Protocol):
    """Minimal repository boundary needed by BACKTEST-001."""

    def open(self) -> object:
        """Open the local database."""

    def initialize_schema(self) -> None:
        """Create or migrate the supported schema."""

    def get_monthly_market_totals(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> list[MonthlyMarketTotal]:
        """Read month-wide totals."""

    def get_theme_market_structure_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeMarketStructureMetric]:
        """Read decision and future market-structure rows."""

    def get_theme_growth_source_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeGrowthSourceMetric]:
        """Read decision-month growth-source rows."""

    def get_theme_trend_scores(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeTrendScore]:
        """Read stored legacy score rows without recalculating them."""

    def get_theme_model_summaries(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeModelSummary]:
        """Read stored MODEL-002 summary rows."""

    def get_theme_seasonality_profiles(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
        metric_name: str | None = None,
        calendar_month: int | None = None,
    ) -> list[ThemeSeasonalityProfile]:
        """Read decision-month seasonality profiles."""

    def replace_theme_backtest_range(
        self,
        outcomes: Sequence[ThemeLaunchWindowOutcome],
        feature_metrics: Sequence[ThemeBacktestFeatureMetric],
        segment_metrics: Sequence[ThemeBacktestSegmentMetric],
    ) -> None:
        """Atomically replace all BACKTEST-001 output sets."""

    def get_theme_launch_window_outcomes(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        decision_period_start: date | None = None,
        decision_period_end: date | None = None,
        game_theme: str | None = None,
        outcome_horizon_months: int | None = None,
    ) -> list[ThemeLaunchWindowOutcome]:
        """Read raw outcome rows."""

    def get_theme_backtest_feature_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        backtest_start: date | None = None,
        backtest_end: date | None = None,
        outcome_horizon_months: int | None = None,
        feature_name: str | None = None,
        feature_group: str | None = None,
        outcome_name: str | None = None,
    ) -> list[ThemeBacktestFeatureMetric]:
        """Read feature-metric rows."""

    def get_theme_backtest_segment_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        backtest_start: date | None = None,
        backtest_end: date | None = None,
        outcome_horizon_months: int | None = None,
        segment_name: str | None = None,
        segment_value: str | None = None,
        outcome_name: str | None = None,
    ) -> list[ThemeBacktestSegmentMetric]:
        """Read segment-metric rows."""

    def export_theme_launch_window_outcomes_to_parquet(self, path: str | Path) -> None:
        """Export raw outcomes."""

    def export_theme_backtest_feature_metrics_to_parquet(self, path: str | Path) -> None:
        """Export feature metrics."""

    def export_theme_backtest_segment_metrics_to_parquet(self, path: str | Path) -> None:
        """Export segment metrics."""

    def close(self) -> None:
        """Close the local database."""


RepositoryFactory = Callable[[Path], BacktestThemesRepository]
ExportFunction = Callable[[BacktestThemesRepository, Path], None]


def backtest_themes(
    request: BacktestThemesRequest,
    config: AppConfig,
    *,
    current_utc: datetime | date | None = None,
    utc_clock: Callable[[], datetime] | None = None,
    repository: BacktestThemesRepository | None = None,
    repository_factory: RepositoryFactory | None = None,
    repository_initialized: bool = False,
    outcomes_exporter: ExportFunction | None = None,
    feature_exporter: ExportFunction | None = None,
    segment_exporter: ExportFunction | None = None,
) -> BacktestThemesSummary:
    """Validate or execute a leakage-safe local launch-window backtest."""

    if repository is not None and repository_factory is not None:
        raise WorkflowError("provide either repository or repository_factory, not both")
    if not isinstance(repository_initialized, bool):
        raise WorkflowError("repository_initialized must be a boolean")

    started_at = _resolve_started_at(current_utc, utc_clock)
    month_range = BackfillMonthRange.parse(
        request.start_month,
        request.end_month,
        current_utc=started_at,
    )
    if len(month_range.periods) < 7:
        raise InvalidMonthError("BACKTEST-001 requires at least seven completed months")
    planned_counts = _planned_decision_counts(len(month_range.periods))
    if request.plan_only:
        return _build_summary(
            request=request,
            month_range=month_range,
            planned_counts=planned_counts,
            source_model_summary_row_count=0,
            source_legacy_6m_score_row_count=0,
            result=None,
            verification_passed=False,
            started_at=started_at,
            completed_at=_completion_timestamp(started_at, utc_clock),
        )

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
        start = month_range.periods[0].period_start
        end = month_range.periods[-1].period_end
        monthly_totals = active_repository.get_monthly_market_totals(
            scope_name=scope_name,
            cadence="monthly",
            period_start=start,
            period_end=end,
        )
        structures = active_repository.get_theme_market_structure_metrics(
            scope_name=scope_name,
            cadence="monthly",
            period_start=start,
            period_end=end,
        )
        growth_sources = active_repository.get_theme_growth_source_metrics(
            scope_name=scope_name,
            cadence="monthly",
            period_start=start,
            period_end=end,
        )
        trend_scores = active_repository.get_theme_trend_scores(
            scope_name=scope_name,
            cadence="monthly",
            period_start=start,
            period_end=end,
        )
        summaries = active_repository.get_theme_model_summaries(
            scope_name=scope_name,
            cadence="monthly",
            period_start=start,
            period_end=end,
        )
        seasonality_profiles = active_repository.get_theme_seasonality_profiles(
            scope_name=scope_name,
            cadence="monthly",
            period_start=start,
            period_end=end,
        )
        _require_requested_history(month_range, scope_name, monthly_totals)
        _require_source_compatibility(
            monthly_totals,
            structures,
            growth_sources,
            trend_scores,
            summaries,
        )
        result = calculate_theme_launch_window_backtest(
            monthly_totals,
            structures,
            growth_sources,
            trend_scores,
            summaries,
            seasonality_profiles,
            calculated_at=started_at,
        )
        active_repository.replace_theme_backtest_range(
            result.outcomes,
            result.feature_metrics,
            result.segment_metrics,
        )
        _verify_readback(
            active_repository,
            result,
            scope_name=scope_name,
            start=start,
            end=end,
        )

        outcomes_parquet_path: Path | None = None
        feature_parquet_path: Path | None = None
        segment_parquet_path: Path | None = None
        if not request.skip_export:
            outcomes_parquet_path = (
                request.export_directory / "theme_launch_window_outcomes.parquet"
            )
            feature_parquet_path = (
                request.export_directory / "theme_backtest_feature_metrics.parquet"
            )
            segment_parquet_path = (
                request.export_directory / "theme_backtest_segment_metrics.parquet"
            )
            (outcomes_exporter or _export_outcomes)(active_repository, outcomes_parquet_path)
            (feature_exporter or _export_features)(active_repository, feature_parquet_path)
            (segment_exporter or _export_segments)(active_repository, segment_parquet_path)

        return _build_summary(
            request=request,
            month_range=month_range,
            planned_counts=planned_counts,
            source_model_summary_row_count=len(summaries),
            source_legacy_6m_score_row_count=len(trend_scores),
            result=result,
            verification_passed=True,
            started_at=started_at,
            completed_at=_completion_timestamp(started_at, utc_clock),
            outcomes_parquet_path=outcomes_parquet_path,
            feature_metrics_parquet_path=feature_parquet_path,
            segment_metrics_parquet_path=segment_parquet_path,
        )
    except (BacktestValidationError, ValueError) as error:
        raise BacktestThemesError("BACKTEST-001 evidence validation failed") from error
    finally:
        if owns_repository and active_repository is not None:
            try:
                active_repository.close()
            except Exception:
                LOGGER.warning("DuckDB repository close failed")


def format_backtest_themes_summary(summary: BacktestThemesSummary) -> str:
    """Format a sanitized BACKTEST-001 plan or completion summary."""

    if summary.plan_only:
        return "\n".join(
            (
                "Theme launch-window backtest plan:",
                "mode=plan-only",
                f"start_month={summary.start_month}",
                f"end_month={summary.end_month}",
                f"history_month_count={summary.history_month_count}",
                "outcome_horizons=1,2,3",
                f"legacy_6m_decision_month_count_t1={summary.legacy_6m_decision_month_count_t1}",
                f"legacy_6m_decision_month_count_t2={summary.legacy_6m_decision_month_count_t2}",
                f"legacy_6m_decision_month_count_t3={summary.legacy_6m_decision_month_count_t3}",
                f"model_12m_decision_month_count_t1={summary.model_12m_decision_month_count_t1}",
                f"model_12m_decision_month_count_t2={summary.model_12m_decision_month_count_t2}",
                f"model_12m_decision_month_count_t3={summary.model_12m_decision_month_count_t3}",
                f"model_36m_decision_month_count_t1={summary.model_36m_decision_month_count_t1}",
                f"model_36m_decision_month_count_t2={summary.model_36m_decision_month_count_t2}",
                f"model_36m_decision_month_count_t3={summary.model_36m_decision_month_count_t3}",
                f"seasonality_decision_month_count_t1={summary.seasonality_decision_month_count_t1}",
                f"seasonality_decision_month_count_t2={summary.seasonality_decision_month_count_t2}",
                f"seasonality_decision_month_count_t3={summary.seasonality_decision_month_count_t3}",
                f"feature_definition_count={summary.feature_definition_count}",
                f"primary_outcome_count={summary.primary_outcome_count}",
                f"planned_feature_metric_row_count={summary.planned_feature_metric_row_count}",
                "network=disabled",
                "database=disabled",
                "file_writes=disabled",
            )
        )
    export_text = (
        "parquet_export=skipped"
        if summary.outcomes_parquet_path is None
        else "parquet_export=written"
    )
    return "\n".join(
        (
            "Theme launch-window backtest complete:",
            f"start_month={summary.start_month}",
            f"end_month={summary.end_month}",
            f"history_month_count={summary.history_month_count}",
            f"source_model_summary_row_count={summary.source_model_summary_row_count}",
            f"source_legacy_6m_score_row_count={summary.source_legacy_6m_score_row_count}",
            f"outcome_row_count={summary.outcome_row_count}",
            f"horizon_1_outcome_row_count={summary.horizon_1_outcome_row_count}",
            f"horizon_2_outcome_row_count={summary.horizon_2_outcome_row_count}",
            f"horizon_3_outcome_row_count={summary.horizon_3_outcome_row_count}",
            f"horizon_1_decision_month_count={summary.horizon_1_decision_month_count}",
            f"horizon_2_decision_month_count={summary.horizon_2_decision_month_count}",
            f"horizon_3_decision_month_count={summary.horizon_3_decision_month_count}",
            f"future_theme_absent_row_count={summary.future_theme_absent_row_count}",
            f"downloads_outcome_unavailable_count={summary.downloads_outcome_unavailable_count}",
            f"revenue_outcome_unavailable_count={summary.revenue_outcome_unavailable_count}",
            f"feature_metric_row_count={summary.feature_metric_row_count}",
            f"segment_metric_row_count={summary.segment_metric_row_count}",
            f"zero_eligible_36m_feature_metric_count={summary.zero_eligible_36m_feature_metric_count}",
            f"low_sample_feature_metric_count={summary.low_sample_feature_metric_count}",
            f"low_sample_segment_metric_count={summary.low_sample_segment_metric_count}",
            "verification=passed" if summary.verification_passed else "verification=not_run",
            "network=disabled",
            "feishu=disabled",
            export_text,
        )
    )


def _planned_decision_counts(history_month_count: int) -> dict[tuple[int, int], int]:
    return {
        (feature, horizon): max(0, history_month_count - feature + 1 - horizon)
        for feature in (6, 12, 36, 24)
        for horizon in BACKTEST_OUTCOME_HORIZONS
    }


def _build_summary(
    *,
    request: BacktestThemesRequest,
    month_range: BackfillMonthRange,
    planned_counts: dict[tuple[int, int], int],
    source_model_summary_row_count: int,
    source_legacy_6m_score_row_count: int,
    result: ThemeLaunchWindowBacktestResult | None,
    verification_passed: bool,
    started_at: datetime,
    completed_at: datetime,
    outcomes_parquet_path: Path | None = None,
    feature_metrics_parquet_path: Path | None = None,
    segment_metrics_parquet_path: Path | None = None,
) -> BacktestThemesSummary:
    outcomes = () if result is None else result.outcomes
    features = () if result is None else result.feature_metrics
    segments = () if result is None else result.segment_metrics
    return BacktestThemesSummary(
        start_month=month_range.start_month,
        end_month=month_range.end_month,
        history_month_count=len(month_range.periods),
        legacy_6m_decision_month_count_t1=planned_counts[(6, 1)],
        legacy_6m_decision_month_count_t2=planned_counts[(6, 2)],
        legacy_6m_decision_month_count_t3=planned_counts[(6, 3)],
        model_12m_decision_month_count_t1=planned_counts[(12, 1)],
        model_12m_decision_month_count_t2=planned_counts[(12, 2)],
        model_12m_decision_month_count_t3=planned_counts[(12, 3)],
        model_36m_decision_month_count_t1=planned_counts[(36, 1)],
        model_36m_decision_month_count_t2=planned_counts[(36, 2)],
        model_36m_decision_month_count_t3=planned_counts[(36, 3)],
        seasonality_decision_month_count_t1=planned_counts[(24, 1)],
        seasonality_decision_month_count_t2=planned_counts[(24, 2)],
        seasonality_decision_month_count_t3=planned_counts[(24, 3)],
        feature_definition_count=len(FEATURE_DEFINITIONS),
        primary_outcome_count=len(PRIMARY_OUTCOME_NAMES),
        planned_feature_metric_row_count=len(FEATURE_DEFINITIONS)
        * len(PRIMARY_OUTCOME_NAMES)
        * len(BACKTEST_OUTCOME_HORIZONS),
        source_model_summary_row_count=source_model_summary_row_count,
        source_legacy_6m_score_row_count=source_legacy_6m_score_row_count,
        outcome_row_count=len(outcomes),
        horizon_1_outcome_row_count=sum(row.outcome_horizon_months == 1 for row in outcomes),
        horizon_2_outcome_row_count=sum(row.outcome_horizon_months == 2 for row in outcomes),
        horizon_3_outcome_row_count=sum(row.outcome_horizon_months == 3 for row in outcomes),
        horizon_1_decision_month_count=_decision_month_count(outcomes, 1),
        horizon_2_decision_month_count=_decision_month_count(outcomes, 2),
        horizon_3_decision_month_count=_decision_month_count(outcomes, 3),
        future_theme_absent_row_count=sum(not row.future_theme_present for row in outcomes),
        downloads_outcome_unavailable_count=sum(
            row.future_downloads_share is None for row in outcomes
        ),
        revenue_outcome_unavailable_count=sum(
            row.future_revenue_usd_share is None for row in outcomes
        ),
        feature_metric_row_count=len(features),
        segment_metric_row_count=len(segments),
        zero_eligible_36m_feature_metric_count=sum(
            row.feature_name in {"median_normalized_slope_36m", "stability_cv_median_36m"}
            and row.eligible_row_count == 0
            for row in features
        ),
        low_sample_feature_metric_count=sum(row.low_sample_warning for row in features),
        low_sample_segment_metric_count=sum(row.low_sample_warning for row in segments),
        verification_passed=verification_passed,
        database_path=request.database_path,
        outcomes_parquet_path=outcomes_parquet_path,
        feature_metrics_parquet_path=feature_metrics_parquet_path,
        segment_metrics_parquet_path=segment_metrics_parquet_path,
        plan_only=request.plan_only,
        started_at=started_at,
        completed_at=completed_at,
    )


def _decision_month_count(rows: Sequence[ThemeLaunchWindowOutcome], horizon: int) -> int:
    return len({row.decision_period_start for row in rows if row.outcome_horizon_months == horizon})


def _require_requested_history(
    month_range: BackfillMonthRange,
    scope_name: str,
    monthly_totals: Sequence[MonthlyMarketTotal],
) -> None:
    totals_by_period = {
        (row.scope_name, row.period_start, row.period_end): row for row in monthly_totals
    }
    if len(totals_by_period) != len(monthly_totals):
        raise BacktestThemesError("monthly totals contain duplicate identities")
    for period in month_range.periods:
        key = (scope_name, period.period_start, period.period_end)
        total = totals_by_period.get(key)
        if total is None or total.snapshot_count <= 0:
            raise MissingSourcePeriodError(period.month)


def _require_source_compatibility(
    monthly_totals: Sequence[MonthlyMarketTotal],
    structures: Sequence[ThemeMarketStructureMetric],
    growth_sources: Sequence[ThemeGrowthSourceMetric],
    trend_scores: Sequence[ThemeTrendScore],
    summaries: Sequence[ThemeModelSummary],
) -> None:
    try:
        validate_backtest_source_identity_compatibility(
            monthly_totals,
            structures,
            growth_sources,
            trend_scores,
            summaries,
        )
    except BacktestValidationError as error:
        raise BacktestThemesError("BACKTEST-001 source identities are incompatible") from error


def _verify_readback(
    repository: BacktestThemesRepository,
    result: ThemeLaunchWindowBacktestResult,
    *,
    scope_name: str,
    start: date,
    end: date,
) -> None:
    actual_outcomes = repository.get_theme_launch_window_outcomes(
        scope_name=scope_name,
        cadence="monthly",
        decision_period_start=start,
        decision_period_end=end,
    )
    actual_features = repository.get_theme_backtest_feature_metrics(
        scope_name=scope_name,
        cadence="monthly",
        backtest_start=start,
        backtest_end=end,
    )
    actual_segments = repository.get_theme_backtest_segment_metrics(
        scope_name=scope_name,
        cadence="monthly",
        backtest_start=start,
        backtest_end=end,
    )
    if (
        len(actual_outcomes) != len(result.outcomes)
        or set(actual_outcomes) != set(result.outcomes)
        or len(actual_features) != len(result.feature_metrics)
        or set(actual_features) != set(result.feature_metrics)
        or len(actual_segments) != len(result.segment_metrics)
        or set(actual_segments) != set(result.segment_metrics)
    ):
        raise BacktestReadbackVerificationError("BACKTEST-001 readback verification failed")


def _export_outcomes(repository: BacktestThemesRepository, path: Path) -> None:
    repository.export_theme_launch_window_outcomes_to_parquet(path)


def _export_features(repository: BacktestThemesRepository, path: Path) -> None:
    repository.export_theme_backtest_feature_metrics_to_parquet(path)


def _export_segments(repository: BacktestThemesRepository, path: Path) -> None:
    repository.export_theme_backtest_segment_metrics_to_parquet(path)


def _resolve_started_at(
    current_utc: datetime | date | None,
    utc_clock: Callable[[], datetime] | None,
) -> datetime:
    value: datetime | date
    if current_utc is None:
        if utc_clock is None:
            raise WorkflowError("current UTC time must be supplied by the caller")
        value = utc_clock()
    else:
        value = current_utc
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise WorkflowError("workflow timestamps must be timezone-aware")
        return value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime_time.min, tzinfo=UTC)
    raise WorkflowError("current UTC time must be a date or timezone-aware datetime")


def _completion_timestamp(
    started_at: datetime,
    utc_clock: Callable[[], datetime] | None,
) -> datetime:
    if utc_clock is None:
        return started_at
    completed_at = utc_clock()
    if completed_at.tzinfo is None or completed_at.utcoffset() is None:
        raise WorkflowError("workflow timestamps must be timezone-aware")
    return completed_at.astimezone(UTC)


__all__ = ["BacktestThemesRepository", "backtest_themes", "format_backtest_themes_summary"]
