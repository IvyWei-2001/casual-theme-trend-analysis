"""Local, no-network orchestration for monthly Game Theme trend scoring."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from datetime import time as datetime_time
from pathlib import Path
from typing import Protocol

from ..analysis.errors import AggregationError, MissingSourcePeriodError
from ..analysis.trend_models import ThemeTrendScore
from ..analysis.trend_score import calculate_theme_trend_scores
from ..config import AppConfig
from ..storage import (
    DuckDBRepository,
    MonthlyMarketTotal,
    SnapshotPeriodKey,
    ThemeMonthlyMetric,
)
from .errors import InvalidMonthError, WorkflowError
from .models import (
    BackfillMonthRange,
    MonthlyPeriod,
    ScoreThemesRequest,
    ScoreThemesSummary,
)

LOGGER = logging.getLogger(__name__)


class TrendScoreRepository(Protocol):
    """Minimal repository boundary needed by the score workflow."""

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
        """Read schema-v2 month-wide totals."""

    def get_theme_monthly_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> list[ThemeMonthlyMetric]:
        """Read schema-v2 raw theme metrics."""

    def replace_theme_trend_score_range(
        self,
        rows: Sequence[ThemeTrendScore],
        *,
        target_periods: Sequence[SnapshotPeriodKey] | None = None,
    ) -> None:
        """Atomically replace schema-v3 target-month scores."""

    def export_theme_trend_scores_to_parquet(self, path: str | Path) -> None:
        """Export schema-v3 trend scores."""

    def close(self) -> None:
        """Close the local database."""


RepositoryFactory = Callable[[Path], TrendScoreRepository]
ExportFunction = Callable[[TrendScoreRepository, Path], None]


def score_themes(
    request: ScoreThemesRequest,
    config: AppConfig,
    *,
    current_utc: datetime | date | None = None,
    utc_clock: Callable[[], datetime] | None = None,
    repository: TrendScoreRepository | None = None,
    repository_factory: RepositoryFactory | None = None,
    repository_initialized: bool = False,
    trend_exporter: ExportFunction | None = None,
) -> ScoreThemesSummary:
    """Validate or execute deterministic trend scoring over stored aggregates."""

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
    if len(month_range.periods) < 6:
        raise InvalidMonthError(
            "trend scoring requires at least six consecutive history months"
        )

    scorable_months = month_range.periods[5:]
    if request.plan_only:
        return _build_summary(
            request=request,
            month_range=month_range,
            scorable_months=scorable_months,
            trend_rows=(),
            latest_scores=(),
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
        monthly_totals = active_repository.get_monthly_market_totals(
            scope_name=scope_name,
            cadence="monthly",
            period_start=month_range.periods[0].period_start,
            period_end=month_range.periods[-1].period_end,
        )
        theme_metrics = active_repository.get_theme_monthly_metrics(
            scope_name=scope_name,
            cadence="monthly",
            period_start=month_range.periods[0].period_start,
            period_end=month_range.periods[-1].period_end,
        )
        _require_requested_history(month_range, scope_name, monthly_totals, theme_metrics)

        trend_rows = calculate_theme_trend_scores(
            monthly_totals,
            theme_metrics,
            calculated_at=started_at,
        )
        target_period_keys = tuple(
            SnapshotPeriodKey(
                scope_name=scope_name,
                cadence=period.cadence,
                period_start=period.period_start,
                period_end=period.period_end,
            )
            for period in scorable_months
        )
        active_repository.replace_theme_trend_score_range(
            trend_rows,
            target_periods=target_period_keys,
        )

        trend_parquet_path: Path | None = None
        if not request.skip_export:
            trend_parquet_path = request.export_directory / "theme_trend_scores.parquet"
            exporter = (
                _export_trend_scores
                if trend_exporter is None
                else trend_exporter
            )
            exporter(active_repository, trend_parquet_path)

        latest_target_month = scorable_months[-1].month
        latest_scores = tuple(
            row
            for row in trend_rows
            if row.period_start == scorable_months[-1].period_start
        )
        return _build_summary(
            request=request,
            month_range=month_range,
            scorable_months=scorable_months,
            trend_rows=trend_rows,
            latest_scores=latest_scores,
            started_at=started_at,
            completed_at=_completion_timestamp(started_at, utc_clock),
            trend_parquet_path=trend_parquet_path,
            latest_target_month=latest_target_month,
        )
    finally:
        if owns_repository and active_repository is not None:
            try:
                active_repository.close()
            except Exception:
                LOGGER.warning("DuckDB repository close failed")


def format_score_themes_summary(summary: ScoreThemesSummary) -> str:
    """Format a sanitized summary and the latest target-month ranking."""

    first_target_month = _month_after(summary.start_month, 5)
    if summary.plan_only:
        return (
            "Theme trend scoring plan validated: "
            f"start_month={summary.start_month} end_month={summary.end_month} "
            f"history_month_count={summary.history_month_count} "
            f"scorable_target_month_count={summary.scorable_target_month_count} "
            f"first_scorable_target_month={first_target_month} "
            f"last_scorable_target_month={summary.latest_target_month} "
            f"plan_only=true database_path={summary.database_path} "
            "network=disabled files=none"
        )

    export_text = (
        f"trend_parquet_path={summary.trend_parquet_path}"
        if summary.trend_parquet_path is not None
        else "parquet_export=skipped"
    )
    lines = [
        "Theme trend scoring complete: "
        f"start_month={summary.start_month} end_month={summary.end_month} "
        f"history_month_count={summary.history_month_count} "
        f"scorable_target_month_count={summary.scorable_target_month_count} "
        f"trend_row_count={summary.trend_row_count} "
        f"actionable_row_count={summary.actionable_row_count} "
        f"non_actionable_row_count={summary.non_actionable_row_count} "
        f"latest_target_month={summary.latest_target_month} "
        f"latest_actionable_theme_count={summary.latest_actionable_theme_count} "
        f"database_path={summary.database_path} {export_text}",
        f"Latest target ranking (top={summary.top_n} actionable themes):",
    ]
    latest_actionable = [row for row in summary.latest_scores if row.is_actionable]
    if not latest_actionable:
        lines.append("no_actionable_themes=true")
        return "\n".join(lines)

    for row in latest_actionable[: summary.top_n]:
        lines.append(
            " ".join(
                (
                    f"trend_rank={row.trend_rank}",
                    f"game_theme={row.game_theme}",
                    f"trend_score={_display_number(row.trend_score)}",
                    f"confidence_score={_display_number(row.confidence_score)}",
                    f"growth_score={_display_number(row.growth_score)}",
                    f"acceleration_score={_display_number(row.acceleration_score)}",
                    f"new_product_score={_display_number(row.new_product_score)}",
                    f"concentration_penalty={_display_number(row.concentration_penalty)}",
                    f"latest_product_count={row.latest_product_count}",
                    f"latest_product_share={_display_number(row.latest_product_share)}",
                    "latest_units_absolute_share="
                    f"{_display_number(row.latest_units_absolute_share)}",
                    "latest_revenue_absolute_share="
                    f"{_display_number(row.latest_revenue_absolute_share)}",
                    f"recent3_new_entry_share={_display_number(row.recent3_new_entry_share)}",
                    f"median_rank_improvement={_display_number(row.median_rank_improvement)}",
                    f"revenue_absolute_overindex={_display_number(row.revenue_absolute_overindex)}",
                )
            )
        )
    return "\n".join(lines)


def _build_summary(
    *,
    request: ScoreThemesRequest,
    month_range: BackfillMonthRange,
    scorable_months: Sequence[MonthlyPeriod],
    trend_rows: Sequence[ThemeTrendScore],
    latest_scores: Sequence[ThemeTrendScore],
    started_at: datetime,
    completed_at: datetime,
    trend_parquet_path: Path | None = None,
    latest_target_month: str | None = None,
) -> ScoreThemesSummary:
    resolved_latest_target_month = (
        latest_target_month
        if latest_target_month is not None
        else scorable_months[-1].month
    )
    return ScoreThemesSummary(
        start_month=month_range.start_month,
        end_month=month_range.end_month,
        history_month_count=len(month_range.periods),
        scorable_target_month_count=len(scorable_months),
        trend_row_count=len(trend_rows),
        actionable_row_count=sum(row.is_actionable for row in trend_rows),
        non_actionable_row_count=sum(not row.is_actionable for row in trend_rows),
        latest_target_month=resolved_latest_target_month,
        latest_actionable_theme_count=sum(row.is_actionable for row in latest_scores),
        database_path=request.database_path,
        trend_parquet_path=trend_parquet_path,
        plan_only=request.plan_only,
        started_at=started_at,
        completed_at=completed_at,
        top_n=request.top_n,
        latest_scores=tuple(latest_scores),
    )


def _require_requested_history(
    month_range: BackfillMonthRange,
    scope_name: str,
    monthly_totals: Sequence[MonthlyMarketTotal],
    theme_metrics: Sequence[ThemeMonthlyMetric],
) -> None:
    expected_keys = {
        (scope_name, period.period_start, period.period_end)
        for period in month_range.periods
    }
    total_keys = {
        (row.scope_name, row.period_start, row.period_end)
        for row in monthly_totals
    }
    for period in month_range.periods:
        key = (scope_name, period.period_start, period.period_end)
        if key not in total_keys:
            raise MissingSourcePeriodError(period.month)

    metric_periods = {
        (row.scope_name, row.period_start, row.period_end)
        for row in theme_metrics
    }
    for total in monthly_totals:
        key = (total.scope_name, total.period_start, total.period_end)
        if key not in expected_keys:
            raise AggregationError("monthly total is outside the requested score range")
        if total.snapshot_count <= 0:
            month = total.period_start.strftime("%Y-%m")
            raise MissingSourcePeriodError(month)
        if total.theme_present_count > 0 and key not in metric_periods:
            month = total.period_start.strftime("%Y-%m")
            raise MissingSourcePeriodError(month)


def _export_trend_scores(repository: TrendScoreRepository, path: Path) -> None:
    repository.export_theme_trend_scores_to_parquet(path)


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


def _month_after(month: str, offset: int) -> str:
    year, month_number = (int(value) for value in month.split("-"))
    month_index = year * 12 + month_number - 1 + offset
    result_year, result_month_zero_based = divmod(month_index, 12)
    return f"{result_year:04d}-{result_month_zero_based + 1:02d}"


def _display_number(value: float | None) -> str:
    if value is None:
        return "NULL"
    return f"{value:.6f}"


__all__ = ["TrendScoreRepository", "format_score_themes_summary", "score_themes"]
