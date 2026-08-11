"""Safe, idempotent Feishu field-schema planning and provisioning."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from math import isfinite

import httpx

from ..config import AppConfig
from .client import FeishuClient
from .errors import (
    FeishuPartialProvisioningError,
    FeishuRequestError,
    FeishuSchemaCompatibilityError,
    FeishuSchemaIntegrityError,
    FeishuSchemaVerificationError,
)
from .field_schema import (
    FeishuDesiredField,
    FeishuIncompatibleField,
    FeishuSchemaPlan,
    FeishuSchemaProvisionResult,
    compare_field_compatibility,
    desired_feishu_fields,
    validate_desired_schema,
)
from .models import FeishuBitableField

DEFAULT_FEISHU_FIELD_CREATE_DELAY_SECONDS = 0.5


def build_feishu_schema_plan(
    fields: Sequence[FeishuBitableField],
    *,
    apply_requested: bool,
    desired_fields: tuple[FeishuDesiredField, ...] | None = None,
) -> FeishuSchemaPlan:
    """Compare normalized live fields with the validated desired schema."""

    desired = desired_feishu_fields() if desired_fields is None else validate_desired_schema(
        desired_fields
    )
    primary_fields = tuple(field for field in fields if field.is_primary is True)
    if len(primary_fields) == 0:
        raise FeishuSchemaIntegrityError(
            "Feishu schema inspection found no primary field"
        )
    if len(primary_fields) > 1:
        raise FeishuSchemaIntegrityError(
            "Feishu schema inspection found multiple primary fields"
        )

    primary_field = primary_fields[0]
    fields_by_name: dict[str, FeishuBitableField] = {}
    for desired_field in desired:
        matching_fields = tuple(
            field for field in fields if field.field_name == desired_field.field_name
        )
        if len(matching_fields) > 1:
            raise FeishuSchemaIntegrityError(
                "Feishu schema inspection found duplicate desired field name "
                f"{desired_field.field_name}"
            )
        if matching_fields:
            fields_by_name[desired_field.field_name] = matching_fields[0]

    missing_field_names: list[str] = []
    incompatible_fields: list[FeishuIncompatibleField] = []
    compatible_field_count = 0
    for desired_field in desired:
        existing = fields_by_name.get(desired_field.field_name)
        if existing is None:
            missing_field_names.append(desired_field.field_name)
            continue
        incompatibility = compare_field_compatibility(existing, desired_field)
        if incompatibility is None:
            compatible_field_count += 1
        else:
            incompatible_fields.append(incompatibility)

    return FeishuSchemaPlan(
        current_field_count=len(fields),
        desired_field_count=len(desired),
        compatible_field_count=compatible_field_count,
        missing_field_names=tuple(missing_field_names),
        incompatible_fields=tuple(incompatible_fields),
        existing_primary_field_name=primary_field.field_name,
        apply_requested=apply_requested,
    )


def plan_feishu_schema(
    config: AppConfig,
    *,
    transport: httpx.BaseTransport | None = None,
) -> FeishuSchemaPlan:
    """Authenticate and calculate a live dry-run schema plan without writes."""

    client_config = config.feishu_client_config
    with FeishuClient.from_config(client_config, transport=transport) as client:
        client.get_tenant_access_token()
        fields = client.list_fields(
            app_token=client_config.bitable_app_token.get_secret_value(),
            table_id=client_config.bitable_table_id,
            view_id=client_config.bitable_view_id,
        )
    return build_feishu_schema_plan(fields, apply_requested=False)


def provision_feishu_schema(
    config: AppConfig,
    *,
    transport: httpx.BaseTransport | None = None,
    inspected_at: datetime | None = None,
    completed_at: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
    create_delay_seconds: float = DEFAULT_FEISHU_FIELD_CREATE_DELAY_SECONDS,
) -> FeishuSchemaProvisionResult:
    """Create only missing fields, then reread and verify the complete schema."""

    if not isfinite(create_delay_seconds) or create_delay_seconds < 0:
        raise ValueError("Feishu field create delay must be non-negative and finite")

    desired = desired_feishu_fields()
    inspected_timestamp = _utc_timestamp(inspected_at)
    client_config = config.feishu_client_config
    app_token = client_config.bitable_app_token.get_secret_value()
    created_field_names: list[str] = []

    with FeishuClient.from_config(client_config, transport=transport) as client:
        client.get_tenant_access_token()
        before_fields = client.list_fields(
            app_token=app_token,
            table_id=client_config.bitable_table_id,
            view_id=client_config.bitable_view_id,
        )
        before_plan = build_feishu_schema_plan(
            before_fields,
            apply_requested=True,
            desired_fields=desired,
        )
        if before_plan.incompatible_fields:
            raise FeishuSchemaCompatibilityError(
                tuple(
                    field.field_name for field in before_plan.incompatible_fields
                ),
                details=" | ".join(
                    _format_incompatible_field(field)
                    for field in before_plan.incompatible_fields
                ),
            )

        missing_names = set(before_plan.missing_field_names)
        for index, desired_field in enumerate(desired):
            if desired_field.field_name not in missing_names:
                continue
            try:
                created_field = client.create_field(
                    app_token=app_token,
                    table_id=client_config.bitable_table_id,
                    field=desired_field,
                )
            except FeishuRequestError:
                if created_field_names:
                    raise FeishuPartialProvisioningError(
                        tuple(created_field_names)
                    ) from None
                raise

            response_incompatibility = compare_field_compatibility(
                created_field,
                desired_field,
            )
            if response_incompatibility is not None:
                raise FeishuSchemaVerificationError(
                    "Feishu created field response was incompatible for "
                    f"{desired_field.field_name}"
                )
            created_field_names.append(desired_field.field_name)
            if index < len(desired) - 1 and any(
                field.field_name in missing_names
                and field.field_name not in set(created_field_names)
                for field in desired[index + 1 :]
            ):
                sleep(create_delay_seconds)

        final_fields = client.list_fields(
            app_token=app_token,
            table_id=client_config.bitable_table_id,
            view_id=client_config.bitable_view_id,
        )

    final_plan = build_feishu_schema_plan(
        final_fields,
        apply_requested=True,
        desired_fields=desired,
    )
    if final_plan.missing_field_names or final_plan.incompatible_fields:
        raise FeishuSchemaVerificationError(
            _verification_message(final_plan)
        )

    completed_timestamp = _utc_timestamp(completed_at)
    return FeishuSchemaProvisionResult(
        before_field_count=before_plan.current_field_count,
        desired_field_count=final_plan.desired_field_count,
        created_field_count=len(created_field_names),
        compatible_field_count=final_plan.compatible_field_count,
        final_field_count=final_plan.current_field_count,
        created_field_names=tuple(created_field_names),
        existing_primary_field_name=final_plan.existing_primary_field_name,
        inspected_at=inspected_timestamp,
        completed_at=completed_timestamp,
        app_token_suffix=app_token[-4:],
        table_id=client_config.bitable_table_id,
        view_id=client_config.bitable_view_id,
    )


def format_feishu_schema_plan_only() -> str:
    """Format the credential-free local desired-schema plan."""

    desired = desired_feishu_fields()
    lines = [
        "Feishu schema plan:",
        "mode=plan-only",
        "network=disabled",
        "database=disabled",
        "file_writes=disabled",
        f"desired_non_primary_field_count={len(desired)}",
    ]
    lines.extend(
        f"display_order={field.display_order} field_name={field.field_name} "
        f"logical_type={field.logical_type}"
        for field in desired
    )
    return "\n".join(lines)


def format_feishu_schema_plan(plan: FeishuSchemaPlan) -> str:
    """Format a live dry-run comparison without credentials or raw payloads."""

    planned_names = plan.missing_field_names
    lines = [
        "Feishu schema dry-run complete:",
        "mode=dry-run",
        f"current_field_count={plan.current_field_count}",
        f"desired_non_primary_field_count={plan.desired_field_count}",
        f"compatible_existing_count={plan.compatible_field_count}",
        f"missing_field_count={len(plan.missing_field_names)}",
        f"incompatible_field_count={len(plan.incompatible_fields)}",
        f"existing_primary_field_name={plan.existing_primary_field_name}",
        f"planned_field_names={_join_names(planned_names)}",
        "created_field_count=0",
    ]
    lines.extend(_format_incompatible_field(field) for field in plan.incompatible_fields)
    return "\n".join(lines)


def format_feishu_schema_provision_result(
    result: FeishuSchemaProvisionResult,
) -> str:
    """Format a sanitized apply result."""

    return "\n".join(
        (
            "Feishu schema provisioning complete:",
            "mode=apply",
            f"before_field_count={result.before_field_count}",
            f"desired_non_primary_field_count={result.desired_field_count}",
            f"created_field_count={result.created_field_count}",
            f"compatible_field_count={result.compatible_field_count}",
            f"final_field_count={result.final_field_count}",
            f"created_field_names={_join_names(result.created_field_names)}",
            f"existing_primary_field_name={result.existing_primary_field_name}",
            f"inspected_at={result.inspected_at.isoformat()}",
            f"completed_at={result.completed_at.isoformat()}",
            f"app_token_suffix={result.app_token_suffix}",
            f"table_id={result.table_id}",
            f"view_id={result.view_id or 'not-configured'}",
        )
    )


def _utc_timestamp(value: datetime | None) -> datetime:
    timestamp = datetime.now(UTC) if value is None else value
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Feishu schema timestamps must be timezone-aware")
    return timestamp.astimezone(UTC)


def _join_names(names: Iterable[str]) -> str:
    return ",".join(names) if names else "none"


def _format_incompatible_field(field: FeishuIncompatibleField) -> str:
    return " ".join(
        (
            f"incompatible_field_name={field.field_name}",
            f"expected_logical_type={field.expected_logical_type}",
            f"expected_api_type={field.expected_api_type}",
            f"actual_api_type={field.actual_api_type}",
            f"actual_ui_type={field.actual_ui_type or 'not-reported'}",
            f"actual_formatter={field.actual_formatter or 'not-reported'}",
            f"actual_date_formatter={field.actual_date_formatter or 'not-reported'}",
            f"reason={field.reason}",
        )
    )


def _verification_message(plan: FeishuSchemaPlan) -> str:
    missing = _join_names(plan.missing_field_names)
    incompatible = _join_names(
        field.field_name for field in plan.incompatible_fields
    )
    details = " | ".join(
        _format_incompatible_field(field) for field in plan.incompatible_fields
    )
    return (
        "Feishu schema verification failed; "
        f"missing={missing}; incompatible={incompatible}; details={details or 'none'}"
    )


__all__ = [
    "DEFAULT_FEISHU_FIELD_CREATE_DELAY_SECONDS",
    "build_feishu_schema_plan",
    "format_feishu_schema_plan",
    "format_feishu_schema_plan_only",
    "format_feishu_schema_provision_result",
    "plan_feishu_schema",
    "provision_feishu_schema",
]
