"""Resumable, manually executable historical monthly backfill orchestration."""

from __future__ import annotations

import logging
import time as time_module
from collections.abc import Callable
from datetime import UTC, date, datetime
from datetime import time as datetime_time
from pathlib import Path

from ..config import AppConfig
from ..sensor_tower import SensorTowerClient, SensorTowerError
from ..sensor_tower.errors import SensorTowerConfigurationError
from ..storage import DuckDBRepository, SnapshotPeriodKey, StorageError
from .collect_month import (
    CollectionClient,
    CollectionRepository,
    ExportFunction,
    MetadataSleep,
    collect_month,
)
from .errors import (
    BackfillFailureKind,
    BackfillMonthsError,
    WorkflowError,
)
from .models import (
    BackfillMonthRange,
    BackfillMonthsRequest,
    BackfillMonthsSummary,
    CollectMonthRequest,
)

LOGGER = logging.getLogger(__name__)


def backfill_months(
    request: BackfillMonthsRequest,
    config: AppConfig,
    *,
    current_utc: datetime | date | None = None,
    utc_clock: Callable[[], datetime] | None = None,
    client: CollectionClient | None = None,
    client_factory: Callable[[], CollectionClient] | None = None,
    repository: CollectionRepository | None = None,
    repository_factory: Callable[[Path], CollectionRepository] | None = None,
    metadata_sleep: MetadataSleep = time_module.sleep,
    market_exporter: ExportFunction | None = None,
    metadata_exporter: ExportFunction | None = None,
) -> BackfillMonthsSummary:
    """Validate and execute an inclusive oldest-to-newest monthly backfill.

    The workflow owns resources it creates through factories, reuses them for
    every collected month, and delegates all Sensor Tower, cache, mapping,
    transaction, and export behavior to the existing boundaries.
    """

    if client is not None and client_factory is not None:
        raise WorkflowError("provide either client or client_factory, not both")
    if repository is not None and repository_factory is not None:
        raise WorkflowError("provide either repository or repository_factory, not both")

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
            collected_month_count=0,
            skipped_existing_month_count=0,
            failed_month=None,
            total_candidate_count=0,
            total_selected_count=0,
            total_metadata_cache_fresh_count=0,
            total_metadata_requested_count=0,
            total_metadata_returned_count=0,
            total_metadata_unresolved_count=0,
            total_snapshot_rows_written=0,
            started_at=started_at,
            completed_at=_completion_timestamp(started_at, utc_clock),
        )

    active_repository = repository
    owns_repository = False
    active_client = client
    owns_client = False
    try:
        if active_repository is None:
            repository_builder = (
                DuckDBRepository if repository_factory is None else repository_factory
            )
            active_repository = repository_builder(request.database_path)
            owns_repository = True
        active_repository.open()
        active_repository.initialize_schema()

        scope_name = config.sensor_tower_selection_config.scope_name
        collected_month_count = 0
        skipped_existing_month_count = 0
        total_candidate_count = 0
        total_selected_count = 0
        total_metadata_cache_fresh_count = 0
        total_metadata_requested_count = 0
        total_metadata_returned_count = 0
        total_metadata_unresolved_count = 0
        total_snapshot_rows_written = 0

        for period in month_range.periods:
            period_key = SnapshotPeriodKey(
                scope_name=scope_name,
                cadence=period.cadence,
                period_start=period.period_start,
                period_end=period.period_end,
            )
            try:
                existing_rows = active_repository.get_market_snapshot_period(period_key)
            except Exception as error:
                raise _month_failure(period.month, error) from None
            if existing_rows and not request.refresh_existing:
                skipped_existing_month_count += 1
                continue

            if active_client is None:
                try:
                    active_client = _build_client(config, client_factory)
                except Exception as error:
                    raise _month_failure(period.month, error) from None
                owns_client = True

            month_request = CollectMonthRequest(
                month=period.month,
                database_path=request.database_path,
                export_directory=request.export_directory,
                plan_only=False,
                skip_export=True,
            )
            try:
                month_summary = collect_month(
                    month_request,
                    config,
                    current_utc=started_at,
                    client=active_client,
                    repository=active_repository,
                    repository_initialized=True,
                    include_monetization=False,
                    metadata_sleep=metadata_sleep,
                )
            except Exception as error:
                raise _month_failure(period.month, error) from None

            collected_month_count += 1
            total_candidate_count += month_summary.candidate_count
            total_selected_count += month_summary.selected_count
            total_metadata_cache_fresh_count += month_summary.metadata_cache_fresh_count
            total_metadata_requested_count += month_summary.metadata_requested_count
            total_metadata_returned_count += month_summary.metadata_returned_count
            total_metadata_unresolved_count += month_summary.metadata_unresolved_count
            total_snapshot_rows_written += month_summary.snapshot_rows_written

        market_parquet_path: Path | None = None
        metadata_parquet_path: Path | None = None
        if not request.skip_export:
            market_parquet_path = request.export_directory / "market_snapshots.parquet"
            metadata_parquet_path = request.export_directory / "app_metadata.parquet"
            market_export = (
                _export_market_snapshots
                if market_exporter is None
                else market_exporter
            )
            metadata_export = (
                _export_app_metadata
                if metadata_exporter is None
                else metadata_exporter
            )
            market_export(active_repository, market_parquet_path)
            metadata_export(active_repository, metadata_parquet_path)

        return _build_summary(
            request=request,
            month_range=month_range,
            collected_month_count=collected_month_count,
            skipped_existing_month_count=skipped_existing_month_count,
            failed_month=None,
            total_candidate_count=total_candidate_count,
            total_selected_count=total_selected_count,
            total_metadata_cache_fresh_count=total_metadata_cache_fresh_count,
            total_metadata_requested_count=total_metadata_requested_count,
            total_metadata_returned_count=total_metadata_returned_count,
            total_metadata_unresolved_count=total_metadata_unresolved_count,
            total_snapshot_rows_written=total_snapshot_rows_written,
            started_at=started_at,
            completed_at=_completion_timestamp(started_at, utc_clock),
            market_parquet_path=market_parquet_path,
            metadata_parquet_path=metadata_parquet_path,
        )
    finally:
        if owns_client and active_client is not None:
            _close_client(active_client)
        if owns_repository and active_repository is not None:
            _close_repository(active_repository)


def format_backfill_summary(summary: BackfillMonthsSummary) -> str:
    """Format a concise summary containing month names but no product IDs."""

    month_sequence = ",".join(summary.planned_months)
    if summary.plan_only:
        return (
            "Backfill plan validated: "
            f"start_month={summary.start_month} end_month={summary.end_month} "
            f"planned_month_count={summary.planned_month_count} "
            f"month_sequence={month_sequence} plan_only=true "
            f"database_path={summary.database_path} network=disabled files=none"
        )

    export_text = (
        f"market_parquet_path={summary.market_parquet_path} "
        f"metadata_parquet_path={summary.metadata_parquet_path}"
        if summary.market_parquet_path is not None
        and summary.metadata_parquet_path is not None
        else "parquet_export=skipped"
    )
    return (
        "Backfill complete: "
        f"start_month={summary.start_month} end_month={summary.end_month} "
        f"planned_month_count={summary.planned_month_count} "
        f"collected_month_count={summary.collected_month_count} "
        f"skipped_existing_month_count={summary.skipped_existing_month_count} "
        f"total_candidate_count={summary.total_candidate_count} "
        f"total_selected_count={summary.total_selected_count} "
        f"total_metadata_cache_fresh_count={summary.total_metadata_cache_fresh_count} "
        f"total_metadata_requested_count={summary.total_metadata_requested_count} "
        f"total_metadata_returned_count={summary.total_metadata_returned_count} "
        f"total_metadata_unresolved_count={summary.total_metadata_unresolved_count} "
        f"total_snapshot_rows_written={summary.total_snapshot_rows_written} "
        f"database_path={summary.database_path} {export_text}"
    )


def _build_client(
    config: AppConfig,
    client_factory: Callable[[], CollectionClient] | None,
) -> CollectionClient:
    if client_factory is not None:
        client = client_factory()
        if client is None:
            raise WorkflowError("Sensor Tower client factory returned no client")
        return client
    return SensorTowerClient.from_config(config.sensor_tower_client_config)


def _month_failure(month: str, error: Exception) -> BackfillMonthsError:
    """Map expected month failures to a safe public category and message."""

    if isinstance(error, SensorTowerConfigurationError):
        kind: BackfillFailureKind = "configuration"
        reason = "local Sensor Tower configuration is invalid"
    elif isinstance(error, SensorTowerError):
        kind = "sensor_tower"
        reason = "Sensor Tower workflow failed"
    elif isinstance(error, StorageError) or isinstance(error, OSError):
        kind = "storage"
        reason = "local storage operation failed"
    elif isinstance(error, WorkflowError):
        kind = "workflow"
        reason = "workflow failed"
    else:
        kind = "workflow"
        reason = "workflow failed"
    LOGGER.error("monthly backfill stopped: month=%s reason=%s", month, reason)
    return BackfillMonthsError(month, failure_kind=kind, reason=reason)


def _build_summary(
    *,
    request: BackfillMonthsRequest,
    month_range: BackfillMonthRange,
    collected_month_count: int,
    skipped_existing_month_count: int,
    failed_month: str | None,
    total_candidate_count: int,
    total_selected_count: int,
    total_metadata_cache_fresh_count: int,
    total_metadata_requested_count: int,
    total_metadata_returned_count: int,
    total_metadata_unresolved_count: int,
    total_snapshot_rows_written: int,
    started_at: datetime,
    completed_at: datetime,
    market_parquet_path: Path | None = None,
    metadata_parquet_path: Path | None = None,
) -> BackfillMonthsSummary:
    return BackfillMonthsSummary(
        start_month=month_range.start_month,
        end_month=month_range.end_month,
        planned_month_count=len(month_range.periods),
        planned_months=month_range.months,
        collected_month_count=collected_month_count,
        skipped_existing_month_count=skipped_existing_month_count,
        failed_month=failed_month,
        total_candidate_count=total_candidate_count,
        total_selected_count=total_selected_count,
        total_metadata_cache_fresh_count=total_metadata_cache_fresh_count,
        total_metadata_requested_count=total_metadata_requested_count,
        total_metadata_returned_count=total_metadata_returned_count,
        total_metadata_unresolved_count=total_metadata_unresolved_count,
        total_snapshot_rows_written=total_snapshot_rows_written,
        database_path=request.database_path,
        market_parquet_path=market_parquet_path,
        metadata_parquet_path=metadata_parquet_path,
        plan_only=request.plan_only,
        started_at=started_at,
        completed_at=completed_at,
    )


def _export_market_snapshots(repository: CollectionRepository, path: Path) -> None:
    repository.export_market_snapshots_to_parquet(path)


def _export_app_metadata(repository: CollectionRepository, path: Path) -> None:
    repository.export_app_metadata_to_parquet(path)


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


def _close_client(client: CollectionClient) -> None:
    try:
        client.close()
    except Exception:
        LOGGER.warning("Sensor Tower client close failed")


def _close_repository(repository: CollectionRepository) -> None:
    try:
        repository.close()
    except Exception:
        LOGGER.warning("DuckDB repository close failed")
