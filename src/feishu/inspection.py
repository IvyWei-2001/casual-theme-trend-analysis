"""Read-only Feishu field inspection workflow and sanitized CLI formatting."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from ..config import AppConfig
from .client import FeishuClient
from .models import FeishuBitableField, FeishuFieldInspectionResult


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


def _single_line(value: str) -> str:
    """Keep external display text from changing the audit line structure."""

    return " ".join(value.split())


__all__ = [
    "FeishuBitableField",
    "FeishuFieldInspectionResult",
    "format_feishu_inspection_plan",
    "format_feishu_inspection_summary",
    "inspect_feishu",
]
