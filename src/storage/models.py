"""Typed internal rows used by the DuckDB storage boundary.

These models intentionally contain no HTTP response objects, credentials, or
Sensor Tower DTOs.  Source-specific mapping happens in :mod:`src.storage.mappers`;
the repository only accepts these normalized rows.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from types import MappingProxyType
from typing import Literal

from .errors import StorageValidationError

type Cadence = Literal["monthly", "weekly"]
type PublisherResolutionSource = Literal[
    "android_publisher_ids",
    "publisher_name",
    "itunes_publisher_ids",
    "unavailable",
]

_POSITIVE_INTEGER_PATTERN = re.compile(r"^[0-9]+$")
_VALID_CADENCES = frozenset({"monthly", "weekly"})
_VALID_PUBLISHER_RESOLUTION_SOURCES = frozenset(
    {
        "android_publisher_ids",
        "publisher_name",
        "itunes_publisher_ids",
        "unavailable",
    }
)
_PLACEHOLDER_TEXT = frozenset({"Unknown", "N/A"})


def normalize_positive_id(value: object, *, field_name: str = "unified_app_id") -> str:
    """Normalize a positive integer-like application ID to a decimal string."""

    if isinstance(value, bool):
        raise StorageValidationError(f"{field_name} must be a positive integer ID")

    if isinstance(value, int):
        if value <= 0:
            raise StorageValidationError(f"{field_name} must be a positive integer ID")
        return str(value)

    if isinstance(value, str):
        cleaned = value.strip()
        if not _POSITIVE_INTEGER_PATTERN.fullmatch(cleaned):
            raise StorageValidationError(f"{field_name} must be a positive integer ID")
        normalized = str(int(cleaned, 10))
        if normalized == "0":
            raise StorageValidationError(f"{field_name} must be a positive integer ID")
        return normalized

    raise StorageValidationError(f"{field_name} must be a positive integer ID")


def normalize_id_sequence(values: Sequence[object]) -> tuple[str, ...]:
    """Normalize and deduplicate IDs while preserving first-seen order."""

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        app_id = normalize_positive_id(value)
        if app_id not in seen:
            normalized.append(app_id)
            seen.add(app_id)
    return tuple(normalized)


def require_timezone_aware(value: object, *, field_name: str) -> datetime:
    """Validate a timestamp has an actual UTC offset."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StorageValidationError(f"{field_name} must be timezone-aware")
    return value


def _require_date(value: object, *, field_name: str) -> date:
    if type(value) is not date:
        raise StorageValidationError(f"{field_name} must be a date")
    return value


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StorageValidationError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise StorageValidationError(f"{field_name} must be a string or NULL")
    if value in _PLACEHOLDER_TEXT:
        raise StorageValidationError(f"{field_name} must not use placeholder text")
    return value


def _optional_date(value: object, *, field_name: str) -> date | None:
    if value is None:
        return None
    return _require_date(value, field_name=field_name)


def _optional_number(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StorageValidationError(f"{field_name} must be a number or NULL")
    numeric_value = float(value)
    if not isfinite(numeric_value):
        raise StorageValidationError(f"{field_name} must be finite when present")
    return numeric_value


@dataclass(frozen=True, slots=True)
class SnapshotPeriodKey:
    """Composite identity of one stored market period."""

    scope_name: str
    cadence: Cadence
    period_start: date
    period_end: date

    def __post_init__(self) -> None:
        _require_text(self.scope_name, field_name="scope_name")
        if self.cadence not in _VALID_CADENCES:
            raise StorageValidationError("cadence must be 'monthly' or 'weekly'")
        start = _require_date(self.period_start, field_name="period_start")
        end = _require_date(self.period_end, field_name="period_end")
        if start > end:
            raise StorageValidationError("period_start must be on or before period_end")


@dataclass(frozen=True, slots=True)
class AppMetadataRow:
    """One normalized, persistent metadata-cache row."""

    unified_app_id: str
    name: str | None
    publisher_display_name: str | None
    publisher_resolution_source: PublisherResolutionSource
    android_app_id: str | None
    ios_app_id: str | None
    fetched_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "unified_app_id",
            normalize_positive_id(self.unified_app_id, field_name="unified_app_id"),
        )
        object.__setattr__(
            self,
            "name",
            _optional_text(self.name, field_name="name"),
        )
        object.__setattr__(
            self,
            "publisher_display_name",
            _optional_text(self.publisher_display_name, field_name="publisher_display_name"),
        )
        if self.publisher_resolution_source not in _VALID_PUBLISHER_RESOLUTION_SOURCES:
            raise StorageValidationError(
                "publisher_resolution_source is not a supported resolution source"
            )
        object.__setattr__(
            self,
            "android_app_id",
            _optional_text(self.android_app_id, field_name="android_app_id"),
        )
        object.__setattr__(
            self,
            "ios_app_id",
            _optional_text(self.ios_app_id, field_name="ios_app_id"),
        )
        object.__setattr__(
            self,
            "fetched_at",
            require_timezone_aware(self.fetched_at, field_name="fetched_at"),
        )


@dataclass(frozen=True, slots=True)
class MarketSnapshotRow:
    """One normalized selected product in one stored market period."""

    scope_name: str
    cadence: Cadence
    period_start: date
    period_end: date
    rank_position: int
    source_app_id: str
    unified_app_id: str
    scope_country: str
    device_type: str
    category: int
    data_model: str
    source_date: datetime
    source_country: str | None
    current_units_value: float | None
    units_absolute: float | None
    comparison_units_value: float | None
    units_delta: float | None
    units_transformed_delta: float | None
    current_revenue_value: float | None
    revenue_absolute: float | None
    comparison_revenue_value: float | None
    revenue_delta: float | None
    revenue_transformed_delta: float | None
    absolute: float | None
    delta: float | None
    transformed_delta: float | None
    game_theme: str | None
    game_genre: str | None
    game_subgenre: str | None
    game_product_model: str | None
    game_art_style: str | None
    game_setting: str | None
    earliest_release_date: date | None
    release_date_ww: date | None
    publisher_country: str | None
    most_popular_country_by_revenue: str | None
    is_unified_source_value: str | None
    collected_at: datetime

    def __post_init__(self) -> None:
        SnapshotPeriodKey(
            scope_name=self.scope_name,
            cadence=self.cadence,
            period_start=self.period_start,
            period_end=self.period_end,
        )
        _require_text(self.scope_country, field_name="scope_country")
        _require_text(self.device_type, field_name="device_type")
        _require_text(self.data_model, field_name="data_model")
        if isinstance(self.rank_position, bool) or not isinstance(self.rank_position, int):
            raise StorageValidationError("rank_position must be a positive integer")
        if self.rank_position <= 0:
            raise StorageValidationError("rank_position must be a positive integer")
        if isinstance(self.category, bool) or not isinstance(self.category, int):
            raise StorageValidationError("category must be a positive integer")
        if self.category <= 0:
            raise StorageValidationError("category must be a positive integer")

        object.__setattr__(
            self,
            "source_app_id",
            normalize_positive_id(self.source_app_id, field_name="source_app_id"),
        )
        object.__setattr__(
            self,
            "unified_app_id",
            normalize_positive_id(self.unified_app_id, field_name="unified_app_id"),
        )
        object.__setattr__(
            self,
            "source_date",
            require_timezone_aware(self.source_date, field_name="source_date"),
        )
        object.__setattr__(
            self,
            "collected_at",
            require_timezone_aware(self.collected_at, field_name="collected_at"),
        )

        numeric_fields = (
            "current_units_value",
            "units_absolute",
            "comparison_units_value",
            "units_delta",
            "units_transformed_delta",
            "current_revenue_value",
            "revenue_absolute",
            "comparison_revenue_value",
            "revenue_delta",
            "revenue_transformed_delta",
            "absolute",
            "delta",
            "transformed_delta",
        )
        for field_name in numeric_fields:
            object.__setattr__(
                self,
                field_name,
                _optional_number(getattr(self, field_name), field_name=field_name),
            )

        text_fields = (
            "source_country",
            "game_theme",
            "game_genre",
            "game_subgenre",
            "game_product_model",
            "game_art_style",
            "game_setting",
            "publisher_country",
            "most_popular_country_by_revenue",
            "is_unified_source_value",
        )
        for field_name in text_fields:
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name), field_name=field_name),
            )

        for field_name in ("earliest_release_date", "release_date_ww"):
            object.__setattr__(
                self,
                field_name,
                _optional_date(getattr(self, field_name), field_name=field_name),
            )

    @property
    def period_key(self) -> SnapshotPeriodKey:
        """Return this row's composite market-period identity."""

        return SnapshotPeriodKey(
            scope_name=self.scope_name,
            cadence=self.cadence,
            period_start=self.period_start,
            period_end=self.period_end,
        )

    @property
    def request_provenance(self) -> tuple[str, str, int, str]:
        """Return fields that must be consistent within one replacement."""

        return (self.scope_country, self.device_type, self.category, self.data_model)


@dataclass(frozen=True, slots=True)
class MetadataCacheLookup:
    """Result of a local metadata-cache lookup with no automatic refresh."""

    fresh_metadata_by_id: Mapping[str, AppMetadataRow]
    ids_to_fetch: tuple[str, ...]
    stale_ids: tuple[str, ...]
    missing_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fresh_metadata_by_id",
            MappingProxyType(dict(self.fresh_metadata_by_id)),
        )
        object.__setattr__(self, "ids_to_fetch", tuple(self.ids_to_fetch))
        object.__setattr__(self, "stale_ids", tuple(self.stale_ids))
        object.__setattr__(self, "missing_ids", tuple(self.missing_ids))
