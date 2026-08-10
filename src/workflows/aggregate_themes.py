"""Local, no-network orchestration for monthly Game Theme aggregation."""

from __future__ import annotations

import calendar
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from typing import Protocol

from ..analysis.errors import AggregationError, MissingSourcePeriodError
from ..analysis.theme_monthly import aggregate_monthly_theme_metrics
from ..config import AppConfig
from ..storage import (
    AppMetadataRow,
    DuckDBRepository,
    MarketSnapshotRow,
    MonthlyMarketTotal,
    SnapshotPeriodKey,
    ThemeMonthlyMetric,
)
from .errors import WorkflowError
from .models import (
    AggregateThemesRequest,
    AggregateThemesSummary,
    BackfillMonthRange,
)

LOGGER = logging.getLogger(__name__)


class AggregationRepository(Protocol):
    """Minimal DuckDB repository boundary needed by this workflow."""

    def open(self) -> object:
        """Open the local database."""

    def initialize_schema(self) -> None:
        """Create or migrate the explicitly supported schema."""

    def get_market_snapshot_period(self, key: SnapshotPeriodKey) -> list[MarketSnapshotRow]:
        """Read one complete stored source period."""

    def get_app_metadata(
        self,
        unified_app_ids: Sequence[object],
    ) -> Mapping[str, AppMetadataRow]:
        """Read normalized metadata for the selected source IDs."""

    def replace_theme_monthly_range(
        self,
        monthly_totals: Sequence[MonthlyMarketTotal],
        theme_metrics: Sequence[ThemeMonthlyMetric],
    ) -> None:
        """Atomically replace both derived tables for the requested range."""

    def export_monthly_market_totals_to_parquet(self, path: str | Path) -> None:
        """Export monthly totals."""

    def export_theme_monthly_metrics_to_parquet(self, path: str | Path) -> None:
        """Export theme metrics."""

    def close(self) -> None:
        """Close the local database."""


RepositoryFactory = Callable[[Path], AggregationRepository]
ExportFunction = Callable[[AggregationRepository, Path], None]


def aggregate_themes(
    request: AggregateThemesRequest,
    config: AppConfig,
    *,
    current_utc: datetime | date | None = None,
    utc_clock: Callable[[], datetime] | None = None,
    repository: AggregationRepository | None = None,
    repository_factory: RepositoryFactory | None = None,
    repository_initialized: bool = False,
    monthly_totals_exporter: ExportFunction | None = None,
    theme_metrics_exporter: ExportFunction | None = None,
) -> AggregateThemesSummary:
    """Validate or execute a deterministic aggregation over stored DuckDB rows.

    The plan-only branch returns before a repository is built or opened.  The
    real branch reads source snapshots and current normalized metadata only;
    this workflow never constructs a Sensor Tower client.
    """

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
    if request.plan_only:
        return _build_summary(
            request=request,
            month_range=month_range,
            aggregated_month_count=0,
            monthly_totals_row_count=0,
            theme_metrics_row_count=0,
            source_snapshot_row_count=0,
            source_missing_theme_count=0,
            source_units_coverage_count=0,
            source_revenue_coverage_count=0,
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
        current_rows_by_period: list[tuple[MarketSnapshotRow, ...]] = []
        previous_rows_by_key: dict[SnapshotPeriodKey, tuple[MarketSnapshotRow, ...] | None] = {}
        all_current_ids: list[str] = []
        for period in month_range.periods:
            current_key = SnapshotPeriodKey(
                scope_name=scope_name,
                cadence=period.cadence,
                period_start=period.period_start,
                period_end=period.period_end,
            )
            current_rows = tuple(active_repository.get_market_snapshot_period(current_key))
            if not current_rows:
                raise MissingSourcePeriodError(period.month)
            if any(row.period_key != current_key for row in current_rows):
                raise AggregationError("source period identity is mixed or invalid")
            current_rows_by_period.append(current_rows)
            all_current_ids.extend(row.unified_app_id for row in current_rows)

            previous_key = _previous_period_key(current_key)
            previous_rows = tuple(active_repository.get_market_snapshot_period(previous_key))
            previous_rows_by_key[previous_key] = previous_rows or None

        metadata_by_id = active_repository.get_app_metadata(all_current_ids)
        result = aggregate_monthly_theme_metrics(
            current_rows_by_period,
            metadata_by_id,
            previous_periods=previous_rows_by_key,
            calculated_at=started_at,
        )
        active_repository.replace_theme_monthly_range(
            result.monthly_totals,
            result.theme_metrics,
        )

        monthly_totals_parquet_path: Path | None = None
        theme_metrics_parquet_path: Path | None = None
        if not request.skip_export:
            monthly_totals_parquet_path = (
                request.export_directory / "monthly_market_totals.parquet"
            )
            theme_metrics_parquet_path = (
                request.export_directory / "theme_monthly_metrics.parquet"
            )
            totals_export = (
                _export_monthly_totals
                if monthly_totals_exporter is None
                else monthly_totals_exporter
            )
            metrics_export = (
                _export_theme_metrics
                if theme_metrics_exporter is None
                else theme_metrics_exporter
            )
            totals_export(active_repository, monthly_totals_parquet_path)
            metrics_export(active_repository, theme_metrics_parquet_path)

        return _build_summary(
            request=request,
            month_range=month_range,
            aggregated_month_count=len(month_range.periods),
            monthly_totals_row_count=len(result.monthly_totals),
            theme_metrics_row_count=len(result.theme_metrics),
            source_snapshot_row_count=sum(len(rows) for rows in current_rows_by_period),
            source_missing_theme_count=sum(
                row.theme_missing_count for row in result.monthly_totals
            ),
            source_units_coverage_count=sum(
                row.units_absolute_coverage_count for row in result.monthly_totals
            ),
            source_revenue_coverage_count=sum(
                row.revenue_absolute_coverage_count for row in result.monthly_totals
            ),
            started_at=started_at,
            completed_at=_completion_timestamp(started_at, utc_clock),
            monthly_totals_parquet_path=monthly_totals_parquet_path,
            theme_metrics_parquet_path=theme_metrics_parquet_path,
        )
    finally:
        if owns_repository and active_repository is not None:
            try:
                active_repository.close()
            except Exception:
                LOGGER.warning("DuckDB repository close failed")


def format_aggregate_themes_summary(summary: AggregateThemesSummary) -> str:
    """Format a concise sanitized aggregation result."""

    month_sequence = ",".join(summary.planned_months)
    if summary.plan_only:
        return (
            "Theme aggregation plan validated: "
            f"start_month={summary.start_month} end_month={summary.end_month} "
            f"planned_month_count={summary.planned_month_count} "
            f"month_sequence={month_sequence} plan_only=true "
            f"database_path={summary.database_path} network=disabled files=none"
        )

    export_text = (
        f"monthly_totals_parquet_path={summary.monthly_totals_parquet_path} "
        f"theme_metrics_parquet_path={summary.theme_metrics_parquet_path}"
        if summary.monthly_totals_parquet_path is not None
        and summary.theme_metrics_parquet_path is not None
        else "parquet_export=skipped"
    )
    return (
        "Theme aggregation complete: "
        f"start_month={summary.start_month} end_month={summary.end_month} "
        f"planned_month_count={summary.planned_month_count} "
        f"aggregated_month_count={summary.aggregated_month_count} "
        f"monthly_totals_row_count={summary.monthly_totals_row_count} "
        f"theme_metrics_row_count={summary.theme_metrics_row_count} "
        f"source_snapshot_row_count={summary.source_snapshot_row_count} "
        f"source_missing_theme_count={summary.source_missing_theme_count} "
        f"source_units_coverage_count={summary.source_units_coverage_count} "
        f"source_revenue_coverage_count={summary.source_revenue_coverage_count} "
        f"database_path={summary.database_path} {export_text}"
    )

def _build_summary(
    *,
    request: AggregateThemesRequest,
    month_range: BackfillMonthRange,
    aggregated_month_count: int,
    monthly_totals_row_count: int,
    theme_metrics_row_count: int,
    source_snapshot_row_count: int,
    source_missing_theme_count: int,
    source_units_coverage_count: int,
    source_revenue_coverage_count: int,
    started_at: datetime,
    completed_at: datetime,
    monthly_totals_parquet_path: Path | None = None,
    theme_metrics_parquet_path: Path | None = None,
) -> AggregateThemesSummary:
    return AggregateThemesSummary(
        start_month=month_range.start_month,
        end_month=month_range.end_month,
        planned_month_count=len(month_range.periods),
        planned_months=month_range.months,
        aggregated_month_count=aggregated_month_count,
        monthly_totals_row_count=monthly_totals_row_count,
        theme_metrics_row_count=theme_metrics_row_count,
        source_snapshot_row_count=source_snapshot_row_count,
        source_missing_theme_count=source_missing_theme_count,
        source_units_coverage_count=source_units_coverage_count,
        source_revenue_coverage_count=source_revenue_coverage_count,
        database_path=request.database_path,
        monthly_totals_parquet_path=monthly_totals_parquet_path,
        theme_metrics_parquet_path=theme_metrics_parquet_path,
        plan_only=request.plan_only,
        started_at=started_at,
        completed_at=completed_at,
    )


def _export_monthly_totals(repository: AggregationRepository, path: Path) -> None:
    repository.export_monthly_market_totals_to_parquet(path)


def _export_theme_metrics(repository: AggregationRepository, path: Path) -> None:
    repository.export_theme_monthly_metrics_to_parquet(path)


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


def _previous_period_key(key: SnapshotPeriodKey) -> SnapshotPeriodKey:
    previous_start = key.period_start - timedelta(days=1)
    previous_start = previous_start.replace(day=1)
    previous_end = date(
        previous_start.year,
        previous_start.month,
        calendar.monthrange(previous_start.year, previous_start.month)[1],
    )
    return SnapshotPeriodKey(
        scope_name=key.scope_name,
        cadence="monthly",
        period_start=previous_start,
        period_end=previous_end,
    )
