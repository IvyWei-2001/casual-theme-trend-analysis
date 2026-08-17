"""Orchestration for one live, completed natural-calendar-month collection."""

from __future__ import annotations

import logging
import time as time_module
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from datetime import time as datetime_time
from pathlib import Path
from typing import Protocol

from ..analysis.monetization_models import (
    AppMonetizationProfile,
    ThemeMonetizationObservabilityMetric,
    build_app_monetization_profiles,
)
from ..analysis.monetization_observability import (
    aggregate_theme_monetization_observability,
)
from ..config import AppConfig
from ..sensor_tower import (
    SensorTowerClient,
    SensorTowerMarketRecord,
    SensorTowerMarketRequest,
    SensorTowerMetadataFetchResult,
    SensorTowerMetadataRequest,
    SensorTowerNormalizedMetadata,
    attach_metadata,
    extract_selected_unified_app_ids,
    fetch_metadata_for_unified_app_ids,
    select_market_records,
)
from ..storage import (
    AppMetadataRow,
    DuckDBRepository,
    MarketSnapshotRow,
    MetadataCacheLookup,
    SnapshotPeriodKey,
    StorageValidationError,
    build_app_metadata_rows,
    build_market_snapshot_rows,
    normalize_storage_opaque_id,
)
from .errors import WorkflowError, WorkflowMetadataIntegrityError
from .models import CollectMonthRequest, CollectMonthSummary, MonthlyPeriod

LOGGER = logging.getLogger(__name__)


class CollectionClient(Protocol):
    """Minimal Sensor Tower client boundary required by this workflow."""

    def fetch_market_candidates(
        self,
        request: SensorTowerMarketRequest,
    ) -> list[SensorTowerMarketRecord]:
        """Fetch and normalize market candidates."""

    def fetch_metadata_batch(
        self,
        request: SensorTowerMetadataRequest,
    ) -> SensorTowerMetadataFetchResult:
        """Fetch and normalize one metadata batch."""

    def close(self) -> None:
        """Close an owned external client when supported."""


class CollectionRepository(Protocol):
    """Minimal DuckDB repository boundary required by this workflow."""

    def open(self) -> object:
        """Open the local database."""

    def initialize_schema(self) -> None:
        """Create or verify the explicitly supported schema."""

    def get_market_snapshot_period(
        self,
        key: SnapshotPeriodKey,
    ) -> list[MarketSnapshotRow]:
        """Read one complete market period in rank order."""

    def lookup_metadata_cache(
        self,
        unified_app_ids: Sequence[object],
        *,
        as_of: datetime,
        max_age_days: int | float,
    ) -> MetadataCacheLookup:
        """Classify cached metadata as fresh, stale, or missing."""

    def upsert_app_metadata(self, rows: Sequence[AppMetadataRow]) -> None:
        """Persist newly fetched metadata rows."""

    def replace_market_snapshot_period(self, rows: Sequence[MarketSnapshotRow]) -> None:
        """Atomically replace one complete market period."""

    def replace_market_snapshot_and_monetization_period(
        self,
        snapshots: Sequence[MarketSnapshotRow],
        profiles: Sequence[AppMonetizationProfile],
        theme_metrics: Sequence[ThemeMonetizationObservabilityMetric],
    ) -> None:
        """Atomically replace source and prospective monetization rows."""

    def export_market_snapshots_to_parquet(self, path: str | Path) -> None:
        """Export market snapshots through the repository boundary."""

    def export_app_metadata_to_parquet(self, path: str | Path) -> None:
        """Export metadata through the repository boundary."""

    def export_app_monetization_profiles_to_parquet(self, path: str | Path) -> None:
        """Export product monetization profiles through the repository boundary."""

    def export_theme_monetization_observability_metrics_to_parquet(
        self,
        path: str | Path,
    ) -> None:
        """Export theme monetization metrics through the repository boundary."""

    def close(self) -> None:
        """Close the local database."""


MetadataSleep = Callable[[float], None]
ClientFactory = Callable[[], CollectionClient]
RepositoryFactory = Callable[[Path], CollectionRepository]
ExportFunction = Callable[[CollectionRepository, Path], None]


def collect_month(
    request: CollectMonthRequest,
    config: AppConfig,
    *,
    current_utc: datetime | date | None = None,
    utc_clock: Callable[[], datetime] | None = None,
    client: CollectionClient | None = None,
    client_factory: ClientFactory | None = None,
    repository: CollectionRepository | None = None,
    repository_factory: RepositoryFactory | None = None,
    repository_initialized: bool = False,
    include_monetization: bool = True,
    metadata_sleep: MetadataSleep = time_module.sleep,
    market_exporter: ExportFunction | None = None,
    metadata_exporter: ExportFunction | None = None,
) -> CollectMonthSummary:
    """Run or validate one manually requested completed monthly collection.

    The default path constructs the real Sensor Tower client only after month
    and local configuration validation. Tests may inject a client and
    repository, which keeps all automated execution independent of credentials,
    network access, and production files.
    """

    if client is not None and client_factory is not None:
        raise WorkflowError("provide either client or client_factory, not both")
    if repository is not None and repository_factory is not None:
        raise WorkflowError("provide either repository or repository_factory, not both")
    if not isinstance(repository_initialized, bool):
        raise WorkflowError("repository_initialized must be a boolean")
    if not isinstance(include_monetization, bool):
        raise WorkflowError("include_monetization must be a boolean")

    if current_utc is None:
        if utc_clock is None:
            raise WorkflowError("current UTC time must be supplied by the caller")
        current_utc = utc_clock()
    started_at = _normalize_utc_datetime(_as_utc_datetime(current_utc))
    period = MonthlyPeriod.parse(request.month, current_utc=started_at)
    market_request = config.build_sensor_tower_market_request(
        period.period_start,
        end_date=period.period_end,
    )
    selection_config = config.sensor_tower_selection_config
    metadata_config = config.sensor_tower_metadata_config

    if request.plan_only:
        completed_at = _completion_timestamp(started_at, utc_clock)
        return _build_summary(
            request=request,
            period=period,
            scope_name=selection_config.scope_name,
            candidate_count=0,
            selected_count=0,
            metadata_cache_fresh_count=0,
            metadata_stale_count=0,
            metadata_missing_count=0,
            metadata_requested_count=0,
            metadata_returned_count=0,
            metadata_unresolved_count=0,
            snapshot_rows_written=0,
            started_at=started_at,
            completed_at=completed_at,
        )

    active_client = client
    owns_client = False
    if active_client is None:
        if client_factory is not None:
            active_client = client_factory()
        else:
            active_client = SensorTowerClient.from_config(config.sensor_tower_client_config)
            owns_client = True

    active_repository = repository
    owns_repository = False
    try:
        candidates = active_client.fetch_market_candidates(market_request)
        candidate_count = len(candidates)
        selected_records = select_market_records(
            candidates,
            allowed_genres=selection_config.allowed_genres,
            final_top_n=selection_config.final_top_n,
            exclude_china_revenue_market=selection_config.exclude_china_revenue_market,
        )
        selected_count = len(selected_records)
        LOGGER.info(
            "monthly market selection completed: candidates=%d selected=%d",
            candidate_count,
            selected_count,
        )
        selected_ids = extract_selected_unified_app_ids(selected_records)

        if active_repository is None:
            factory = DuckDBRepository if repository_factory is None else repository_factory
            active_repository = factory(request.database_path)
            owns_repository = True

        if not repository_initialized:
            active_repository.open()
            active_repository.initialize_schema()
        cache_lookup = active_repository.lookup_metadata_cache(
            selected_ids,
            as_of=started_at,
            max_age_days=config.metadata_cache_max_age_days,
        )

        if cache_lookup.ids_to_fetch:
            fetched_metadata = fetch_metadata_for_unified_app_ids(
                active_client,
                cache_lookup.ids_to_fetch,
                metadata_config,
                sleep=metadata_sleep,
            )
        else:
            fetched_metadata = _empty_metadata_result()

        combined_metadata, unresolved_ids = _combine_metadata(
            cache_lookup,
            fetched_metadata,
            selected_ids,
        )
        combined_result = SensorTowerMetadataFetchResult(
            metadata_by_unified_app_id=combined_metadata,
            requested_unified_app_ids=selected_ids,
            missing_unified_app_ids=unresolved_ids,
            requested_count=len(selected_ids),
            returned_count=len(combined_metadata),
        )
        enriched_records = attach_metadata(selected_records, combined_result)

        snapshot_rows = build_market_snapshot_rows(
            enriched_records,
            scope_name=selection_config.scope_name,
            cadence=period.cadence,
            period_start=period.period_start,
            period_end=period.period_end,
            scope_country=config.sensor_tower_country,
            device_type=config.sensor_tower_device_type,
            category=config.sensor_tower_category,
            data_model=config.sensor_tower_data_model,
            collected_at=started_at,
        )
        newly_fetched_metadata_rows = build_app_metadata_rows(
            fetched_metadata,
            fetched_at=started_at,
        )

        monetization_profiles: list[AppMonetizationProfile] = []
        theme_monetization_metrics: list[ThemeMonetizationObservabilityMetric] = []
        if include_monetization:
            monetization_profiles = build_app_monetization_profiles(
                snapshot_rows,
                calculated_at=started_at,
            )
            theme_monetization_metrics = aggregate_theme_monetization_observability(
                snapshot_rows,
                monetization_profiles,
                calculated_at=started_at,
            )

        if newly_fetched_metadata_rows:
            active_repository.upsert_app_metadata(newly_fetched_metadata_rows)
        if include_monetization:
            active_repository.replace_market_snapshot_and_monetization_period(
                snapshot_rows,
                monetization_profiles,
                theme_monetization_metrics,
            )
        else:
            active_repository.replace_market_snapshot_period(snapshot_rows)

        market_parquet_path: Path | None = None
        metadata_parquet_path: Path | None = None
        app_profiles_parquet_path: Path | None = None
        theme_metrics_parquet_path: Path | None = None
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
            if include_monetization:
                app_profiles_parquet_path = (
                    request.export_directory / "app_monetization_profiles.parquet"
                )
                theme_metrics_parquet_path = (
                    request.export_directory
                    / "theme_monetization_observability_metrics.parquet"
                )
                active_repository.export_app_monetization_profiles_to_parquet(
                    app_profiles_parquet_path
                )
                active_repository.export_theme_monetization_observability_metrics_to_parquet(
                    theme_metrics_parquet_path
                )

        completed_at = _completion_timestamp(started_at, utc_clock)
        return _build_summary(
            request=request,
            period=period,
            scope_name=selection_config.scope_name,
            candidate_count=candidate_count,
            selected_count=selected_count,
            metadata_cache_fresh_count=len(cache_lookup.fresh_metadata_by_id),
            metadata_stale_count=len(cache_lookup.stale_ids),
            metadata_missing_count=len(cache_lookup.missing_ids),
            metadata_requested_count=len(cache_lookup.ids_to_fetch),
            metadata_returned_count=len(fetched_metadata.metadata_by_unified_app_id),
            metadata_unresolved_count=len(unresolved_ids),
            snapshot_rows_written=len(snapshot_rows),
            started_at=started_at,
            completed_at=completed_at,
            market_parquet_path=market_parquet_path,
            metadata_parquet_path=metadata_parquet_path,
            monetization_profile_rows_written=len(monetization_profiles),
            theme_monetization_rows_written=len(theme_monetization_metrics),
            app_profiles_parquet_path=app_profiles_parquet_path,
            theme_metrics_parquet_path=theme_metrics_parquet_path,
        )
    finally:
        if owns_repository and active_repository is not None:
            active_repository.close()
        if owns_client:
            active_client.close()


def app_metadata_row_to_sensor_tower_metadata(
    row: AppMetadataRow,
) -> SensorTowerNormalizedMetadata:
    """Convert one fresh DuckDB cache row back to the adapter's normalized type."""

    if not isinstance(row, AppMetadataRow):
        raise WorkflowMetadataIntegrityError("metadata cache contained an invalid row")
    try:
        return SensorTowerNormalizedMetadata(
            unified_app_id=row.unified_app_id,
            name=row.name,
            publisher_display_name=row.publisher_display_name,
            publisher_resolution_source=row.publisher_resolution_source,
            android_app_id=row.android_app_id,
            ios_app_id=row.ios_app_id,
        )
    except (TypeError, ValueError) as error:
        raise WorkflowMetadataIntegrityError(
            "metadata cache row could not be normalized"
        ) from error


def format_collection_summary(summary: CollectMonthSummary) -> str:
    """Format a concise summary without tokens, URLs, or app-ID lists."""

    if summary.plan_only:
        return (
            "Collection plan validated: "
            f"month={summary.month} period_start={summary.period_start.isoformat()} "
            f"period_end={summary.period_end.isoformat()} cadence=monthly "
            f"scope={summary.scope_name} plan_only=true "
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
        "Collection complete: "
        f"month={summary.month} period_start={summary.period_start.isoformat()} "
        f"period_end={summary.period_end.isoformat()} cadence=monthly "
        f"scope={summary.scope_name} candidate_count={summary.candidate_count} "
        f"selected_count={summary.selected_count} "
        f"metadata_cache_fresh_count={summary.metadata_cache_fresh_count} "
        f"metadata_stale_count={summary.metadata_stale_count} "
        f"metadata_missing_count={summary.metadata_missing_count} "
        f"metadata_requested_count={summary.metadata_requested_count} "
        f"metadata_returned_count={summary.metadata_returned_count} "
        f"metadata_unresolved_count={summary.metadata_unresolved_count} "
        f"snapshot_rows_written={summary.snapshot_rows_written} "
        f"monetization_profile_rows_written={summary.monetization_profile_rows_written} "
        f"theme_monetization_rows_written={summary.theme_monetization_rows_written} "
        f"database_path={summary.database_path} {export_text}"
    )


def _combine_metadata(
    cache_lookup: MetadataCacheLookup,
    fetched_metadata: SensorTowerMetadataFetchResult,
    selected_ids: tuple[str, ...],
) -> tuple[dict[str, SensorTowerNormalizedMetadata], tuple[str, ...]]:
    """Merge fresh cache rows and new results with explicit integrity checks."""

    combined: dict[str, SensorTowerNormalizedMetadata] = {}
    for cache_key, cache_row in cache_lookup.fresh_metadata_by_id.items():
        try:
            normalized_key = normalize_storage_opaque_id(
                cache_key,
                field_name="metadata cache ID",
            )
        except StorageValidationError as error:
            raise WorkflowMetadataIntegrityError(
                "metadata cache contained an invalid ID"
            ) from error
        if normalized_key != cache_row.unified_app_id:
            raise WorkflowMetadataIntegrityError(
                "metadata cache ID did not match its row"
            )
        if normalized_key in combined:
            raise WorkflowMetadataIntegrityError(
                "metadata cache contained duplicate IDs"
            )
        combined[normalized_key] = app_metadata_row_to_sensor_tower_metadata(cache_row)

    expected_fetched_ids = tuple(cache_lookup.ids_to_fetch)
    if tuple(fetched_metadata.requested_unified_app_ids) != expected_fetched_ids:
        raise WorkflowMetadataIntegrityError(
            "metadata refresh request IDs did not match the cache lookup"
        )
    if not isinstance(fetched_metadata.metadata_by_unified_app_id, Mapping):
        raise WorkflowMetadataIntegrityError("metadata refresh did not return a mapping")

    expected_id_set = set(expected_fetched_ids)
    for response_key, metadata in fetched_metadata.metadata_by_unified_app_id.items():
        if not isinstance(metadata, SensorTowerNormalizedMetadata):
            raise WorkflowMetadataIntegrityError(
                "metadata refresh contained an invalid normalized row"
            )
        try:
            normalized_key = normalize_storage_opaque_id(
                response_key,
                field_name="metadata response ID",
            )
            normalized_metadata_id = normalize_storage_opaque_id(
                metadata.unified_app_id,
                field_name="metadata response ID",
            )
        except StorageValidationError as error:
            raise WorkflowMetadataIntegrityError(
                "metadata refresh contained an invalid ID"
            ) from error
        if normalized_key != normalized_metadata_id:
            raise WorkflowMetadataIntegrityError(
                "metadata refresh ID did not match its row"
            )
        if normalized_key not in expected_id_set:
            raise WorkflowMetadataIntegrityError(
                "metadata refresh returned an unrequested ID"
            )
        if normalized_key in combined:
            raise WorkflowMetadataIntegrityError(
                "metadata ID was supplied by both cache and refresh"
            )
        combined[normalized_key] = metadata

    unresolved_ids = tuple(app_id for app_id in selected_ids if app_id not in combined)
    return combined, unresolved_ids


def _empty_metadata_result() -> SensorTowerMetadataFetchResult:
    return SensorTowerMetadataFetchResult(
        metadata_by_unified_app_id={},
        requested_unified_app_ids=(),
        missing_unified_app_ids=(),
        requested_count=0,
        returned_count=0,
    )


def _build_summary(
    *,
    request: CollectMonthRequest,
    period: MonthlyPeriod,
    scope_name: str,
    candidate_count: int,
    selected_count: int,
    metadata_cache_fresh_count: int,
    metadata_stale_count: int,
    metadata_missing_count: int,
    metadata_requested_count: int,
    metadata_returned_count: int,
    metadata_unresolved_count: int,
    snapshot_rows_written: int,
    started_at: datetime,
    completed_at: datetime,
    market_parquet_path: Path | None = None,
    metadata_parquet_path: Path | None = None,
    monetization_profile_rows_written: int = 0,
    theme_monetization_rows_written: int = 0,
    app_profiles_parquet_path: Path | None = None,
    theme_metrics_parquet_path: Path | None = None,
) -> CollectMonthSummary:
    return CollectMonthSummary(
        month=period.month,
        period_start=period.period_start,
        period_end=period.period_end,
        scope_name=scope_name,
        candidate_count=candidate_count,
        selected_count=selected_count,
        metadata_cache_fresh_count=metadata_cache_fresh_count,
        metadata_stale_count=metadata_stale_count,
        metadata_missing_count=metadata_missing_count,
        metadata_requested_count=metadata_requested_count,
        metadata_returned_count=metadata_returned_count,
        metadata_unresolved_count=metadata_unresolved_count,
        snapshot_rows_written=snapshot_rows_written,
        database_path=request.database_path,
        market_parquet_path=market_parquet_path,
        metadata_parquet_path=metadata_parquet_path,
        plan_only=request.plan_only,
        started_at=started_at,
        completed_at=completed_at,
        monetization_profile_rows_written=monetization_profile_rows_written,
        theme_monetization_rows_written=theme_monetization_rows_written,
        app_profiles_parquet_path=app_profiles_parquet_path,
        theme_metrics_parquet_path=theme_metrics_parquet_path,
    )


def _export_market_snapshots(repository: CollectionRepository, path: Path) -> None:
    repository.export_market_snapshots_to_parquet(path)


def _export_app_metadata(repository: CollectionRepository, path: Path) -> None:
    repository.export_app_metadata_to_parquet(path)


def _normalize_utc_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowError("workflow timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _as_utc_datetime(value: datetime | date) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, datetime_time.min, tzinfo=UTC)


def _completion_timestamp(
    started_at: datetime,
    utc_clock: Callable[[], datetime] | None,
) -> datetime:
    """Use an injected completion clock, or the single collected timestamp."""

    if utc_clock is None:
        return started_at
    return _normalize_utc_datetime(utc_clock())
