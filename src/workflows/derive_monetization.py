"""Offline MONETIZATION-001 derivation from stored market snapshots."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

from ..analysis.monetization_models import (
    MONETIZATION_POLICY_VERSION,
    AppMonetizationProfile,
    ThemeMonetizationObservabilityMetric,
    build_app_monetization_profiles,
)
from ..analysis.monetization_observability import (
    aggregate_theme_monetization_observability,
)
from ..storage import DuckDBRepository, MarketSnapshotRow, SnapshotPeriodKey
from .errors import MonetizationWorkflowError
from .models import (
    BackfillMonthRange,
    DeriveMonetizationRequest,
    DeriveMonetizationSummary,
    MonthlyPeriod,
)


class DeriveMonetizationRepository(Protocol):
    """Local repository boundary for the offline range workflow."""

    def open(self) -> object: ...

    def initialize_schema(self) -> None: ...

    def get_market_snapshot_periods(
        self,
        period_start: date,
        period_end: date,
    ) -> dict[SnapshotPeriodKey, list[MarketSnapshotRow]]: ...

    def replace_monetization_range(
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
        monetization_proxy: str | None = None,
        observable_revenue_state: str | None = None,
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


RepositoryFactory = Callable[[Path], DeriveMonetizationRepository]


def derive_monetization(
    request: DeriveMonetizationRequest,
    *,
    current_utc: datetime | date | None = None,
    utc_clock: Callable[[], datetime] | None = None,
    repository: DeriveMonetizationRepository | None = None,
    repository_factory: RepositoryFactory | None = None,
) -> DeriveMonetizationSummary:
    """Derive and atomically replace observable-Revenue rows for an inclusive range."""

    if repository is not None and repository_factory is not None:
        raise MonetizationWorkflowError("provide either repository or repository_factory, not both")
    started_at = _normalize_utc_datetime(_resolve_current_utc(current_utc, utc_clock))
    month_range = BackfillMonthRange.parse(
        request.start_month,
        request.end_month,
        current_utc=started_at,
    )
    if request.plan_only:
        return _build_summary(
            request=request,
            month_range=month_range,
            scope_name="",
            processed_month_count=0,
            source_snapshot_row_count=0,
            profile_row_count=0,
            theme_metric_row_count=0,
            expected_theme_identity_count=0,
            started_at=started_at,
            completed_at=_completion_timestamp(started_at, utc_clock),
        )

    active_repository = repository
    owns_repository = False
    try:
        if active_repository is None:
            active_repository = (
                repository_factory(request.database_path)
                if repository_factory is not None
                else DuckDBRepository(request.database_path)
            )
            owns_repository = True
        active_repository.open()
        active_repository.initialize_schema()

        stored_periods = active_repository.get_market_snapshot_periods(
            month_range.periods[0].period_start,
            month_range.periods[-1].period_end,
        )
        period_rows = _match_requested_periods(month_range.periods, stored_periods)
        profiles: list[AppMonetizationProfile] = []
        theme_metrics: list[ThemeMonetizationObservabilityMetric] = []
        source_theme_identities: set[tuple[str, str, date, date, str]] = set()
        scope_names: set[str] = set()
        for period in month_range.periods:
            period_key, snapshots = period_rows[period.month]
            _validate_source_rows(period, period_key, snapshots)
            scope_names.add(period_key.scope_name)
            month_profiles = build_app_monetization_profiles(
                snapshots,
                calculated_at=started_at,
            )
            month_metrics = aggregate_theme_monetization_observability(
                snapshots,
                month_profiles,
                calculated_at=started_at,
            )
            profiles.extend(month_profiles)
            theme_metrics.extend(month_metrics)
            source_theme_identities.update(
                (
                    metric.scope_name,
                    metric.cadence,
                    metric.period_start,
                    metric.period_end,
                    metric.game_theme,
                )
                for metric in month_metrics
            )

        expected_theme_identities = _validate_existing_theme_identities(
            active_repository,
            source_theme_identities,
            month_range,
            scope_names,
        )
        active_repository.replace_monetization_range(profiles, theme_metrics)
        _verify_range_readback(
            active_repository,
            profiles,
            theme_metrics,
            month_range,
            scope_names,
        )

        app_profiles_path: Path | None = None
        theme_metrics_path: Path | None = None
        if not request.skip_export:
            app_profiles_path = request.export_directory / "app_monetization_profiles.parquet"
            theme_metrics_path = (
                request.export_directory
                / "theme_monetization_observability_metrics.parquet"
            )
            active_repository.export_app_monetization_profiles_to_parquet(app_profiles_path)
            active_repository.export_theme_monetization_observability_metrics_to_parquet(
                theme_metrics_path
            )

        return _build_summary(
            request=request,
            month_range=month_range,
            scope_name=next(iter(scope_names)) if len(scope_names) == 1 else "multiple",
            processed_month_count=len(month_range.periods),
            source_snapshot_row_count=len(profiles),
            profile_row_count=len(profiles),
            theme_metric_row_count=len(theme_metrics),
            expected_theme_identity_count=expected_theme_identities,
            started_at=started_at,
            completed_at=_completion_timestamp(started_at, utc_clock),
            app_profiles_parquet_path=app_profiles_path,
            theme_metrics_parquet_path=theme_metrics_path,
        )
    finally:
        if owns_repository and active_repository is not None:
            active_repository.close()


def format_derive_monetization_summary(summary: DeriveMonetizationSummary) -> str:
    """Format a sanitized plan or completed offline derivation result."""

    if summary.plan_only:
        return "\n".join(
            (
                "Monetization derivation plan:",
                "mode=plan-only",
                f"start_month={summary.start_month}",
                f"end_month={summary.end_month}",
                f"planned_month_count={summary.planned_month_count}",
                f"policy_version={summary.policy_version}",
                "source=stored_market_snapshots_only",
                "historical_custom_fields=disabled",
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
            "Monetization derivation complete:",
            f"start_month={summary.start_month}",
            f"end_month={summary.end_month}",
            f"processed_month_count={summary.processed_month_count}",
            f"source_snapshot_row_count={summary.source_snapshot_row_count}",
            f"profile_row_count={summary.profile_row_count}",
            f"theme_metric_row_count={summary.theme_metric_row_count}",
            f"expected_theme_identity_count={summary.expected_theme_identity_count}",
            f"scope_name={summary.scope_name}",
            f"policy_version={summary.policy_version}",
            f"verification={summary.verification}",
            "network=disabled",
            "metadata_api=disabled",
            "feishu=disabled",
            export_text,
        )
    )


def _match_requested_periods(
    periods: Sequence[MonthlyPeriod],
    stored_periods: dict[SnapshotPeriodKey, list[MarketSnapshotRow]],
) -> dict[str, tuple[SnapshotPeriodKey, list[MarketSnapshotRow]]]:
    matched: dict[str, tuple[SnapshotPeriodKey, list[MarketSnapshotRow]]] = {}
    for period in periods:
        candidates = [
            (key, rows)
            for key, rows in stored_periods.items()
            if key.period_start == period.period_start
        ]
        if not candidates:
            raise MonetizationWorkflowError(
                f"missing stored monthly market period for {period.month}"
            )
        if len(candidates) != 1:
            raise MonetizationWorkflowError(
                f"multiple stored monthly market periods found for {period.month}"
            )
        key, rows = candidates[0]
        if not rows:
            raise MonetizationWorkflowError(
                f"stored monthly market period is empty for {period.month}"
            )
        matched[period.month] = (key, rows)
    return matched


def _validate_source_rows(
    period: MonthlyPeriod,
    period_key: SnapshotPeriodKey,
    rows: Sequence[MarketSnapshotRow],
) -> None:
    expected_key = SnapshotPeriodKey(
        scope_name=period_key.scope_name,
        cadence="monthly",
        period_start=period.period_start,
        period_end=period.period_end,
    )
    if period_key != expected_key:
        raise MonetizationWorkflowError(
            f"stored market period identity does not match requested month {period.month}"
        )
    if not rows:
        raise MonetizationWorkflowError(
            f"stored monthly market period is empty for {period.month}"
        )
    source_ids = [row.source_app_id for row in rows]
    unified_ids = [row.unified_app_id for row in rows]
    if len(set(source_ids)) != len(source_ids):
        raise MonetizationWorkflowError(
            f"stored source identities are duplicated for {period.month}"
        )
    if len(set(unified_ids)) != len(unified_ids):
        raise MonetizationWorkflowError(
            f"stored unified identities are duplicated for {period.month}"
        )
    if any(row.period_key != period_key for row in rows):
        raise MonetizationWorkflowError(
            f"stored market rows do not match requested month {period.month}"
        )


def _validate_existing_theme_identities(
    repository: DeriveMonetizationRepository,
    source_identities: set[tuple[str, str, date, date, str]],
    month_range: BackfillMonthRange,
    scope_names: set[str],
) -> int:
    """Compare output identities with existing AGG/MODEL populations when present."""

    if not source_identities or not hasattr(repository, "get_theme_monthly_metrics"):
        return len(source_identities)
    scope_name = next(iter(scope_names)) if len(scope_names) == 1 else None
    monthly_rows = []
    for period in month_range.periods:
        monthly_rows.extend(
            repository.get_theme_monthly_metrics(
                scope_name=scope_name,
                period_start=period.period_start,
                period_end=period.period_end,
            )
        )
    monthly_identities = {
        (row.scope_name, row.cadence, row.period_start, row.period_end, row.game_theme)
        for row in monthly_rows
    }
    if monthly_identities and monthly_identities != source_identities:
        raise MonetizationWorkflowError(
            "theme identities do not match the existing monthly aggregation population"
        )
    if hasattr(repository, "get_theme_model_summaries"):
        model_rows = []
        for period in month_range.periods:
            model_rows.extend(
                repository.get_theme_model_summaries(
                    scope_name=scope_name,
                    period_start=period.period_start,
                    period_end=period.period_end,
                )
            )
        model_identities = {
            (row.scope_name, row.cadence, row.period_start, row.period_end, row.game_theme)
            for row in model_rows
        }
        if model_identities and model_identities != source_identities:
            raise MonetizationWorkflowError(
                "theme identities do not match the existing model summary population"
            )
    return len(source_identities)


def _verify_range_readback(
    repository: DeriveMonetizationRepository,
    profiles: Sequence[AppMonetizationProfile],
    theme_metrics: Sequence[ThemeMonetizationObservabilityMetric],
    month_range: BackfillMonthRange,
    scope_names: set[str],
) -> None:
    scope_name = next(iter(scope_names)) if len(scope_names) == 1 else None
    actual_profiles: list[AppMonetizationProfile] = []
    actual_metrics: list[ThemeMonetizationObservabilityMetric] = []
    for period in month_range.periods:
        actual_profiles.extend(
            repository.get_app_monetization_profiles(
                scope_name=scope_name,
                period_start=period.period_start,
                period_end=period.period_end,
            )
        )
        actual_metrics.extend(
            repository.get_theme_monetization_observability_metrics(
                scope_name=scope_name,
                period_start=period.period_start,
                period_end=period.period_end,
            )
        )
    if sorted(actual_profiles, key=lambda row: row.period_key + (row.unified_app_id,)) != sorted(
        profiles,
        key=lambda row: row.period_key + (row.unified_app_id,),
    ):
        raise MonetizationWorkflowError("app monetization readback did not match calculation")
    if sorted(actual_metrics, key=lambda row: row.period_key + (row.game_theme,)) != sorted(
        theme_metrics,
        key=lambda row: row.period_key + (row.game_theme,),
    ):
        raise MonetizationWorkflowError(
            "theme monetization readback did not match calculation"
        )


def _build_summary(
    *,
    request: DeriveMonetizationRequest,
    month_range: BackfillMonthRange,
    scope_name: str,
    processed_month_count: int,
    source_snapshot_row_count: int,
    profile_row_count: int,
    theme_metric_row_count: int,
    expected_theme_identity_count: int,
    started_at: datetime,
    completed_at: datetime,
    app_profiles_parquet_path: Path | None = None,
    theme_metrics_parquet_path: Path | None = None,
) -> DeriveMonetizationSummary:
    return DeriveMonetizationSummary(
        start_month=month_range.start_month,
        end_month=month_range.end_month,
        planned_month_count=len(month_range.periods),
        planned_months=month_range.months,
        processed_month_count=processed_month_count,
        scope_name=scope_name,
        policy_version=MONETIZATION_POLICY_VERSION,
        source_snapshot_row_count=source_snapshot_row_count,
        profile_row_count=profile_row_count,
        theme_metric_row_count=theme_metric_row_count,
        expected_theme_identity_count=expected_theme_identity_count,
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


def _resolve_current_utc(
    current_utc: datetime | date | None,
    utc_clock: Callable[[], datetime] | None,
) -> datetime | date:
    if current_utc is not None:
        return current_utc
    if utc_clock is None:
        return datetime.now(UTC)
    return utc_clock()


def _normalize_utc_datetime(value: datetime | date) -> datetime:
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if not isinstance(value, datetime):
        raise MonetizationWorkflowError("current UTC time must be a datetime or date")
    if value.tzinfo is None or value.utcoffset() is None:
        raise MonetizationWorkflowError("current UTC time must be timezone-aware")
    return value.astimezone(UTC)


def _completion_timestamp(
    started_at: datetime,
    utc_clock: Callable[[], datetime] | None,
) -> datetime:
    if utc_clock is None:
        return started_at
    return _normalize_utc_datetime(utc_clock())
