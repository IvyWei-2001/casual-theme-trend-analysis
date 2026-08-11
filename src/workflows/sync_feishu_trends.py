"""Complete-set, idempotent DuckDB-to-Feishu trend synchronization."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from math import isfinite
from pathlib import Path
from typing import Protocol

import httpx

from ..analysis.trend_models import ThemeTrendScore
from ..config import AppConfig
from ..feishu.client import FeishuClient
from ..feishu.errors import (
    FeishuError,
    FeishuPartialSynchronizationError,
    FeishuReconciliationVerificationError,
    FeishuSchemaIntegrityError,
)
from ..feishu.field_schema import FeishuSchemaPlan
from ..feishu.provisioning import build_feishu_schema_plan
from ..feishu.synchronization import (
    DEFAULT_FEISHU_RECORD_WRITE_BATCH_SIZE,
    PRIMARY_FIELD_NAME,
    FeishuTrendReconciliationPlan,
    build_batch_create_payload,
    build_reconciliation_plan,
    require_no_duplicate_managed_keys,
    require_no_stale_managed_records,
    sync_field_mappings,
    validate_authoritative_scores,
    validate_record_write_batch_size,
)
from ..storage import DuckDBRepository
from .errors import WorkflowError
from .models import SyncFeishuTrendsRequest

DEFAULT_FEISHU_RECORD_WRITE_DELAY_SECONDS = 0.5


class SyncTrendRepository(Protocol):
    """Minimal DuckDB repository boundary needed by the synchronization workflow."""

    def open(self) -> object:
        """Open the local database."""

    def initialize_schema(self) -> None:
        """Verify or initialize the supported schema."""

    def get_theme_trend_scores(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeTrendScore]:
        """Read the complete stored trend-score source set."""

    def close(self) -> None:
        """Close the local database."""


RepositoryFactory = Callable[[Path], SyncTrendRepository]


@dataclass(frozen=True, slots=True, repr=False)
class FeishuTrendSyncSummary:
    """Sanitized result for a dry-run or completed apply."""

    mode: str
    source_score_count: int
    source_month_count: int
    source_first_month: date
    source_latest_month: date
    schema_field_count: int
    desired_non_primary_field_count: int
    compatible_existing_count: int
    current_record_count: int
    managed_record_count: int
    unmanaged_blank_record_count: int
    unmanaged_nonblank_record_count: int
    duplicate_managed_key_count: int
    stale_managed_record_count: int
    create_count: int
    update_count: int
    unchanged_count: int
    planned_create_count: int
    planned_update_count: int
    created_count: int
    updated_count: int
    final_managed_record_count: int
    final_create_count: int
    final_update_count: int
    final_duplicate_managed_key_count: int
    final_stale_managed_record_count: int
    app_token_suffix: str
    table_id: str
    plan: FeishuTrendReconciliationPlan
    final_plan: FeishuTrendReconciliationPlan | None

    def __repr__(self) -> str:
        """Represent only counts and approved destination metadata."""

        return (
            "FeishuTrendSyncSummary("
            f"mode={self.mode!r}, source_score_count={self.source_score_count!r}, "
            f"create_count={self.create_count!r}, update_count={self.update_count!r}, "
            f"unchanged_count={self.unchanged_count!r}, "
            f"final_managed_record_count={self.final_managed_record_count!r})"
        )


def sync_feishu_trends(
    request: SyncFeishuTrendsRequest,
    config: AppConfig,
    *,
    transport: httpx.BaseTransport | None = None,
    repository: SyncTrendRepository | None = None,
    repository_factory: RepositoryFactory | None = None,
    repository_initialized: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    write_batch_size: int = DEFAULT_FEISHU_RECORD_WRITE_BATCH_SIZE,
    write_delay_seconds: float = DEFAULT_FEISHU_RECORD_WRITE_DELAY_SECONDS,
) -> FeishuTrendSyncSummary:
    """Plan or explicitly apply the complete authoritative monthly score set."""

    if request.plan_only:
        raise WorkflowError(
            "sync-feishu-trends plan-only must be handled before configuration loading"
        )
    if repository is not None and repository_factory is not None:
        raise WorkflowError("provide either repository or repository_factory, not both")
    if not isinstance(repository_initialized, bool):
        raise WorkflowError("repository_initialized must be a boolean")
    validate_record_write_batch_size(write_batch_size)
    if not isfinite(write_delay_seconds) or write_delay_seconds < 0:
        raise WorkflowError("Feishu record write delay must be finite and non-negative")

    source_scores = _read_source_scores(
        request,
        config,
        repository=repository,
        repository_factory=repository_factory,
        repository_initialized=repository_initialized,
    )
    client_config = config.feishu_client_config
    app_token = client_config.bitable_app_token.get_secret_value()

    with FeishuClient.from_config(client_config, transport=transport) as client:
        client.get_tenant_access_token()
        fields = client.list_fields(
            app_token=app_token,
            table_id=client_config.bitable_table_id,
            view_id=client_config.bitable_view_id,
        )
        schema_plan = build_feishu_schema_plan(fields, apply_requested=request.apply)
        _require_complete_sync_schema(fields, schema_plan)
        records = client.list_sync_records(
            app_token=app_token,
            table_id=client_config.bitable_table_id,
            primary_field_name=PRIMARY_FIELD_NAME,
        )
        plan = build_reconciliation_plan(
            source_scores,
            records.records,
            scope_name=config.sensor_tower_scope_name,
        )
        require_no_duplicate_managed_keys(plan)

        if not request.apply:
            return _build_summary(
                mode="dry-run",
                plan=plan,
                final_plan=None,
                schema_plan=schema_plan,
                app_token=app_token,
                table_id=client_config.bitable_table_id,
                planned_create_count=0,
                planned_update_count=0,
                created_count=0,
                updated_count=0,
            )

        require_no_stale_managed_records(plan)
        if plan.create_count == 0 and plan.update_count == 0:
            return _build_summary(
                mode="apply",
                plan=plan,
                final_plan=plan,
                schema_plan=schema_plan,
                app_token=app_token,
                table_id=client_config.bitable_table_id,
                planned_create_count=plan.create_count,
                planned_update_count=plan.update_count,
                created_count=0,
                updated_count=0,
            )

        created_count, updated_count = _execute_write_batches(
            client,
            plan,
            app_token=app_token,
            table_id=client_config.bitable_table_id,
            batch_size=write_batch_size,
            sleep=sleep,
            delay_seconds=write_delay_seconds,
        )

        final_records = client.list_sync_records(
            app_token=app_token,
            table_id=client_config.bitable_table_id,
            primary_field_name=PRIMARY_FIELD_NAME,
        )
        final_plan = build_reconciliation_plan(
            source_scores,
            final_records.records,
            scope_name=config.sensor_tower_scope_name,
        )
        _require_final_verification(final_plan, plan.source_score_count)
        return _build_summary(
            mode="apply",
            plan=plan,
            final_plan=final_plan,
            schema_plan=schema_plan,
            app_token=app_token,
            table_id=client_config.bitable_table_id,
            planned_create_count=plan.create_count,
            planned_update_count=plan.update_count,
            created_count=created_count,
            updated_count=updated_count,
        )


def format_feishu_trend_sync_plan_only() -> str:
    """Format the credential-free local synchronization contract."""

    sync_field_mappings()
    return "\n".join(
        (
            "Feishu trend sync contract:",
            "mode=plan-only",
            "configuration=disabled",
            "credentials=disabled",
            "network=disabled",
            "database=disabled",
            "file_writes=disabled",
            "source=ThemeTrendScore",
            "scope=configured",
            "cadence=monthly",
            "write_mode=explicit-apply-only",
            "record_deletes=disabled",
            "unmanaged_records=preserved",
        )
    )


def format_feishu_trend_sync_summary(
    summary: FeishuTrendSyncSummary,
) -> str:
    """Format a count-only synchronization result."""

    if summary.mode == "dry-run":
        return "\n".join(
            (
                "Feishu trend sync plan:",
                "mode=dry-run",
                f"source_score_count={summary.source_score_count}",
                f"source_month_count={summary.source_month_count}",
                f"source_first_month={_month(summary.source_first_month)}",
                f"source_latest_month={_month(summary.source_latest_month)}",
                f"schema_field_count={summary.schema_field_count}",
                f"desired_non_primary_field_count={summary.desired_non_primary_field_count}",
                f"compatible_existing_count={summary.compatible_existing_count}",
                f"current_record_count={summary.current_record_count}",
                f"managed_record_count={summary.managed_record_count}",
                f"unmanaged_blank_record_count={summary.unmanaged_blank_record_count}",
                f"unmanaged_nonblank_record_count={summary.unmanaged_nonblank_record_count}",
                f"duplicate_managed_key_count={summary.duplicate_managed_key_count}",
                f"stale_managed_record_count={summary.stale_managed_record_count}",
                f"create_count={summary.create_count}",
                f"update_count={summary.update_count}",
                f"unchanged_count={summary.unchanged_count}",
                "write_request_count=0",
            )
        )

    final_plan = summary.final_plan
    if final_plan is None:
        raise WorkflowError("apply summary is missing final verification")
    return "\n".join(
        (
            "Feishu trend synchronization complete:",
            "mode=apply",
            f"source_score_count={summary.source_score_count}",
            f"source_month_count={summary.source_month_count}",
            f"source_first_month={_month(summary.source_first_month)}",
            f"source_latest_month={_month(summary.source_latest_month)}",
            f"planned_create_count={summary.planned_create_count}",
            f"planned_update_count={summary.planned_update_count}",
            f"created_count={summary.created_count}",
            f"updated_count={summary.updated_count}",
            f"unchanged_count={summary.unchanged_count}",
            f"unmanaged_blank_record_count={summary.unmanaged_blank_record_count}",
            f"unmanaged_nonblank_record_count={summary.unmanaged_nonblank_record_count}",
            f"final_managed_record_count={summary.final_managed_record_count}",
            f"final_create_count={summary.final_create_count}",
            f"final_update_count={summary.final_update_count}",
            f"duplicate_managed_key_count={summary.final_duplicate_managed_key_count}",
            f"stale_managed_record_count={summary.final_stale_managed_record_count}",
            f"app_token_suffix={summary.app_token_suffix}",
            f"table_id={summary.table_id}",
        )
    )


def _read_source_scores(
    request: SyncFeishuTrendsRequest,
    config: AppConfig,
    *,
    repository: SyncTrendRepository | None,
    repository_factory: RepositoryFactory | None,
    repository_initialized: bool,
) -> tuple[ThemeTrendScore, ...]:
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
        raw_scores = active_repository.get_theme_trend_scores(
            scope_name=config.sensor_tower_scope_name,
            cadence="monthly",
        )
        return validate_authoritative_scores(
            raw_scores,
            scope_name=config.sensor_tower_scope_name,
        )
    finally:
        if owns_repository and active_repository is not None:
            try:
                active_repository.close()
            except Exception:
                pass


def _require_complete_sync_schema(
    fields: Sequence[object],
    schema_plan: FeishuSchemaPlan,
) -> None:
    if (
        schema_plan.desired_field_count != 21
        or schema_plan.compatible_field_count != 21
        or schema_plan.missing_field_names
        or schema_plan.incompatible_fields
    ):
        raise FeishuSchemaIntegrityError(
            "Feishu trend synchronization stopped because the FEISHU-002 schema "
            "is incomplete or incompatible"
        )
    primary_fields = tuple(
        field
        for field in fields
        if getattr(field, "is_primary", None) is True
    )
    if len(primary_fields) != 1:
        raise FeishuSchemaIntegrityError(
            "Feishu trend synchronization requires exactly one primary field"
        )
    primary = primary_fields[0]
    if (
        getattr(primary, "field_name", None) != PRIMARY_FIELD_NAME
        or getattr(primary, "type", None) != 1
        or getattr(primary, "ui_type", None) not in {None, "Text"}
    ):
        raise FeishuSchemaIntegrityError(
            "Feishu trend synchronization requires the configured primary Text field"
        )


def _execute_write_batches(
    client: FeishuClient,
    plan: FeishuTrendReconciliationPlan,
    *,
    app_token: str,
    table_id: str,
    batch_size: int,
    sleep: Callable[[float], None],
    delay_seconds: float,
) -> tuple[int, int]:
    update_payloads = tuple(update.payload() for update in plan.updates)
    create_payloads = tuple(
        build_batch_create_payload(record) for record in plan.create_records
    )
    batches: list[tuple[str, tuple[dict[str, object], ...]]] = []
    batches.extend(
        ("update", chunk)
        for chunk in _chunks(update_payloads, batch_size)
    )
    batches.extend(
        ("create", chunk)
        for chunk in _chunks(create_payloads, batch_size)
    )

    successful_request_count = 0
    created_count = 0
    updated_count = 0
    failure: FeishuError | None = None
    for index, (operation, batch) in enumerate(batches):
        try:
            if operation == "update":
                result = client.batch_update_records(
                    app_token=app_token,
                    table_id=table_id,
                    records=batch,
                )
                updated_count += result.record_count
            else:
                result = client.batch_create_records(
                    app_token=app_token,
                    table_id=table_id,
                    records=batch,
                )
                created_count += result.record_count
        except FeishuError as error:
            failure = error
            break
        successful_request_count += 1
        if index < len(batches) - 1:
            sleep(delay_seconds)

    if failure is not None:
        if successful_request_count:
            raise _partial_sync_error(successful_request_count)
        raise failure
    return created_count, updated_count


def _require_final_verification(
    plan: FeishuTrendReconciliationPlan,
    source_score_count: int,
) -> None:
    if (
        plan.duplicate_managed_key_count != 0
        or plan.stale_managed_record_count != 0
        or plan.create_count != 0
        or plan.update_count != 0
        or plan.managed_record_count != source_score_count
    ):
        raise FeishuReconciliationVerificationError(
            "Feishu trend synchronization final verification did not converge"
        )


def _partial_sync_error(successful_request_count: int) -> FeishuError:
    return FeishuPartialSynchronizationError(successful_request_count)


def _build_summary(
    *,
    mode: str,
    plan: FeishuTrendReconciliationPlan,
    final_plan: FeishuTrendReconciliationPlan | None,
    schema_plan: FeishuSchemaPlan,
    app_token: str,
    table_id: str,
    planned_create_count: int,
    planned_update_count: int,
    created_count: int,
    updated_count: int,
) -> FeishuTrendSyncSummary:
    effective_final = plan if final_plan is None else final_plan
    return FeishuTrendSyncSummary(
        mode=mode,
        source_score_count=plan.source_score_count,
        source_month_count=plan.source_month_count,
        source_first_month=plan.source_first_month,
        source_latest_month=plan.source_latest_month,
        schema_field_count=schema_plan.current_field_count,
        desired_non_primary_field_count=schema_plan.desired_field_count,
        compatible_existing_count=schema_plan.compatible_field_count,
        current_record_count=plan.current_record_count,
        managed_record_count=plan.managed_record_count,
        unmanaged_blank_record_count=plan.unmanaged_blank_record_count,
        unmanaged_nonblank_record_count=plan.unmanaged_nonblank_record_count,
        duplicate_managed_key_count=plan.duplicate_managed_key_count,
        stale_managed_record_count=plan.stale_managed_record_count,
        create_count=plan.create_count,
        update_count=plan.update_count,
        unchanged_count=plan.unchanged_count,
        planned_create_count=planned_create_count,
        planned_update_count=planned_update_count,
        created_count=created_count,
        updated_count=updated_count,
        final_managed_record_count=effective_final.managed_record_count,
        final_create_count=effective_final.create_count,
        final_update_count=effective_final.update_count,
        final_duplicate_managed_key_count=effective_final.duplicate_managed_key_count,
        final_stale_managed_record_count=effective_final.stale_managed_record_count,
        app_token_suffix=app_token[-4:],
        table_id=table_id,
        plan=plan,
        final_plan=final_plan,
    )


def _chunks(
    values: Sequence[dict[str, object]],
    batch_size: int,
) -> tuple[tuple[dict[str, object], ...], ...]:
    validate_record_write_batch_size(batch_size)
    return tuple(
        tuple(values[index : index + batch_size])
        for index in range(0, len(values), batch_size)
    )


def _month(value: date) -> str:
    return value.strftime("%Y-%m")


__all__ = [
    "DEFAULT_FEISHU_RECORD_WRITE_DELAY_SECONDS",
    "FeishuTrendSyncSummary",
    "SyncTrendRepository",
    "format_feishu_trend_sync_plan_only",
    "format_feishu_trend_sync_summary",
    "sync_feishu_trends",
]
