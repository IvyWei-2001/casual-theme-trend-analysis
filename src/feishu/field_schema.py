"""Verified, deterministic Feishu trend-score field schema models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Final, Literal

from .errors import FeishuSchemaValidationError
from .models import FeishuBitableField

FeishuLogicalType = Literal["date", "text", "checkbox", "number", "date-time"]
FieldPropertyValue = str | bool
FieldProperty = Mapping[str, FieldPropertyValue]

FEISHU_NUMBER_FORMATTERS: Final[frozenset[str]] = frozenset(
    {
        "0",
        "0.0",
        "0.00",
        "0.000",
        "0.0000",
        "1,000",
        "1,000.00",
        "%",
        "0.00%",
        "¥",
        "¥0.00",
        "$",
        "$0.00",
    }
)
FEISHU_DATE_FORMATTERS: Final[frozenset[str]] = frozenset(
    {
        "yyyy/MM/dd",
        "yyyy-MM-dd HH:mm",
        "MM-dd",
        "MM/dd/yyyy",
        "dd/MM/yyyy",
    }
)
FEISHU_MONTH_DATE_FORMATTER: Final[str] = "yyyy/MM/dd"
FEISHU_DATE_TIME_FORMATTER: Final[str] = "yyyy-MM-dd HH:mm"


def _property(**values: FieldPropertyValue) -> FieldProperty:
    """Create an immutable desired-field property mapping."""

    return MappingProxyType(values)


@dataclass(frozen=True, slots=True)
class FeishuDesiredField:
    """One desired non-primary field and its verified API payload metadata."""

    field_name: str
    logical_type: FeishuLogicalType
    verified_api_type: int
    ui_type: str | None
    property: FieldProperty | None
    display_order: int

    def api_payload(self) -> dict[str, object]:
        """Build the create-field body in stable insertion order."""

        payload: dict[str, object] = {
            "field_name": self.field_name,
            "type": self.verified_api_type,
        }
        if self.ui_type is not None:
            payload["ui_type"] = self.ui_type
        if self.property is not None:
            payload["property"] = dict(self.property)
        return payload


@dataclass(frozen=True, slots=True)
class FeishuIncompatibleField:
    """Safe metadata describing one desired-name compatibility collision."""

    field_name: str
    expected_logical_type: FeishuLogicalType
    expected_api_type: int
    actual_api_type: int
    actual_ui_type: str | None
    actual_formatter: str | None
    actual_date_formatter: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class FeishuSchemaPlan:
    """Sanitized comparison of one live table schema with the desired schema."""

    current_field_count: int
    desired_field_count: int
    compatible_field_count: int
    missing_field_names: tuple[str, ...]
    incompatible_fields: tuple[FeishuIncompatibleField, ...]
    existing_primary_field_name: str
    apply_requested: bool


@dataclass(frozen=True, slots=True)
class FeishuSchemaProvisionResult:
    """Sanitized result of one complete field-schema provisioning attempt."""

    before_field_count: int
    desired_field_count: int
    created_field_count: int
    compatible_field_count: int
    final_field_count: int
    created_field_names: tuple[str, ...]
    existing_primary_field_name: str
    inspected_at: datetime
    completed_at: datetime
    app_token_suffix: str
    table_id: str
    view_id: str | None


DESIRED_FEISHU_FIELDS: Final[tuple[FeishuDesiredField, ...]] = (
    FeishuDesiredField(
        field_name="月份",
        logical_type="date",
        verified_api_type=5,
        ui_type=None,
        property=_property(date_formatter=FEISHU_MONTH_DATE_FORMATTER, auto_fill=False),
        display_order=1,
    ),
    FeishuDesiredField(
        field_name="题材",
        logical_type="text",
        verified_api_type=1,
        ui_type=None,
        property=None,
        display_order=2,
    ),
    FeishuDesiredField(
        field_name="是否最新月份",
        logical_type="checkbox",
        verified_api_type=7,
        ui_type=None,
        property=None,
        display_order=3,
    ),
    FeishuDesiredField(
        field_name="是否可行动",
        logical_type="checkbox",
        verified_api_type=7,
        ui_type=None,
        property=None,
        display_order=4,
    ),
    FeishuDesiredField(
        field_name="排除原因",
        logical_type="text",
        verified_api_type=1,
        ui_type=None,
        property=None,
        display_order=5,
    ),
    FeishuDesiredField(
        field_name="趋势排名",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0"),
        display_order=6,
    ),
    FeishuDesiredField(
        field_name="趋势分",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0.00"),
        display_order=7,
    ),
    FeishuDesiredField(
        field_name="置信度",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0.00"),
        display_order=8,
    ),
    FeishuDesiredField(
        field_name="增长分",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0.00"),
        display_order=9,
    ),
    FeishuDesiredField(
        field_name="加速度分",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0.00"),
        display_order=10,
    ),
    FeishuDesiredField(
        field_name="新产品分",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0.00"),
        display_order=11,
    ),
    FeishuDesiredField(
        field_name="集中度惩罚",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0.00"),
        display_order=12,
    ),
    FeishuDesiredField(
        field_name="最新产品数",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0"),
        display_order=13,
    ),
    FeishuDesiredField(
        field_name="最新产品份额",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0.00%"),
        display_order=14,
    ),
    FeishuDesiredField(
        field_name="units_absolute份额",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0.00%"),
        display_order=15,
    ),
    FeishuDesiredField(
        field_name="revenue_absolute份额",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0.00%"),
        display_order=16,
    ),
    FeishuDesiredField(
        field_name="近3月新进入占比",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0.00%"),
        display_order=17,
    ),
    FeishuDesiredField(
        field_name="排名改善",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0.00"),
        display_order=18,
    ),
    FeishuDesiredField(
        field_name="units_absolute超配倍数",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0.00"),
        display_order=19,
    ),
    FeishuDesiredField(
        field_name="revenue_absolute超配倍数",
        logical_type="number",
        verified_api_type=2,
        ui_type=None,
        property=_property(formatter="0.00"),
        display_order=20,
    ),
    FeishuDesiredField(
        field_name="计算时间",
        logical_type="date-time",
        verified_api_type=5,
        ui_type=None,
        property=_property(date_formatter=FEISHU_DATE_TIME_FORMATTER, auto_fill=False),
        display_order=21,
    ),
)


def desired_feishu_fields() -> tuple[FeishuDesiredField, ...]:
    """Return the validated desired schema in its deterministic order."""

    return validate_desired_schema(DESIRED_FEISHU_FIELDS)


def validate_desired_schema(
    fields: tuple[FeishuDesiredField, ...],
) -> tuple[FeishuDesiredField, ...]:
    """Validate the local schema without reading configuration or the network."""

    if not fields:
        raise FeishuSchemaValidationError("Feishu desired schema must not be empty")

    names: set[str] = set()
    for expected_order, field in enumerate(fields, start=1):
        if not field.field_name.strip():
            raise FeishuSchemaValidationError("Feishu desired field names must be non-empty")
        if field.field_name in names:
            raise FeishuSchemaValidationError(
                f"Feishu desired schema contains duplicate field name {field.field_name}"
            )
        names.add(field.field_name)
        if field.display_order != expected_order:
            raise FeishuSchemaValidationError(
                f"Feishu desired field order is invalid for {field.field_name}"
            )

        expected_api_types: dict[str, int] = {
            "date": 5,
            "text": 1,
            "checkbox": 7,
            "number": 2,
            "date-time": 5,
        }
        if field.logical_type not in expected_api_types:
            raise FeishuSchemaValidationError(
                f"Feishu desired logical type is invalid for {field.field_name}"
            )
        expected_api_type = expected_api_types[field.logical_type]
        if (
            isinstance(field.verified_api_type, bool)
            or not isinstance(field.verified_api_type, int)
            or field.verified_api_type != expected_api_type
        ):
            raise FeishuSchemaValidationError(
                f"Feishu desired field type is invalid for {field.field_name}"
            )
        if field.ui_type is not None:
            raise FeishuSchemaValidationError(
                f"Feishu desired field ui_type must be omitted for {field.field_name}"
            )
        if field.property is not None:
            if not isinstance(field.property, Mapping) or any(
                not isinstance(key, str)
                or not isinstance(value, (str, bool))
                for key, value in field.property.items()
            ):
                raise FeishuSchemaValidationError(
                    f"Feishu desired property is invalid for {field.field_name}"
                )

        if field.logical_type == "number":
            formatter = _property_value(field.property, "formatter")
            if formatter not in FEISHU_NUMBER_FORMATTERS:
                raise FeishuSchemaValidationError(
                    f"Feishu number formatter is invalid for {field.field_name}"
                )
            if field.property is None or set(field.property) != {"formatter"}:
                raise FeishuSchemaValidationError(
                    f"Feishu number property is invalid for {field.field_name}"
                )
        elif field.logical_type in {"date", "date-time"}:
            date_formatter = _property_value(field.property, "date_formatter")
            if date_formatter not in FEISHU_DATE_FORMATTERS:
                raise FeishuSchemaValidationError(
                    f"Feishu date formatter is invalid for {field.field_name}"
                )
            if _property_value(field.property, "auto_fill") is not False:
                raise FeishuSchemaValidationError(
                    f"Feishu date auto_fill must be false for {field.field_name}"
                )
            if field.property is None or set(field.property) != {
                "date_formatter",
                "auto_fill",
            }:
                raise FeishuSchemaValidationError(
                    f"Feishu date property is invalid for {field.field_name}"
                )
        elif field.property is not None:
            raise FeishuSchemaValidationError(
                f"Feishu property must be omitted for {field.field_name}"
            )

    return fields


def compare_field_compatibility(
    existing: FeishuBitableField,
    desired: FeishuDesiredField,
) -> FeishuIncompatibleField | None:
    """Compare one normalized live field with one desired field."""

    if existing.is_primary is True:
        return _incompatible(existing, desired, "desired field must not be primary")
    if existing.type != desired.verified_api_type:
        return _incompatible(existing, desired, "API field type does not match")

    expected_ui_types = {
        "text": {None, "Text"},
        "checkbox": {None, "Checkbox"},
        "number": {None, "Number"},
        "date": {None, "DateTime"},
        "date-time": {None, "DateTime"},
    }[desired.logical_type]
    if existing.ui_type not in expected_ui_types:
        return _incompatible(existing, desired, "UI field type does not match")

    if desired.logical_type == "number":
        expected_formatter = _property_value(desired.property, "formatter")
        if existing.formatter != expected_formatter:
            return _incompatible(existing, desired, "numeric formatter does not match")
    elif desired.logical_type in {"date", "date-time"}:
        expected_formatter = _property_value(desired.property, "date_formatter")
        actual_date_formatter = existing.date_formatter
        if actual_date_formatter is None and desired.logical_type == "date":
            actual_date_formatter = FEISHU_MONTH_DATE_FORMATTER
        if actual_date_formatter != expected_formatter:
            return _incompatible(existing, desired, "date formatter does not match")
        if existing.date_auto_fill not in {None, False}:
            return _incompatible(existing, desired, "date auto-fill property does not match")
    elif (
        existing.property_present
        or existing.option_count != 0
        or existing.formatter is not None
        or existing.date_formatter is not None
        or existing.date_auto_fill is not None
    ):
        return _incompatible(existing, desired, "text or checkbox property does not match")

    return None


def _property_value(property_value: FieldProperty | None, key: str) -> FieldPropertyValue | None:
    if property_value is None:
        return None
    return property_value.get(key)


def _incompatible(
    existing: FeishuBitableField,
    desired: FeishuDesiredField,
    reason: str,
) -> FeishuIncompatibleField:
    return FeishuIncompatibleField(
        field_name=desired.field_name,
        expected_logical_type=desired.logical_type,
        expected_api_type=desired.verified_api_type,
        actual_api_type=existing.type,
        actual_ui_type=existing.ui_type,
        actual_formatter=existing.formatter,
        actual_date_formatter=existing.date_formatter,
        reason=reason,
    )


__all__ = [
    "DESIRED_FEISHU_FIELDS",
    "FEISHU_DATE_FORMATTERS",
    "FEISHU_DATE_TIME_FORMATTER",
    "FEISHU_MONTH_DATE_FORMATTER",
    "FEISHU_NUMBER_FORMATTERS",
    "FeishuDesiredField",
    "FeishuIncompatibleField",
    "FeishuLogicalType",
    "FeishuSchemaPlan",
    "FeishuSchemaProvisionResult",
    "compare_field_compatibility",
    "desired_feishu_fields",
    "validate_desired_schema",
]
