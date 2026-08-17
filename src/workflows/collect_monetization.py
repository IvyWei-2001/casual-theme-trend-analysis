"""Latest-month MONETIZATION-001 collection orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from datetime import time as datetime_time
from pathlib import Path
from typing import Protocol, cast

from ..analysis.monetization_models import (
    MONETIZATION_POLICY_VERSION,
    AppMonetizationProfile,
    ThemeMonetizationObservabilityMetric,
    build_app_monetization_profiles,
)
from ..analysis.monetization_observability import aggregate_theme_monetization_observability
from ..config import AppConfig
from ..sensor_tower import (
    MONETIZATION_MEANINGFUL_IAP_TAG_KEYS,
    MONETIZATION_VERIFIED_CUSTOM_TAG_KEYS,
    SensorTowerClient,
    SensorTowerMarketRecord,
    select_market_records,
)
from ..storage import (
    DuckDBRepository,
    MarketSnapshotRow,
    SnapshotPeriodKey,
)
from .errors import MonetizationReadbackVerificationError, MonetizationWorkflowError
from .models import CollectMonetizationRequest, CollectMonetizationSummary, MonthlyPeriod

LOGGER = logging.getLogger(__name__)


class MonetizationClient(Protocol):
    """Minimal already-verified market client boundary."""

    def fetch_market_candidates(self, request: object) -> list[SensorTowerMarketRecord]:
        """Fetch one market response."""

    def close(self) -> None:
        """Close an owned client."""


class MonetizationRepository(Protocol):
    """Repository operations required by the dedicated workflow."""

    def open(self) -> object: ...

    def initialize_schema(self) -> None: ...

    def get_latest_market_snapshot_period_key(
        self,
        scope_name: str,
        cadence: str = "monthly",
    ) -> SnapshotPeriodKey | None: ...

    def get_market_snapshot_period(self, key: SnapshotPeriodKey) -> list[MarketSnapshotRow]: ...

    def replace_monetization_period(
        self,
        profiles: Sequence[AppMonetizationProfile],
        theme_metrics: Sequence[ThemeMonetizationObservabilityMetric],
    ) -> None: ...

    def get_app_monetization_profiles(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        unified_app_id: object | None = None,
        monetization_mix_proxy: str | None = None,
        observable_revenue_applicability: str | None = None,
    ) -> list[AppMonetizationProfile]: ...

    def get_theme_monetization_observability_metrics(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeMonetizationObservabilityMetric]: ...

    def export_app_monetization_profiles_to_parquet(self, path: str | Path) -> None: ...

    def export_theme_monetization_observability_metrics_to_parquet(
        self,
        path: str | Path,
    ) -> None: ...

    def close(self) -> None: ...


ClientFactory = Callable[[], MonetizationClient]
RepositoryFactory = Callable[[Path], MonetizationRepository]


def collect_monetization(
    request: CollectMonetizationRequest,
    config: AppConfig | None = None,
    *,
    current_utc: datetime | date | None = None,
    utc_clock: Callable[[], datetime] | None = None,
    client: MonetizationClient | None = None,
    client_factory: ClientFactory | None = None,
    repository: MonetizationRepository | None = None,
    repository_factory: RepositoryFactory | None = None,
) -> CollectMonetizationSummary:
    """Collect one latest stored month without historical monetization backfill."""

    if client is not None and client_factory is not None:
        raise MonetizationWorkflowError("provide either client or client_factory, not both")
    if repository is not None and repository_factory is not None:
        raise MonetizationWorkflowError("provide either repository or repository_factory, not both")

    started_at = _normalize_utc_datetime(_resolve_current_utc(current_utc, utc_clock))
    period = MonthlyPeriod.parse(request.month, current_utc=started_at)
    if request.plan_only:
        return _build_summary(
            request=request,
            period=period,
            scope_name="",
            stored_snapshot_count=0,
            candidate_count=0,
            selected_count=0,
            matched_source_record_count=0,
            unmatched_stored_snapshot_count=0,
            extra_selected_record_count=0,
            profiles=(),
            theme_metrics=(),
            started_at=started_at,
            completed_at=_completion_timestamp(started_at, utc_clock),
        )
    if config is None:
        raise MonetizationWorkflowError("config is required for monetization collection")

    selection_config = config.sensor_tower_selection_config
    period_key = SnapshotPeriodKey(
        scope_name=selection_config.scope_name,
        cadence=period.cadence,
        period_start=period.period_start,
        period_end=period.period_end,
    )
    active_repository: MonetizationRepository
    owns_repository = False
    active_client: MonetizationClient | None = client
    owns_client = False
    try:
        if repository is None:
            if repository_factory is None:
                active_repository = cast(
                    MonetizationRepository,
                    DuckDBRepository(request.database_path),
                )
            else:
                active_repository = repository_factory(request.database_path)
            owns_repository = True
        else:
            active_repository = repository
        active_repository.open()
        active_repository.initialize_schema()
        latest_key = active_repository.get_latest_market_snapshot_period_key(
            selection_config.scope_name,
            cadence="monthly",
        )
        if latest_key != period_key:
            raise MonetizationWorkflowError(
                "requested month must equal the latest stored market month"
            )
        stored_snapshots = active_repository.get_market_snapshot_period(period_key)
        _validate_stored_population(stored_snapshots, period_key)

        market_request = config.build_sensor_tower_market_request(
            period.period_start,
            end_date=period.period_end,
        )
        if active_client is None:
            if client_factory is not None:
                active_client = client_factory()
            else:
                active_client = cast(
                    MonetizationClient,
                    SensorTowerClient.from_config(config.sensor_tower_client_config),
                )
                owns_client = True
        if active_client is None:
            raise MonetizationWorkflowError("market client could not be created")
        candidates = active_client.fetch_market_candidates(market_request)
        _validate_fetched_source_ids(candidates)
        selected_records = select_market_records(
            candidates,
            allowed_genres=selection_config.allowed_genres,
            final_top_n=selection_config.final_top_n,
            exclude_china_revenue_market=selection_config.exclude_china_revenue_market,
        )
        selected_ids = {record.app_id for record in selected_records}
        stored_ids = {row.source_app_id for row in stored_snapshots}
        matched_count = len(stored_ids & selected_ids)
        unmatched_count = len(stored_ids - selected_ids)
        extra_count = len(selected_ids - stored_ids)
        if stored_ids != selected_ids:
            raise MonetizationWorkflowError(
                "stored/API population mismatch: "
                f"stored_count={len(stored_ids)} "
                f"selected_count={len(selected_ids)} "
                f"matched_count={matched_count} "
                f"unmatched_stored_count={unmatched_count} "
                f"extra_selected_count={extra_count}"
            )

        profiles = build_app_monetization_profiles(
            stored_snapshots,
            selected_records,
            observed_at=started_at,
        )
        theme_metrics = aggregate_theme_monetization_observability(
            stored_snapshots,
            profiles,
            calculated_at=started_at,
        )
        active_repository.replace_monetization_period(profiles, theme_metrics)
        _verify_workflow_readback(
            active_repository,
            period_key,
            profiles,
            theme_metrics,
        )

        app_profiles_path: Path | None = None
        theme_metrics_path: Path | None = None
        if not request.skip_export:
            app_profiles_path = request.export_directory / "app_monetization_profiles.parquet"
            theme_metrics_path = (
                request.export_directory / "theme_monetization_observability_metrics.parquet"
            )
            active_repository.export_app_monetization_profiles_to_parquet(app_profiles_path)
            active_repository.export_theme_monetization_observability_metrics_to_parquet(
                theme_metrics_path
            )

        return _build_summary(
            request=request,
            period=period,
            scope_name=selection_config.scope_name,
            stored_snapshot_count=len(stored_snapshots),
            candidate_count=len(candidates),
            selected_count=len(selected_records),
            matched_source_record_count=matched_count,
            unmatched_stored_snapshot_count=unmatched_count,
            extra_selected_record_count=extra_count,
            profiles=profiles,
            theme_metrics=theme_metrics,
            started_at=started_at,
            completed_at=_completion_timestamp(started_at, utc_clock),
            app_profiles_parquet_path=app_profiles_path,
            theme_metrics_parquet_path=theme_metrics_path,
        )
    finally:
        if owns_client and active_client is not None:
            active_client.close()
        if owns_repository and active_repository is not None:
            active_repository.close()


def format_collect_monetization_summary(summary: CollectMonetizationSummary) -> str:
    """Format a sanitized plan or collection result without source values."""

    if summary.plan_only:
        return "\n".join(
            (
                "Monetization observability plan:",
                "mode=plan-only",
                f"month={summary.month}",
                f"policy_version={summary.policy_version}",
                f"verified_tag_count={summary.verified_tag_count}",
                f"meaningful_iap_tag_count={summary.meaningful_iap_tag_count}",
                "new_outputs=app_monetization_profiles,theme_monetization_observability_metrics",
                "historical_backfill=disabled",
                "network=disabled",
                "database=disabled",
                "file_writes=disabled",
            )
        )
    export_text = (
        "parquet_export=written"
        if summary.app_profiles_parquet_path is not None
        and summary.theme_metrics_parquet_path is not None
        else "parquet_export=skipped"
    )
    return "\n".join(
        (
            "Monetization observability collection complete:",
            f"month={summary.month}",
            f"stored_snapshot_count={summary.stored_snapshot_count}",
            f"candidate_count={summary.candidate_count}",
            f"selected_count={summary.selected_count}",
            f"matched_source_record_count={summary.matched_source_record_count}",
            f"unmatched_stored_snapshot_count={summary.unmatched_stored_snapshot_count}",
            f"extra_selected_record_count={summary.extra_selected_record_count}",
            f"profile_row_count={summary.profile_row_count}",
            f"classified_profile_count={summary.classified_profile_count}",
            f"unknown_profile_count={summary.unknown_profile_count}",
            f"invalid_signal_profile_count={summary.invalid_signal_profile_count}",
            f"theme_metric_row_count={summary.theme_metric_row_count}",
            f"verification={summary.verification}",
            f"metadata_api={summary.metadata_api}",
            f"feishu={summary.feishu}",
            export_text,
        )
    )


def _build_summary(
    *,
    request: CollectMonetizationRequest,
    period: MonthlyPeriod,
    scope_name: str,
    stored_snapshot_count: int,
    candidate_count: int,
    selected_count: int,
    matched_source_record_count: int,
    unmatched_stored_snapshot_count: int,
    extra_selected_record_count: int,
    profiles: Sequence[AppMonetizationProfile],
    theme_metrics: Sequence[ThemeMonetizationObservabilityMetric],
    started_at: datetime,
    completed_at: datetime,
    app_profiles_parquet_path: Path | None = None,
    theme_metrics_parquet_path: Path | None = None,
) -> CollectMonetizationSummary:
    profile_rows = tuple(profiles)
    theme_rows = tuple(theme_metrics)
    return CollectMonetizationSummary(
        month=period.month,
        period_start=period.period_start,
        period_end=period.period_end,
        scope_name=scope_name,
        policy_version=MONETIZATION_POLICY_VERSION,
        verified_tag_count=len(MONETIZATION_VERIFIED_CUSTOM_TAG_KEYS),
        meaningful_iap_tag_count=len(MONETIZATION_MEANINGFUL_IAP_TAG_KEYS),
        stored_snapshot_count=stored_snapshot_count,
        candidate_count=candidate_count,
        selected_count=selected_count,
        matched_source_record_count=matched_source_record_count,
        unmatched_stored_snapshot_count=unmatched_stored_snapshot_count,
        extra_selected_record_count=extra_selected_record_count,
        profile_row_count=len(profile_rows),
        classified_profile_count=sum(
            row.monetization_mix_proxy != "unknown" for row in profile_rows
        ),
        unknown_profile_count=sum(row.monetization_mix_proxy == "unknown" for row in profile_rows),
        invalid_signal_profile_count=sum(
            row.classification_reason == "invalid_classification_signal" for row in profile_rows
        ),
        theme_metric_row_count=len(theme_rows),
        database_path=request.database_path,
        app_profiles_parquet_path=app_profiles_parquet_path,
        theme_metrics_parquet_path=theme_metrics_parquet_path,
        verification="passed" if not request.plan_only else "not_run",
        metadata_api="disabled",
        feishu="disabled",
        plan_only=request.plan_only,
        started_at=started_at,
        completed_at=completed_at,
    )


def _validate_stored_population(
    rows: Sequence[MarketSnapshotRow],
    period_key: SnapshotPeriodKey,
) -> None:
    if not rows:
        raise MonetizationWorkflowError("latest stored market month is empty")
    if any(row.period_key != period_key for row in rows):
        raise MonetizationWorkflowError("stored market rows do not match the requested month")
    source_ids = [row.source_app_id for row in rows]
    if len(set(source_ids)) != len(source_ids):
        raise MonetizationWorkflowError("stored market source identities are duplicated")
    unified_ids = [row.unified_app_id for row in rows]
    if len(set(unified_ids)) != len(unified_ids):
        raise MonetizationWorkflowError("stored market product identities are duplicated")


def _validate_fetched_source_ids(records: Sequence[SensorTowerMarketRecord]) -> None:
    source_ids = [record.app_id for record in records]
    if len(set(source_ids)) != len(source_ids):
        raise MonetizationWorkflowError("fetched source identities are duplicated")


def _verify_workflow_readback(
    repository: MonetizationRepository,
    period_key: SnapshotPeriodKey,
    profiles: Sequence[AppMonetizationProfile],
    theme_metrics: Sequence[ThemeMonetizationObservabilityMetric],
) -> None:
    actual_profiles = repository.get_app_monetization_profiles(
        scope_name=period_key.scope_name,
        cadence=period_key.cadence,
        period_start=period_key.period_start,
        period_end=period_key.period_end,
    )
    actual_metrics = repository.get_theme_monetization_observability_metrics(
        scope_name=period_key.scope_name,
        cadence=period_key.cadence,
        period_start=period_key.period_start,
        period_end=period_key.period_end,
    )
    if (
        len(actual_profiles) != len(profiles)
        or {row.unified_app_id for row in actual_profiles}
        != {row.unified_app_id for row in profiles}
        or len(actual_metrics) != len(theme_metrics)
        or {row.game_theme for row in actual_metrics}
        != {row.game_theme for row in theme_metrics}
    ):
        raise MonetizationReadbackVerificationError(
            "monetization readback identities did not match the calculated payload"
        )


def _resolve_current_utc(
    current_utc: datetime | date | None,
    utc_clock: Callable[[], datetime] | None,
) -> datetime | date:
    if current_utc is not None:
        return current_utc
    if utc_clock is None:
        raise MonetizationWorkflowError("current UTC time must be supplied by the caller")
    value = utc_clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise MonetizationWorkflowError("workflow timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _normalize_utc_datetime(value: datetime | date) -> datetime:
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime_time.min, tzinfo=UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise MonetizationWorkflowError("workflow timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _completion_timestamp(
    started_at: datetime,
    utc_clock: Callable[[], datetime] | None,
) -> datetime:
    if utc_clock is None:
        return started_at
    return _normalize_utc_datetime(utc_clock())
