"""Pure contracts for synchronizing DuckDB trend scores to Feishu records."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from hashlib import sha256
from math import isfinite
from types import MappingProxyType
from typing import Final, Literal

from ..analysis.trend_models import ThemeTrendScore
from .errors import (
    FeishuDuplicateManagedKeyError,
    FeishuManagedRecordIntegrityError,
    FeishuSourceValidationError,
    FeishuStaleManagedRecordError,
)
from .field_schema import desired_feishu_fields
from .models import FeishuSyncRecord

PRIMARY_FIELD_NAME: Final[str] = "鏂囨湰"
MANAGED_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^ctta:v1:[0-9]{4}-[0-9]{2}:[0-9a-f]{64}$"
)
DEFAULT_FEISHU_RECORD_WRITE_BATCH_SIZE: Final[int] = 100
MIN_FEISHU_RECORD_WRITE_BATCH_SIZE: Final[int] = 1
MAX_FEISHU_RECORD_WRITE_BATCH_SIZE: Final[int] = 1000
FEISHU_NUMERIC_COMPARISON_TOLERANCE: Final[float] = 1e-9

FeishuSyncRecordCategory = Literal[
    "managed",
    "unmanaged_blank",
    "unmanaged_nonblank",
]

_SOURCE_ATTRIBUTES: Final[tuple[tuple[str, str], ...]] = (
    ("period_start", "date"),
    ("game_theme", "text"),
    ("is_latest_month", "checkbox"),
    ("is_actionable", "checkbox"),
    ("exclusion_reason", "text"),
    ("trend_rank", "number"),
    ("trend_score", "number"),
    ("confidence_score", "number"),
    ("growth_score", "number"),
    ("acceleration_score", "number"),
    ("new_product_score", "number"),
    ("concentration_penalty", "number"),
    ("latest_product_count", "number"),
    ("latest_product_share", "number"),
    ("latest_units_absolute_share", "number"),
    ("latest_revenue_absolute_share", "number"),
    ("recent3_new_entry_share", "number"),
    ("median_rank_improvement", "number"),
    ("units_absolute_overindex", "number"),
    ("revenue_absolute_overindex", "number"),
    ("calculated_at", "date-time"),
)


@dataclass(frozen=True, slots=True)
class FeishuSyncFieldMapping:
    """One exact Feishu field to internal score-property mapping."""

    field_name: str
    source_attribute: str
    logical_type: str


@dataclass(frozen=True, slots=True, repr=False)
class DesiredFeishuTrendRecord:
    """One immutable desired record, including its private technical key."""

    source_identity: tuple[str, str, date, date, str]
    managed_key: str
    fields: Mapping[str, object]

    def create_payload(self) -> dict[str, object]:
        """Return the exact batch-create record shape."""

        return build_batch_create_payload(self)

    def __repr__(self) -> str:
        """Expose only counts; managed keys and source values stay private."""

        return (
            "DesiredFeishuTrendRecord(source_field_count="
            f"{len(self.fields)!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FeishuTrendUpdate:
    """One private record-targeted update in a reconciliation plan."""

    record_id: str
    desired: DesiredFeishuTrendRecord
    fields: Mapping[str, object]

    def payload(self) -> dict[str, object]:
        """Return the exact batch-update record shape."""

        return {
            "record_id": self.record_id,
            "fields": dict(self.fields),
        }

    def __repr__(self) -> str:
        """Expose only the changed-field count."""

        return f"FeishuTrendUpdate(changed_field_count={len(self.fields)!r})"


@dataclass(frozen=True, slots=True, repr=False)
class FeishuTrendReconciliationPlan:
    """Deterministic source-to-table reconciliation result."""

    source_score_count: int
    source_month_count: int
    source_first_month: date
    source_latest_month: date
    current_record_count: int
    managed_record_count: int
    unmanaged_blank_record_count: int
    unmanaged_nonblank_record_count: int
    duplicate_managed_key_count: int
    stale_managed_record_count: int
    create_count: int
    update_count: int
    unchanged_count: int
    desired_records: tuple[DesiredFeishuTrendRecord, ...]
    create_records: tuple[DesiredFeishuTrendRecord, ...]
    updates: tuple[FeishuTrendUpdate, ...]

    @property
    def write_record_count(self) -> int:
        """Return the number of records that would be created or updated."""

        return self.create_count + self.update_count

    def write_request_count(
        self,
        batch_size: int = DEFAULT_FEISHU_RECORD_WRITE_BATCH_SIZE,
    ) -> int:
        """Return the deterministic number of create/update requests."""

        validate_record_write_batch_size(batch_size)
        return _batch_count(self.update_count, batch_size) + _batch_count(
            self.create_count,
            batch_size,
        )

    def __repr__(self) -> str:
        """Represent the plan using counts only."""

        return (
            "FeishuTrendReconciliationPlan("
            f"source_score_count={self.source_score_count!r}, "
            f"current_record_count={self.current_record_count!r}, "
            f"managed_record_count={self.managed_record_count!r}, "
            f"create_count={self.create_count!r}, "
            f"update_count={self.update_count!r}, "
            f"unchanged_count={self.unchanged_count!r}, "
            f"duplicate_managed_key_count={self.duplicate_managed_key_count!r}, "
            f"stale_managed_record_count={self.stale_managed_record_count!r})"
        )


def sync_field_mappings() -> tuple[FeishuSyncFieldMapping, ...]:
    """Return the validated exact 21-field synchronization mapping."""

    desired = desired_feishu_fields()
    if len(desired) != len(_SOURCE_ATTRIBUTES):
        raise FeishuSourceValidationError(
            "Feishu synchronization schema must contain exactly 21 managed fields"
        )
    return tuple(
        FeishuSyncFieldMapping(
            field_name=field.field_name,
            source_attribute=attribute,
            logical_type=logical_type,
        )
        for field, (attribute, logical_type) in zip(
            desired,
            _SOURCE_ATTRIBUTES,
            strict=True,
        )
    )


def validate_record_write_batch_size(batch_size: object) -> int:
    """Validate the internal Feishu batch size without contacting Feishu."""

    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not (
            MIN_FEISHU_RECORD_WRITE_BATCH_SIZE
            <= batch_size
            <= MAX_FEISHU_RECORD_WRITE_BATCH_SIZE
        )
    ):
        raise ValueError(
            "Feishu record write batch size must be an integer between 1 and 1000"
        )
    return batch_size


def theme_trend_score_identity(
    score: ThemeTrendScore,
) -> tuple[str, str, date, date, str]:
    """Return the complete authoritative source identity."""

    return (
        score.scope_name,
        score.cadence,
        score.period_start,
        score.period_end,
        score.game_theme,
    )


def managed_key_for_score(score: ThemeTrendScore) -> str:
    """Build the versioned, delimiter-safe technical key for one score row."""

    canonical_identity = "\x1f".join(
        (
            score.scope_name,
            score.cadence,
            score.period_start.isoformat(),
            score.period_end.isoformat(),
            score.game_theme,
        )
    )
    digest = sha256(canonical_identity.encode("utf-8")).hexdigest()
    managed_key = f"ctta:v1:{score.period_start.strftime('%Y-%m')}:{digest}"
    if MANAGED_KEY_PATTERN.fullmatch(managed_key) is None:
        raise FeishuSourceValidationError("generated Feishu managed key is invalid")
    return managed_key


def is_valid_managed_key(value: object) -> bool:
    """Return whether a primary-field value matches the exact key contract."""

    return isinstance(value, str) and MANAGED_KEY_PATTERN.fullmatch(value) is not None


def validate_authoritative_scores(
    scores: Sequence[ThemeTrendScore],
    *,
    scope_name: str,
) -> tuple[ThemeTrendScore, ...]:
    """Validate the complete configured monthly source score set."""

    values = tuple(scores)
    if not values:
        raise FeishuSourceValidationError(
            "DuckDB contains no ThemeTrendScore rows for the configured scope"
        )
    if any(not isinstance(row, ThemeTrendScore) for row in values):
        raise FeishuSourceValidationError(
            "DuckDB trend-score source contains a non-ThemeTrendScore row"
        )
    if any(row.scope_name != scope_name for row in values):
        raise FeishuSourceValidationError(
            "DuckDB trend-score source contains mixed scopes"
        )
    if any(row.cadence != "monthly" for row in values):
        raise FeishuSourceValidationError(
            "DuckDB trend-score source contains a non-monthly cadence"
        )
    identities = [theme_trend_score_identity(row) for row in values]
    if len(set(identities)) != len(identities):
        raise FeishuSourceValidationError(
            "DuckDB trend-score source contains duplicate identities"
        )
    return values


def score_to_feishu_fields(
    score: ThemeTrendScore,
    *,
    latest_period_start: date | None = None,
) -> Mapping[str, object]:
    """Map one score to all 21 non-primary canonical Feishu values."""

    if not isinstance(score, ThemeTrendScore):
        raise FeishuSourceValidationError("score must be a ThemeTrendScore")
    resolved_latest_period_start = (
        score.period_start if latest_period_start is None else latest_period_start
    )
    if not isinstance(resolved_latest_period_start, date) or isinstance(
        resolved_latest_period_start,
        datetime,
    ):
        raise FeishuSourceValidationError("latest_period_start must be a date")

    derived = {"is_latest_month": score.period_start == resolved_latest_period_start}
    fields: dict[str, object] = {}
    for mapping in sync_field_mappings():
        source_attribute = mapping.source_attribute
        if source_attribute == "is_latest_month":
            value = derived[source_attribute]
        else:
            value = getattr(score, source_attribute)
        fields[mapping.field_name] = _convert_score_value(
            value,
            logical_type=mapping.logical_type,
        )
    return MappingProxyType(fields)


def build_desired_trend_records(
    scores: Sequence[ThemeTrendScore],
    *,
    scope_name: str | None = None,
) -> tuple[DesiredFeishuTrendRecord, ...]:
    """Build desired records in deterministic source-identity order."""

    values = tuple(scores)
    resolved_scope_name = (
        scope_name
        if scope_name is not None
        else (values[0].scope_name if values else "")
    )
    validated = validate_authoritative_scores(values, scope_name=resolved_scope_name)
    latest_period_start = max(row.period_start for row in validated)
    records = [
        DesiredFeishuTrendRecord(
            source_identity=theme_trend_score_identity(row),
            managed_key=managed_key_for_score(row),
            fields=score_to_feishu_fields(
                row,
                latest_period_start=latest_period_start,
            ),
        )
        for row in validated
    ]
    records.sort(key=lambda record: record.source_identity)
    return tuple(records)


def build_batch_create_payload(
    desired: DesiredFeishuTrendRecord,
) -> dict[str, object]:
    """Build a create payload, preserving None/zero/false semantics."""

    fields: dict[str, object] = {PRIMARY_FIELD_NAME: desired.managed_key}
    for field_name, value in desired.fields.items():
        if value is not None:
            fields[field_name] = value
    return {"fields": fields}


def build_batch_update_fields(
    desired: DesiredFeishuTrendRecord,
    existing_fields: Mapping[str, object],
) -> Mapping[str, object]:
    """Return only canonical fields whose values differ from the existing row."""

    changed: dict[str, object] = {}
    for field_name, desired_value in desired.fields.items():
        existing_value = existing_fields.get(field_name)
        if not _canonical_values_equal(existing_value, desired_value):
            changed[field_name] = desired_value
    return MappingProxyType(changed)


def build_reconciliation_plan(
    scores: Sequence[ThemeTrendScore],
    records: Sequence[FeishuSyncRecord],
    *,
    scope_name: str | None = None,
) -> FeishuTrendReconciliationPlan:
    """Build a pure, response-order-independent synchronization plan."""

    values = tuple(scores)
    resolved_scope_name = (
        scope_name
        if scope_name is not None
        else (values[0].scope_name if values else "")
    )
    source_scores = validate_authoritative_scores(
        values,
        scope_name=resolved_scope_name,
    )
    desired_records = build_desired_trend_records(
        source_scores,
        scope_name=resolved_scope_name,
    )
    existing_records = tuple(records)
    if any(not isinstance(record, FeishuSyncRecord) for record in existing_records):
        raise FeishuManagedRecordIntegrityError(
            "Feishu synchronization records contain an unsupported record model"
        )

    managed_by_key: dict[str, list[FeishuSyncRecord]] = {}
    unmanaged_blank_count = 0
    unmanaged_nonblank_count = 0
    for record in existing_records:
        primary_value = record.primary_value
        if primary_value is None:
            unmanaged_blank_count += 1
        elif is_valid_managed_key(primary_value):
            managed_by_key.setdefault(primary_value, []).append(record)
        else:
            unmanaged_nonblank_count += 1

    duplicate_count = sum(
        len(matching_records) > 1
        for matching_records in managed_by_key.values()
    )
    desired_keys = {record.managed_key for record in desired_records}
    stale_count = sum(
        len(matching_records)
        for key, matching_records in managed_by_key.items()
        if key not in desired_keys
    )

    create_records: list[DesiredFeishuTrendRecord] = []
    updates: list[FeishuTrendUpdate] = []
    unchanged_count = 0
    if duplicate_count == 0:
        for desired in desired_records:
            matching_records = managed_by_key.get(desired.managed_key)
            if not matching_records:
                create_records.append(desired)
                continue
            existing = matching_records[0]
            changed_fields = build_batch_update_fields(desired, existing.fields)
            if changed_fields:
                updates.append(
                    FeishuTrendUpdate(
                        record_id=existing.record_id,
                        desired=desired,
                        fields=changed_fields,
                    )
                )
            else:
                unchanged_count += 1

    first_month = min(row.period_start for row in source_scores)
    latest_month = max(row.period_start for row in source_scores)
    return FeishuTrendReconciliationPlan(
        source_score_count=len(source_scores),
        source_month_count=len({row.period_start for row in source_scores}),
        source_first_month=first_month,
        source_latest_month=latest_month,
        current_record_count=len(existing_records),
        managed_record_count=sum(len(value) for value in managed_by_key.values()),
        unmanaged_blank_record_count=unmanaged_blank_count,
        unmanaged_nonblank_record_count=unmanaged_nonblank_count,
        duplicate_managed_key_count=duplicate_count,
        stale_managed_record_count=stale_count,
        create_count=len(create_records),
        update_count=len(updates),
        unchanged_count=unchanged_count,
        desired_records=desired_records,
        create_records=tuple(create_records),
        updates=tuple(updates),
    )


def require_no_duplicate_managed_keys(
    plan: FeishuTrendReconciliationPlan,
) -> None:
    """Fail without exposing any duplicate key or record identifier."""

    if plan.duplicate_managed_key_count:
        raise FeishuDuplicateManagedKeyError(plan.duplicate_managed_key_count)


def require_no_stale_managed_records(
    plan: FeishuTrendReconciliationPlan,
) -> None:
    """Fail an apply when managed records are outside the source set."""

    if plan.stale_managed_record_count:
        raise FeishuStaleManagedRecordError(plan.stale_managed_record_count)


def normalize_primary_field_value(value: object) -> str | None:
    """Normalize the supported Feishu Text-cell shapes for classification."""

    if value is None:
        return None
    normalized = _normalize_plain_text(value)
    return normalized if normalized.strip() else None


def normalize_managed_field_value(
    value: object,
    *,
    logical_type: str,
) -> object:
    """Normalize one managed Feishu cell into a safe canonical value."""

    if value is None:
        return None
    if logical_type == "text":
        return _normalize_plain_text(value)
    if logical_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FeishuManagedRecordIntegrityError(
                "managed Feishu number field has an unsupported value shape"
            )
        if not isfinite(float(value)):
            raise FeishuManagedRecordIntegrityError(
                "managed Feishu number field is not finite"
            )
        return value
    if logical_type == "checkbox":
        if not isinstance(value, bool):
            raise FeishuManagedRecordIntegrityError(
                "managed Feishu checkbox field has an unsupported value shape"
            )
        return value
    if logical_type in {"date", "date-time"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise FeishuManagedRecordIntegrityError(
                "managed Feishu date field has an unsupported value shape"
            )
        return value
    raise FeishuManagedRecordIntegrityError(
        "managed Feishu field has an unsupported logical type"
    )


def parse_sync_record_item(
    item: object,
    *,
    primary_field_name: str = PRIMARY_FIELD_NAME,
) -> FeishuSyncRecord:
    """Parse only the primary field for unmanaged rows and all managed cells otherwise."""

    if not isinstance(item, Mapping):
        raise FeishuManagedRecordIntegrityError(
            "Feishu synchronization record item is malformed"
        )
    raw_record_id = item.get("record_id")
    if not isinstance(raw_record_id, str) or not raw_record_id.strip():
        raise FeishuManagedRecordIntegrityError(
            "Feishu synchronization record identifier is malformed"
        )
    raw_fields = item.get("fields")
    if not isinstance(raw_fields, Mapping):
        raise FeishuManagedRecordIntegrityError(
            "Feishu synchronization record fields are malformed"
        )

    try:
        primary_value = normalize_primary_field_value(raw_fields.get(primary_field_name))
    except FeishuManagedRecordIntegrityError:
        raise
    except Exception:
        raise FeishuManagedRecordIntegrityError(
            "Feishu synchronization primary field is malformed"
        ) from None

    if primary_value is None or not is_valid_managed_key(primary_value):
        return FeishuSyncRecord(
            record_id=raw_record_id.strip(),
            primary_value=primary_value,
            fields=MappingProxyType({}),
        )

    normalized_fields: dict[str, object] = {}
    for mapping in sync_field_mappings():
        raw_value = raw_fields.get(mapping.field_name)
        normalized_fields[mapping.field_name] = normalize_managed_field_value(
            raw_value,
            logical_type=mapping.logical_type,
        )
    return FeishuSyncRecord(
        record_id=raw_record_id.strip(),
        primary_value=primary_value,
        fields=MappingProxyType(normalized_fields),
    )


def _convert_score_value(value: object, *, logical_type: str) -> object:
    if value is None:
        return None
    if logical_type == "date":
        if not isinstance(value, date) or isinstance(value, datetime):
            raise FeishuSourceValidationError("score date field is invalid")
        return _date_to_epoch_milliseconds(value)
    if logical_type == "date-time":
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise FeishuSourceValidationError(
                "score calculated_at must be timezone-aware"
            )
        return _datetime_to_epoch_milliseconds(value)
    if logical_type == "checkbox":
        if not isinstance(value, bool):
            raise FeishuSourceValidationError("score checkbox field is invalid")
        return value
    if logical_type == "text":
        if not isinstance(value, str):
            raise FeishuSourceValidationError("score text field is invalid")
        return value
    if logical_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FeishuSourceValidationError("score number field is invalid")
        if not isfinite(float(value)):
            raise FeishuSourceValidationError("score number field is not finite")
        return value
    raise FeishuSourceValidationError("score field logical type is invalid")


def _date_to_epoch_milliseconds(value: date) -> int:
    return _datetime_to_epoch_milliseconds(datetime.combine(value, time.min, tzinfo=UTC))


def _datetime_to_epoch_milliseconds(value: datetime) -> int:
    return int(value.astimezone(UTC).timestamp() * 1000)


def _normalize_plain_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        raise FeishuManagedRecordIntegrityError(
            "managed Feishu text field has an unsupported value shape"
        )
    pieces: list[str] = []
    for item in value:
        if not isinstance(item, Mapping) or not isinstance(item.get("text"), str):
            raise FeishuManagedRecordIntegrityError(
                "managed Feishu text field has an unsupported value shape"
            )
        pieces.append(item["text"])
    return "".join(pieces)


def _canonical_values_equal(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if (
        not isinstance(left, bool)
        and not isinstance(right, bool)
        and isinstance(left, (int, float))
        and isinstance(right, (int, float))
    ):
        return (
            isfinite(float(left))
            and isfinite(float(right))
            and abs(float(left) - float(right))
            <= FEISHU_NUMERIC_COMPARISON_TOLERANCE
        )
    return type(left) is type(right) and left == right


def _batch_count(record_count: int, batch_size: int) -> int:
    return (record_count + batch_size - 1) // batch_size


__all__ = [
    "DEFAULT_FEISHU_RECORD_WRITE_BATCH_SIZE",
    "FEISHU_NUMERIC_COMPARISON_TOLERANCE",
    "FeishuSyncFieldMapping",
    "FeishuTrendReconciliationPlan",
    "FeishuTrendUpdate",
    "DesiredFeishuTrendRecord",
    "MANAGED_KEY_PATTERN",
    "MAX_FEISHU_RECORD_WRITE_BATCH_SIZE",
    "MIN_FEISHU_RECORD_WRITE_BATCH_SIZE",
    "PRIMARY_FIELD_NAME",
    "build_batch_create_payload",
    "build_desired_trend_records",
    "build_reconciliation_plan",
    "build_batch_update_fields",
    "is_valid_managed_key",
    "managed_key_for_score",
    "normalize_managed_field_value",
    "normalize_primary_field_value",
    "parse_sync_record_item",
    "require_no_duplicate_managed_keys",
    "require_no_stale_managed_records",
    "score_to_feishu_fields",
    "sync_field_mappings",
    "theme_trend_score_identity",
    "validate_authoritative_scores",
    "validate_record_write_batch_size",
]
