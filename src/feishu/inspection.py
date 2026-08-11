"""Read-only Feishu field inspection workflow and sanitized CLI formatting."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from ..config import AppConfig
from .client import FeishuClient
from .errors import FeishuSchemaIntegrityError
from .field_schema import FeishuSchemaPlan
from .models import (
    FeishuBitableField,
    FeishuFieldInspectionResult,
    FeishuRecordInspectionResult,
)
from .provisioning import build_feishu_schema_plan


def inspect_feishu(
    config: AppConfig,
    *,
    transport: httpx.BaseTransport | None = None,
    inspected_at: datetime | None = None,
) -> FeishuFieldInspectionResult:
    """Authenticate and inspect all configured Bitable fields without writes."""

    client_config = config.feishu_client_config
    timestamp = datetime.now(UTC) if inspected_at is None else inspected_at
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("inspected_at must be timezone-aware")
    timestamp = timestamp.astimezone(UTC)

    with FeishuClient.from_config(client_config, transport=transport) as client:
        client.get_tenant_access_token()
        fields = client.list_fields(
            app_token=client_config.bitable_app_token.get_secret_value(),
            table_id=client_config.bitable_table_id,
            view_id=client_config.bitable_view_id,
        )

    normalized_fields = tuple(fields)
    return FeishuFieldInspectionResult.from_fields(
        normalized_fields,
        inspected_at=timestamp,
        app_token=client_config.bitable_app_token.get_secret_value(),
        table_id=client_config.bitable_table_id,
        view_id=client_config.bitable_view_id,
    )


def inspect_feishu_records(
    config: AppConfig,
    *,
    transport: httpx.BaseTransport | None = None,
    inspected_at: datetime | None = None,
) -> FeishuRecordInspectionResult:
    """Validate the FEISHU-002 schema, then inspect all table records read-only."""

    client_config = config.feishu_client_config
    timestamp = _utc_timestamp(inspected_at)
    app_token = client_config.bitable_app_token.get_secret_value()

    with FeishuClient.from_config(client_config, transport=transport) as client:
        client.get_tenant_access_token()
        fields = client.list_fields(
            app_token=app_token,
            table_id=client_config.bitable_table_id,
            view_id=client_config.bitable_view_id,
        )
        schema_plan = build_feishu_schema_plan(fields, apply_requested=False)
        _require_complete_record_schema(schema_plan)
        records = client.list_records(
            app_token=app_token,
            table_id=client_config.bitable_table_id,
            primary_field_name=schema_plan.existing_primary_field_name,
        )

    records_with_primary_value = records.records_with_primary_value
    return FeishuRecordInspectionResult(
        schema_field_count=schema_plan.current_field_count,
        desired_non_primary_field_count=schema_plan.desired_field_count,
        compatible_existing_count=schema_plan.compatible_field_count,
        missing_field_count=len(schema_plan.missing_field_names),
        incompatible_field_count=len(schema_plan.incompatible_fields),
        existing_primary_field_name=schema_plan.existing_primary_field_name,
        record_page_count=records.page_count,
        record_count=records.record_count,
        records_with_primary_value=records_with_primary_value,
        records_without_primary_value=records.record_count - records_with_primary_value,
        observed_field_name_count=len(records.observed_field_names),
        duplicate_record_id_count=0,
        inspected_at=timestamp,
        app_token_suffix=app_token[-4:],
        table_id=client_config.bitable_table_id,
    )


def format_feishu_inspection_plan(config: AppConfig) -> str:
    """Format a credential-safe no-network inspection plan."""

    return "\n".join(
        (
            "Feishu inspection plan:",
            "mode=plan-only",
            "network=disabled",
            "database=disabled",
            "file_writes=disabled",
            "authentication=tenant_access_token",
            "bitable_operation=GET fields only",
            f"app_id_configured={'yes' if config.feishu_app_id else 'no'}",
            f"app_token_configured={'yes' if config.feishu_bitable_app_token else 'no'}",
            f"table_id={config.feishu_bitable_table_id or 'not-configured'}",
            f"view_id={config.feishu_bitable_view_id or 'not-configured'}",
        )
    )


def format_feishu_record_inspection_plan() -> str:
    """Format a credential-free plan for schema-gated record inspection."""

    return "\n".join(
        (
            "Feishu record inspection plan:",
            "mode=plan-only",
            "network=disabled",
            "database=disabled",
            "file_writes=disabled",
            "authentication=disabled",
            "bitable_operation=GET fields then GET records",
            "records_view_id=omitted",
            "record_page_size=100",
            "desired_non_primary_field_count=21",
        )
    )


def format_feishu_inspection_summary(result: FeishuFieldInspectionResult) -> str:
    """Format one sanitized field audit for the command line."""

    lines = [
        "Feishu inspection complete:",
        f"field_count={result.field_count}",
        f"primary_field_count={result.primary_field_count}",
        f"duplicate_field_name_count={len(result.duplicate_field_names)}",
        f"table_id={result.table_id}",
        f"view_id={result.view_id or 'not-configured'}",
        "",
    ]
    for field in result.fields:
        ui_type = field.ui_type if field.ui_type is not None else "not-reported"
        primary = (
            str(field.is_primary).lower()
            if field.is_primary is not None
            else "not-reported"
        )
        options = ",".join(field.option_names) if field.option_names else "none"
        lines.append(
            " ".join(
                (
                    f"field_id={field.field_id}",
                    f"field_name={_single_line(field.field_name)}",
                    f"type={field.type}",
                    f"ui_type={_single_line(ui_type)}",
                    f"primary={primary}",
                    f"options={field.option_count}",
                    f"option_names={_single_line(options)}",
                )
            )
        )
    return "\n".join(lines)


def format_feishu_record_inspection_summary(
    result: FeishuRecordInspectionResult,
) -> str:
    """Format a record audit using counts only, never IDs or cell values."""

    return "\n".join(
        (
            "Feishu record inspection complete:",
            "mode=read-only",
            f"schema_field_count={result.schema_field_count}",
            f"desired_non_primary_field_count={result.desired_non_primary_field_count}",
            f"compatible_existing_count={result.compatible_existing_count}",
            f"missing_field_count={result.missing_field_count}",
            f"incompatible_field_count={result.incompatible_field_count}",
            f"existing_primary_field_name={_single_line(result.existing_primary_field_name)}",
            f"record_page_count={result.record_page_count}",
            f"record_count={result.record_count}",
            f"records_with_primary_value={result.records_with_primary_value}",
            f"records_without_primary_value={result.records_without_primary_value}",
            f"observed_field_name_count={result.observed_field_name_count}",
            f"duplicate_record_id_count={result.duplicate_record_id_count}",
            f"app_token_suffix={result.app_token_suffix}",
            f"table_id={result.table_id}",
        )
    )


def _utc_timestamp(value: datetime | None) -> datetime:
    timestamp = datetime.now(UTC) if value is None else value
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Feishu record inspection timestamp must be timezone-aware")
    return timestamp.astimezone(UTC)


def _require_complete_record_schema(schema_plan: FeishuSchemaPlan) -> None:
    """Stop before records GET unless the complete FEISHU-002 schema matches."""

    if (
        schema_plan.desired_field_count != 21
        or schema_plan.compatible_field_count != 21
        or schema_plan.missing_field_names
        or schema_plan.incompatible_fields
    ):
        raise FeishuSchemaIntegrityError(
            "Feishu record inspection stopped before records GET because the "
            "FEISHU-002 schema is incomplete or incompatible"
        )


def _single_line(value: str) -> str:
    """Keep external display text from changing the audit line structure."""

    return " ".join(value.split())


__all__ = [
    "FeishuBitableField",
    "FeishuFieldInspectionResult",
    "FeishuRecordInspectionResult",
    "format_feishu_inspection_plan",
    "format_feishu_inspection_summary",
    "format_feishu_record_inspection_plan",
    "format_feishu_record_inspection_summary",
    "inspect_feishu",
    "inspect_feishu_records",
]
