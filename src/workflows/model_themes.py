"""Local, no-network orchestration for the MODEL-002 evidence model."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from datetime import time as datetime_time
from math import isclose
from pathlib import Path
from typing import Protocol

from ..analysis.errors import AggregationError, MissingSourcePeriodError
from ..analysis.model_v2 import calculate_theme_model_metrics
from ..analysis.model_v2_models import ThemeModelResult
from ..analysis.trend_models import ThemeTrendScore
from ..analysis.trend_score import calculate_theme_trend_scores
from ..config import AppConfig
from ..storage import (
    DuckDBRepository,
    MonthlyMarketTotal,
    SnapshotPeriodKey,
    ThemeHorizonMetric,
    ThemeMarketStructureMetric,
    ThemeModelSummary,
    ThemeMonthlyMetric,
    ThemeSeasonalityProfile,
)
from .errors import ModelReadbackVerificationError, WorkflowError
from .models import BackfillMonthRange, ModelThemesRequest, ModelThemesSummary, MonthlyPeriod

LOGGER = logging.getLogger(__name__)


class ModelThemesRepository(Protocol):
    """Minimal repository boundary needed by MODEL-002."""

    def open(self) -> object:
        """Open the local database."""

    def initialize_schema(self) -> None:
        """Create or migrate the explicitly supported schema."""

    def get_monthly_market_totals(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> list[MonthlyMarketTotal]:
        """Read month-wide AGG-001 totals."""

    def get_theme_monthly_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeMonthlyMetric]:
        """Read legacy AGG-001 theme metrics."""

    def get_theme_market_structure_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeMarketStructureMetric]:
        """Read AGG-002 market-structure evidence."""

    def replace_theme_model_range(
        self,
        trend_scores: Sequence[ThemeTrendScore],
        horizon_metrics: Sequence[ThemeHorizonMetric],
        model_summaries: Sequence[ThemeModelSummary],
        seasonality_profiles: Sequence[ThemeSeasonalityProfile],
        *,
        target_periods: Sequence[SnapshotPeriodKey],
        trend_target_periods: Sequence[SnapshotPeriodKey] | None = None,
    ) -> None:
        """Atomically replace the four MODEL-002 output sets."""

    def get_theme_trend_scores(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeTrendScore]:
        """Read refreshed legacy score rows."""

    def get_theme_horizon_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
        horizon_month_count: int | None = None,
        metric_name: str | None = None,
    ) -> list[ThemeHorizonMetric]:
        """Read horizon evidence rows."""

    def get_theme_model_summaries(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeModelSummary]:
        """Read model summary rows."""

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
        """Read seasonality profile rows."""

    def export_theme_trend_scores_to_parquet(self, path: str | Path) -> None:
        """Export the legacy score baseline."""

    def export_theme_horizon_metrics_to_parquet(self, path: str | Path) -> None:
        """Export horizon evidence."""

    def export_theme_model_summaries_to_parquet(self, path: str | Path) -> None:
        """Export model summaries."""

    def export_theme_seasonality_profiles_to_parquet(self, path: str | Path) -> None:
        """Export seasonality profiles."""

    def close(self) -> None:
        """Close the local database."""


RepositoryFactory = Callable[[Path], ModelThemesRepository]
ExportFunction = Callable[[ModelThemesRepository, Path], None]


def model_themes(
    request: ModelThemesRequest,
    config: AppConfig,
    *,
    current_utc: datetime | date | None = None,
    utc_clock: Callable[[], datetime] | None = None,
    repository: ModelThemesRepository | None = None,
    repository_factory: RepositoryFactory | None = None,
    repository_initialized: bool = False,
    trend_exporter: ExportFunction | None = None,
    horizon_exporter: ExportFunction | None = None,
    summaries_exporter: ExportFunction | None = None,
    seasonality_exporter: ExportFunction | None = None,
) -> ModelThemesSummary:
    """Validate or execute MODEL-002 over an existing local DuckDB history."""

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
    horizon_target_counts = {
        horizon: max(0, len(month_range.periods) - horizon + 1)
        for horizon in (6, 12, 36)
    }
    seasonality_target_count = max(0, len(month_range.periods) - 24 + 1)
    if request.plan_only:
        return _build_summary(
            request=request,
            month_range=month_range,
            source_market_structure_row_count=0,
            horizon_target_counts=horizon_target_counts,
            seasonality_target_count=seasonality_target_count,
            trend_rows=(),
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
        theme_metrics = active_repository.get_theme_monthly_metrics(
            scope_name=scope_name,
            cadence="monthly",
            period_start=start,
            period_end=end,
        )
        structure_metrics = active_repository.get_theme_market_structure_metrics(
            scope_name=scope_name,
            cadence="monthly",
            period_start=start,
            period_end=end,
        )
        _require_requested_history(
            month_range,
            scope_name,
            monthly_totals,
            theme_metrics,
            structure_metrics,
        )

        trend_rows = (
            calculate_theme_trend_scores(
                monthly_totals,
                theme_metrics,
                calculated_at=started_at,
            )
            if len(month_range.periods) >= 6
            else ()
        )
        result = calculate_theme_model_metrics(
            monthly_totals,
            structure_metrics,
            calculated_at=started_at,
        )
        target_period_keys = tuple(
            _period_key(scope_name, period) for period in month_range.periods
        )
        trend_target_keys = tuple(
            _period_key(scope_name, period) for period in month_range.periods[5:]
        ) if len(month_range.periods) >= 6 else ()
        active_repository.replace_theme_model_range(
            trend_rows,
            result.horizon_metrics,
            result.model_summaries,
            result.seasonality_profiles,
            target_periods=target_period_keys,
            trend_target_periods=trend_target_keys,
        )
        _verify_readback(
            active_repository,
            trend_rows,
            result,
            structure_metrics,
            scope_name=scope_name,
            month_range=month_range,
        )

        trend_parquet_path: Path | None = None
        horizon_parquet_path: Path | None = None
        summaries_parquet_path: Path | None = None
        seasonality_parquet_path: Path | None = None
        if not request.skip_export:
            trend_parquet_path = request.export_directory / "theme_trend_scores.parquet"
            horizon_parquet_path = request.export_directory / "theme_horizon_metrics.parquet"
            summaries_parquet_path = request.export_directory / "theme_model_summaries.parquet"
            seasonality_parquet_path = (
                request.export_directory / "theme_seasonality_profiles.parquet"
            )
            (trend_exporter or _export_trend_scores)(active_repository, trend_parquet_path)
            (horizon_exporter or _export_horizon_metrics)(active_repository, horizon_parquet_path)
            (summaries_exporter or _export_model_summaries)(
                active_repository,
                summaries_parquet_path,
            )
            (seasonality_exporter or _export_seasonality_profiles)(
                active_repository,
                seasonality_parquet_path,
            )

        return _build_summary(
            request=request,
            month_range=month_range,
            source_market_structure_row_count=len(structure_metrics),
            horizon_target_counts=horizon_target_counts,
            seasonality_target_count=seasonality_target_count,
            trend_rows=trend_rows,
            result=result,
            verification_passed=True,
            started_at=started_at,
            completed_at=_completion_timestamp(started_at, utc_clock),
            trend_parquet_path=trend_parquet_path,
            horizon_parquet_path=horizon_parquet_path,
            summaries_parquet_path=summaries_parquet_path,
            seasonality_parquet_path=seasonality_parquet_path,
        )
    finally:
        if owns_repository and active_repository is not None:
            try:
                active_repository.close()
            except Exception:
                LOGGER.warning("DuckDB repository close failed")


def format_model_themes_summary(summary: ModelThemesSummary) -> str:
    """Format a sanitized MODEL-002 plan or completion summary."""

    if summary.plan_only:
        return (
            "Theme model plan:\n"
            "mode=plan-only\n"
            f"start_month={summary.start_month}\n"
            f"end_month={summary.end_month}\n"
            f"history_month_count={summary.history_month_count}\n"
            f"horizon_6m_target_month_count={summary.horizon_6m_target_month_count}\n"
            f"horizon_12m_target_month_count={summary.horizon_12m_target_month_count}\n"
            f"horizon_36m_target_month_count={summary.horizon_36m_target_month_count}\n"
            f"seasonality_target_month_count={summary.seasonality_target_month_count}\n"
            "legacy_6m_baseline=recomputed_with_existing_formula\n"
            "new_outputs=theme_horizon_metrics,theme_model_summaries,"
            "theme_seasonality_profiles\n"
            "network=disabled\n"
            "database=disabled\n"
            "file_writes=disabled"
        )

    export_text = (
        "parquet_export=skipped"
        if summary.trend_parquet_path is None
        else "parquet_export=written"
    )
    return "\n".join(
        (
            "Theme model calculation complete:",
            f"start_month={summary.start_month}",
            f"end_month={summary.end_month}",
            f"history_month_count={summary.history_month_count}",
            f"source_market_structure_row_count={summary.source_market_structure_row_count}",
            f"legacy_6m_score_row_count={summary.legacy_6m_score_row_count}",
            f"horizon_metric_row_count={summary.horizon_metric_row_count}",
            f"horizon_6m_row_count={summary.horizon_6m_row_count}",
            f"horizon_12m_row_count={summary.horizon_12m_row_count}",
            f"horizon_36m_row_count={summary.horizon_36m_row_count}",
            f"model_summary_row_count={summary.model_summary_row_count}",
            f"seasonality_profile_row_count={summary.seasonality_profile_row_count}",
            f"seasonality_profile_group_count={summary.seasonality_profile_group_count}",
            f"lifecycle_insufficient_history_count={summary.lifecycle_insufficient_history_count}",
            f"lifecycle_emerging_count={summary.lifecycle_emerging_count}",
            f"lifecycle_accelerating_count={summary.lifecycle_accelerating_count}",
            f"lifecycle_growing_count={summary.lifecycle_growing_count}",
            f"lifecycle_mature_count={summary.lifecycle_mature_count}",
            f"lifecycle_recovering_count={summary.lifecycle_recovering_count}",
            f"lifecycle_declining_count={summary.lifecycle_declining_count}",
            f"lifecycle_mixed_count={summary.lifecycle_mixed_count}",
            "verification=passed" if summary.verification_passed else "verification=not_run",
            "network=disabled",
            "feishu=disabled",
            export_text,
        )
    )


def _build_summary(
    *,
    request: ModelThemesRequest,
    month_range: BackfillMonthRange,
    source_market_structure_row_count: int,
    horizon_target_counts: dict[int, int],
    seasonality_target_count: int,
    trend_rows: Sequence[ThemeTrendScore],
    result: ThemeModelResult | None,
    verification_passed: bool,
    started_at: datetime,
    completed_at: datetime,
    trend_parquet_path: Path | None = None,
    horizon_parquet_path: Path | None = None,
    summaries_parquet_path: Path | None = None,
    seasonality_parquet_path: Path | None = None,
) -> ModelThemesSummary:
    horizon_rows = () if result is None else result.horizon_metrics
    summaries = () if result is None else result.model_summaries
    seasonality_rows = () if result is None else result.seasonality_profiles
    return ModelThemesSummary(
        start_month=month_range.start_month,
        end_month=month_range.end_month,
        history_month_count=len(month_range.periods),
        source_market_structure_row_count=source_market_structure_row_count,
        horizon_6m_target_month_count=horizon_target_counts[6],
        horizon_12m_target_month_count=horizon_target_counts[12],
        horizon_36m_target_month_count=horizon_target_counts[36],
        seasonality_target_month_count=seasonality_target_count,
        legacy_6m_score_row_count=len(trend_rows),
        horizon_metric_row_count=len(horizon_rows),
        horizon_6m_row_count=sum(row.horizon_month_count == 6 for row in horizon_rows),
        horizon_12m_row_count=sum(row.horizon_month_count == 12 for row in horizon_rows),
        horizon_36m_row_count=sum(row.horizon_month_count == 36 for row in horizon_rows),
        model_summary_row_count=len(summaries),
        seasonality_profile_row_count=len(seasonality_rows),
        seasonality_profile_group_count=len(
            {
                (
                    row.scope_name,
                    row.cadence,
                    row.period_start,
                    row.period_end,
                    row.game_theme,
                    row.metric_name,
                )
                for row in seasonality_rows
            }
        ),
        lifecycle_insufficient_history_count=sum(
            row.lifecycle_stage == "insufficient_history" for row in summaries
        ),
        lifecycle_emerging_count=sum(row.lifecycle_stage == "emerging" for row in summaries),
        lifecycle_accelerating_count=sum(
            row.lifecycle_stage == "accelerating" for row in summaries
        ),
        lifecycle_growing_count=sum(row.lifecycle_stage == "growing" for row in summaries),
        lifecycle_mature_count=sum(row.lifecycle_stage == "mature" for row in summaries),
        lifecycle_recovering_count=sum(row.lifecycle_stage == "recovering" for row in summaries),
        lifecycle_declining_count=sum(row.lifecycle_stage == "declining" for row in summaries),
        lifecycle_mixed_count=sum(row.lifecycle_stage == "mixed" for row in summaries),
        verification_passed=verification_passed,
        database_path=request.database_path,
        trend_parquet_path=trend_parquet_path,
        horizon_parquet_path=horizon_parquet_path,
        summaries_parquet_path=summaries_parquet_path,
        seasonality_parquet_path=seasonality_parquet_path,
        plan_only=request.plan_only,
        started_at=started_at,
        completed_at=completed_at,
    )


def _require_requested_history(
    month_range: BackfillMonthRange,
    scope_name: str,
    monthly_totals: Sequence[MonthlyMarketTotal],
    theme_metrics: Sequence[ThemeMonthlyMetric],
    structure_metrics: Sequence[ThemeMarketStructureMetric],
) -> None:
    expected_periods = {
        (scope_name, period.period_start, period.period_end) for period in month_range.periods
    }
    totals_by_period = {
        (row.scope_name, row.period_start, row.period_end): row for row in monthly_totals
    }
    if len(totals_by_period) != len(monthly_totals):
        raise AggregationError("MODEL-002 monthly totals contain duplicate identities")
    for period in month_range.periods:
        key = (scope_name, period.period_start, period.period_end)
        total = totals_by_period.get(key)
        if total is None:
            raise MissingSourcePeriodError(period.month)
        if total.snapshot_count <= 0:
            raise MissingSourcePeriodError(period.month)

    for row in monthly_totals:
        if (row.scope_name, row.period_start, row.period_end) not in expected_periods:
            raise AggregationError("MODEL-002 source rows are outside the requested range")
    for theme_metric_row in theme_metrics:
        if (
            theme_metric_row.scope_name,
            theme_metric_row.period_start,
            theme_metric_row.period_end,
        ) not in expected_periods:
            raise AggregationError("MODEL-002 source rows are outside the requested range")
    for structure_row in structure_metrics:
        if (
            structure_row.scope_name,
            structure_row.period_start,
            structure_row.period_end,
        ) not in expected_periods:
            raise AggregationError("MODEL-002 source rows are outside the requested range")

    theme_identities = {
        (row.scope_name, row.period_start, row.period_end, row.game_theme)
        for row in theme_metrics
    }
    structure_identities = {
        (row.scope_name, row.period_start, row.period_end, row.game_theme)
        for row in structure_metrics
    }
    if theme_identities != structure_identities:
        raise AggregationError("AGG-001 and AGG-002 theme identities do not match")
    if len(theme_identities) != len(theme_metrics) or len(structure_identities) != len(
        structure_metrics
    ):
        raise AggregationError("AGG-001 and AGG-002 theme identities contain duplicates")
    for total in totals_by_period.values():
        key = (total.scope_name, total.period_start, total.period_end)
        has_theme_metrics = any(identity[:3] == key for identity in theme_identities)
        if total.theme_present_count > 0 and not has_theme_metrics:
            raise MissingSourcePeriodError(total.period_start.strftime("%Y-%m"))


def _verify_readback(
    repository: ModelThemesRepository,
    trend_rows: Sequence[ThemeTrendScore],
    result: ThemeModelResult,
    structure_metrics: Sequence[ThemeMarketStructureMetric],
    *,
    scope_name: str,
    month_range: BackfillMonthRange,
) -> None:
    start = month_range.periods[0].period_start
    end = month_range.periods[-1].period_end
    actual_scores = repository.get_theme_trend_scores(
        scope_name=scope_name,
        period_start=start,
        period_end=end,
    )
    actual_horizons = repository.get_theme_horizon_metrics(
        scope_name=scope_name,
        period_start=start,
        period_end=end,
    )
    actual_summaries = repository.get_theme_model_summaries(
        scope_name=scope_name,
        period_start=start,
        period_end=end,
    )
    actual_seasonality = repository.get_theme_seasonality_profiles(
        scope_name=scope_name,
        period_start=start,
        period_end=end,
    )
    if len(actual_scores) != len(trend_rows) or _legacy_score_identities(
        actual_scores
    ) != _legacy_score_identities(trend_rows):
        raise ModelReadbackVerificationError("legacy score readback verification failed")
    if (
        len(actual_horizons) != len(result.horizon_metrics)
        or _identities(actual_horizons) != _identities(result.horizon_metrics)
    ):
        raise ModelReadbackVerificationError("horizon readback verification failed")
    if (
        len(actual_summaries) != len(result.model_summaries)
        or _identities(actual_summaries) != _identities(result.model_summaries)
    ):
        raise ModelReadbackVerificationError("summary readback verification failed")
    expected_structure_identities = {
        (
            row.scope_name,
            row.cadence,
            row.period_start,
            row.period_end,
            row.game_theme,
        )
        for row in structure_metrics
    }
    actual_summary_identities = {
        (
            row.scope_name,
            row.cadence,
            row.period_start,
            row.period_end,
            row.game_theme,
        )
        for row in actual_summaries
    }
    if actual_summary_identities != expected_structure_identities:
        raise ModelReadbackVerificationError("summary source identity verification failed")
    if (
        len(actual_seasonality) != len(result.seasonality_profiles)
        or _identities(actual_seasonality) != _identities(result.seasonality_profiles)
    ):
        raise ModelReadbackVerificationError("seasonality readback verification failed")
    _verify_seasonality_groups(actual_seasonality)


def _identities(rows: Sequence[object]) -> set[object]:
    identities: set[object] = set()
    for row in rows:
        if hasattr(row, "period_key"):
            identities.add(row.period_key)
        else:
            raise ModelReadbackVerificationError("MODEL-002 row identity is unavailable")
    return identities


def _verify_seasonality_groups(rows: Sequence[ThemeSeasonalityProfile]) -> None:
    groups: dict[tuple[str, str, date, date, str, str], list[ThemeSeasonalityProfile]] = {}
    for row in rows:
        key = (
            row.scope_name,
            row.cadence,
            row.period_start,
            row.period_end,
            row.game_theme,
            row.metric_name,
        )
        groups.setdefault(key, []).append(row)
    for values in groups.values():
        if len(values) != 12 or {row.calendar_month for row in values} != set(range(1, 13)):
            raise ModelReadbackVerificationError(
                "seasonality calendar-month readback verification failed"
            )
        if sum(row.is_peak_month for row in values) != 1:
            raise ModelReadbackVerificationError("seasonality peak readback verification failed")
        if sum(row.is_trough_month for row in values) != 1:
            raise ModelReadbackVerificationError("seasonality trough readback verification failed")
        if not isclose(
            sum(row.seasonal_index for row in values) / 12,
            1.0,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ModelReadbackVerificationError("seasonality mean readback verification failed")


def _legacy_score_identities(
    rows: Sequence[ThemeTrendScore],
) -> set[tuple[str, str, date, date, str]]:
    """Return the complete legacy score identity, including the raw theme."""

    return {
        (
            row.scope_name,
            row.cadence,
            row.period_start,
            row.period_end,
            row.game_theme,
        )
        for row in rows
    }


def _period_key(scope_name: str, period: MonthlyPeriod) -> SnapshotPeriodKey:
    return SnapshotPeriodKey(
        scope_name=scope_name,
        cadence="monthly",
        period_start=period.period_start,
        period_end=period.period_end,
    )


def _export_trend_scores(repository: ModelThemesRepository, path: Path) -> None:
    repository.export_theme_trend_scores_to_parquet(path)


def _export_horizon_metrics(repository: ModelThemesRepository, path: Path) -> None:
    repository.export_theme_horizon_metrics_to_parquet(path)


def _export_model_summaries(repository: ModelThemesRepository, path: Path) -> None:
    repository.export_theme_model_summaries_to_parquet(path)


def _export_seasonality_profiles(repository: ModelThemesRepository, path: Path) -> None:
    repository.export_theme_seasonality_profiles_to_parquet(path)


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


__all__ = ["ModelThemesRepository", "format_model_themes_summary", "model_themes"]
