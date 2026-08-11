"""Typed, secret-safe models for the read-only Feishu boundary."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator, model_validator

DEFAULT_FEISHU_API_BASE_URL: Final[str] = "https://open.feishu.cn"
DEFAULT_FEISHU_TIMEOUT_SECONDS: Final[float] = 20.0
FEISHU_AUTHENTICATION_PATH: Final[str] = "/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_FIELDS_PATH_PREFIX: Final[str] = "/open-apis/bitable/v1/apps"
FEISHU_FIELD_PAGE_SIZE: Final[int] = 100
FEISHU_RECORD_PAGE_SIZE: Final[int] = 100


def validate_feishu_api_base_url(value: str) -> str:
    """Normalize a Feishu base URL without accepting an authenticated URL."""

    cleaned = value.strip().rstrip("/")
    parsed = urlsplit(cleaned)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Feishu API base URL must be an https URL without userinfo, query, or fragment"
        )
    return cleaned


def _validate_optional_text(value: object, *, field_name: str) -> object:
    """Validate an optional non-secret text setting without exposing its value."""

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string when configured")
    return value.strip()


def _secret_value(value: object, *, field_name: str) -> str:
    """Read a secret-like value while keeping validation messages value-free."""

    raw_value = value.get_secret_value() if isinstance(value, SecretStr) else value
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return raw_value.strip()


class FeishuClientConfig(BaseModel):
    """Required settings for one real read-only Feishu field inspection."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    base_url: str = DEFAULT_FEISHU_API_BASE_URL
    app_id: str
    app_secret: SecretStr
    bitable_app_token: SecretStr
    bitable_table_id: str
    bitable_view_id: str | None = None
    timeout_seconds: float = DEFAULT_FEISHU_TIMEOUT_SECONDS

    @field_validator("base_url")
    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        return validate_feishu_api_base_url(value)

    @field_validator("app_id", "bitable_table_id")
    @classmethod
    def _normalize_required_text(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "Feishu setting")
        result = _validate_optional_text(value, field_name=str(field_name))
        if not isinstance(result, str):
            raise ValueError(f"{field_name} must be a non-empty string")
        return result

    @field_validator("app_secret", "bitable_app_token", mode="before")
    @classmethod
    def _normalize_required_secret(cls, value: object, info: object) -> str:
        field_name = getattr(info, "field_name", "Feishu secret")
        return _secret_value(value, field_name=str(field_name))

    @field_validator("bitable_view_id")
    @classmethod
    def _validate_view_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        result = _validate_optional_text(value, field_name="bitable_view_id")
        if not isinstance(result, str):
            raise ValueError("bitable_view_id must be a non-empty string when configured")
        if not result.startswith("vew"):
            raise ValueError("Feishu Bitable view_id must begin with vew")
        return result

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def _validate_timeout(cls, value: object) -> float:
        if isinstance(value, bool):
            raise ValueError("Feishu timeout must be positive and finite")
        try:
            numeric_value = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as error:
            raise ValueError("Feishu timeout must be positive and finite") from error
        if not math.isfinite(numeric_value) or numeric_value <= 0:
            raise ValueError("Feishu timeout must be positive and finite")
        return numeric_value

    @model_validator(mode="after")
    def _validate_table_id_prefix(self) -> FeishuClientConfig:
        if not self.bitable_table_id.startswith("tbl"):
            raise ValueError("Feishu Bitable table_id must begin with tbl")
        return self


class FeishuAccessToken(BaseModel):
    """Tenant access token held in a secret-safe model."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    tenant_access_token: SecretStr
    expire: int | None = None

    @field_validator("tenant_access_token", mode="before")
    @classmethod
    def _validate_token(cls, value: object) -> str:
        return _secret_value(value, field_name="tenant_access_token")

    @field_validator("expire")
    @classmethod
    def _validate_expire(cls, value: int | None) -> int | None:
        if value is not None and (isinstance(value, bool) or value < 0):
            raise ValueError("Feishu token expire must be a non-negative integer")
        return value

    def __repr__(self) -> str:
        """Represent token metadata without exposing the tenant token."""

        return f"FeishuAccessToken(expire={self.expire!r})"


@dataclass(frozen=True, slots=True)
class FeishuBitableField:
    """Normalized metadata for one Feishu Bitable field."""

    field_id: str
    field_name: str
    type: int
    ui_type: str | None
    is_primary: bool | None
    option_count: int
    option_names: tuple[str, ...]
    formatter: str | None = None
    date_formatter: str | None = None
    date_auto_fill: bool | None = None
    property_present: bool = False


@dataclass(frozen=True, slots=True)
class FeishuBitableRecord:
    """Safe in-memory metadata for one Bitable record.

    The record identifier is retained only so the client can detect duplicate
    records across pages. Cell values are deliberately discarded immediately;
    only field-name presence and primary-field value presence remain.
    """

    record_id: str
    fields_is_mapping: bool
    field_names: frozenset[str]
    has_primary_value: bool

    @property
    def fields_are_mapping(self) -> bool:
        """Expose the same invariant using a grammatically natural name."""

        return self.fields_is_mapping

    def __repr__(self) -> str:
        """Represent record metadata without exposing the record ID."""

        return (
            "FeishuBitableRecord(record_id=<redacted>, "
            f"fields_is_mapping={self.fields_is_mapping!r}, "
            f"field_name_count={len(self.field_names)!r}, "
            f"has_primary_value={self.has_primary_value!r})"
        )


@dataclass(frozen=True, slots=True)
class FeishuRecordListResult:
    """Sanitized result of one complete paginated record-list request."""

    records: tuple[FeishuBitableRecord, ...]
    page_count: int

    @property
    def record_count(self) -> int:
        """Return the number of records without exposing record identifiers."""

        return len(self.records)

    @property
    def records_with_primary_value(self) -> int:
        """Count records whose configured primary field has a value."""

        return sum(record.has_primary_value for record in self.records)

    @property
    def observed_field_names(self) -> frozenset[str]:
        """Return the union of observed field names without cell values."""

        names: set[str] = set()
        for record in self.records:
            names.update(record.field_names)
        return frozenset(names)

    def __iter__(self) -> Iterator[FeishuBitableRecord]:
        """Allow callers to iterate records without changing the safe model."""

        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> FeishuBitableRecord:
        return self.records[index]

    def __repr__(self) -> str:
        """Represent only aggregate counts; record IDs remain private."""

        return (
            "FeishuRecordListResult("
            f"record_count={self.record_count!r}, page_count={self.page_count!r}, "
            f"records_with_primary_value={self.records_with_primary_value!r}, "
            f"observed_field_name_count={len(self.observed_field_names)!r})"
        )


@dataclass(frozen=True, slots=True)
class FeishuRecordInspectionResult:
    """Sanitized schema-gated result of a read-only record inspection."""

    schema_field_count: int
    desired_non_primary_field_count: int
    compatible_existing_count: int
    missing_field_count: int
    incompatible_field_count: int
    existing_primary_field_name: str
    record_page_count: int
    record_count: int
    records_with_primary_value: int
    records_without_primary_value: int
    observed_field_name_count: int
    duplicate_record_id_count: int
    inspected_at: datetime
    app_token_suffix: str
    table_id: str

    def __repr__(self) -> str:
        """Represent the inspection without raw record or cell data."""

        return (
            "FeishuRecordInspectionResult("
            f"schema_field_count={self.schema_field_count!r}, "
            f"record_page_count={self.record_page_count!r}, "
            f"record_count={self.record_count!r}, "
            f"records_with_primary_value={self.records_with_primary_value!r}, "
            f"records_without_primary_value={self.records_without_primary_value!r}, "
            f"observed_field_name_count={self.observed_field_name_count!r}, "
            f"duplicate_record_id_count={self.duplicate_record_id_count!r}, "
            f"app_token_suffix={self.app_token_suffix!r}, table_id={self.table_id!r})"
        )


@dataclass(frozen=True, slots=True)
class FeishuFieldInspectionResult:
    """Sanitized result of one read-only Bitable field inspection."""

    field_count: int
    primary_field_count: int
    duplicate_field_names: tuple[str, ...]
    fields: tuple[FeishuBitableField, ...]
    inspected_at: datetime
    app_token_suffix: str
    table_id: str
    view_id: str | None

    @classmethod
    def from_fields(
        cls,
        fields: tuple[FeishuBitableField, ...],
        *,
        inspected_at: datetime,
        app_token: str,
        table_id: str,
        view_id: str | None,
    ) -> FeishuFieldInspectionResult:
        """Build a result while retaining only the final four app-token characters."""

        name_counts: dict[str, int] = {}
        for field in fields:
            if field.field_name:
                name_counts[field.field_name] = name_counts.get(field.field_name, 0) + 1
        duplicate_names = tuple(
            name for name in (field.field_name for field in fields) if name_counts.get(name, 0) > 1
        )
        duplicate_names = tuple(dict.fromkeys(duplicate_names))
        return cls(
            field_count=len(fields),
            primary_field_count=sum(field.is_primary is True for field in fields),
            duplicate_field_names=duplicate_names,
            fields=fields,
            inspected_at=inspected_at,
            app_token_suffix=app_token[-4:],
            table_id=table_id,
            view_id=view_id,
        )
    def __repr__(self) -> str:
        """Represent the audit without any authenticated value or raw response."""

        return (
            "FeishuFieldInspectionResult("
            f"field_count={self.field_count!r}, "
            f"primary_field_count={self.primary_field_count!r}, "
            f"duplicate_field_names={self.duplicate_field_names!r}, "
            f"fields={self.fields!r}, "
            f"inspected_at={self.inspected_at!r}, "
            f"app_token_suffix={self.app_token_suffix!r}, "
            f"table_id={self.table_id!r}, view_id={self.view_id!r})"
        )
