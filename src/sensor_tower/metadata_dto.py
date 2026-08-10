"""Typed source and normalized models for Sensor Tower app metadata."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

type PublisherResolutionSource = Literal[
    "android_publisher_ids",
    "publisher_name",
    "itunes_publisher_ids",
    "unavailable",
]
type MetadataPublisherIdValue = str | int | float

_POSITIVE_INTEGER_PATTERN = re.compile(r"^[0-9]+$")


def normalize_required_unified_app_id(value: object) -> str:
    """Normalize one required positive unified app ID to a string."""

    if isinstance(value, bool):
        raise ValueError("unified_app_id must be a positive integer or numeric string")

    if isinstance(value, int):
        if value <= 0:
            raise ValueError("unified_app_id must be positive")
        return str(value)

    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or not _POSITIVE_INTEGER_PATTERN.fullmatch(cleaned):
            raise ValueError("unified_app_id must be a positive integer or numeric string")
        normalized = str(int(cleaned, 10))
        if normalized == "0":
            raise ValueError("unified_app_id must be positive")
        return normalized

    raise ValueError("unified_app_id must be a positive integer or numeric string")


def normalize_optional_app_id(value: object) -> str | None:
    """Normalize an optional Android or iTunes app reference to a string."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (str, int)):
        cleaned = str(value).strip()
        return cleaned or None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return None


class SensorTowerMetadataPublisher(BaseModel):
    """Verified publisher sub-object fields used by the metadata mapping."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("publisher.name must be a string when present")
        cleaned = value.strip()
        return cleaned or None


class SensorTowerMetadataAppReference(BaseModel):
    """Android or iTunes app reference from the verified metadata shape."""

    model_config = ConfigDict(extra="ignore")

    app_id: str | None = None

    @field_validator("app_id", mode="before")
    @classmethod
    def _normalize_app_id(cls, value: object) -> str | None:
        return normalize_optional_app_id(value)


class SensorTowerMetadataApp(BaseModel):
    """Source DTO for one ``/v1/unified/apps`` app object.

    Only fields used by the verified Apps Script contract are modeled. Unknown
    source fields are ignored so the full external response is not retained in
    an internal model.
    """

    model_config = ConfigDict(extra="ignore")

    unified_app_id: str
    name: str | None = None
    publisher: SensorTowerMetadataPublisher | None = None
    android_publisher_ids: tuple[MetadataPublisherIdValue, ...] = ()
    itunes_publisher_ids: tuple[MetadataPublisherIdValue, ...] = ()
    android_apps: tuple[SensorTowerMetadataAppReference, ...] = ()
    itunes_apps: tuple[SensorTowerMetadataAppReference, ...] = ()

    @field_validator("unified_app_id", mode="before")
    @classmethod
    def _normalize_unified_app_id(cls, value: object) -> str:
        return normalize_required_unified_app_id(value)

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("metadata app name must be a string when present")
        cleaned = value.strip()
        return cleaned or None

    @field_validator("android_publisher_ids", "itunes_publisher_ids", mode="before")
    @classmethod
    def _normalize_publisher_ids(cls, value: object) -> tuple[MetadataPublisherIdValue, ...]:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise ValueError("publisher ID fields must be arrays when present")

        normalized: list[MetadataPublisherIdValue] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (str, int, float)):
                raise ValueError("publisher ID values must be strings or numbers")
            normalized.append(item)
        return tuple(normalized)

    @field_validator("android_apps", "itunes_apps", mode="before")
    @classmethod
    def _normalize_app_references(
        cls,
        value: object,
    ) -> tuple[SensorTowerMetadataAppReference, ...]:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise ValueError("app reference fields must be arrays when present")
        return tuple(value)


class SensorTowerNormalizedMetadata(BaseModel):
    """Internal metadata model with verified publisher fallback provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unified_app_id: str
    name: str | None = None
    publisher_display_name: str | None = None
    publisher_resolution_source: PublisherResolutionSource
    android_app_id: str | None = None
    ios_app_id: str | None = None


def normalize_metadata_app(app: SensorTowerMetadataApp) -> SensorTowerNormalizedMetadata:
    """Map one source DTO into the small internal metadata model."""

    android_publisher = _first_publisher_value(app.android_publisher_ids)
    if android_publisher is not None:
        publisher_display_name = android_publisher.replace("+", " ").strip() or None
        publisher_resolution_source: PublisherResolutionSource = "android_publisher_ids"
    elif app.publisher is not None and app.publisher.name is not None:
        publisher_display_name = app.publisher.name
        publisher_resolution_source = "publisher_name"
    else:
        itunes_publisher = _first_publisher_value(app.itunes_publisher_ids)
        publisher_display_name = itunes_publisher
        publisher_resolution_source = (
            "itunes_publisher_ids" if itunes_publisher is not None else "unavailable"
        )

    return SensorTowerNormalizedMetadata(
        unified_app_id=app.unified_app_id,
        name=app.name,
        publisher_display_name=publisher_display_name,
        publisher_resolution_source=publisher_resolution_source,
        android_app_id=(app.android_apps[0].app_id if app.android_apps else None),
        ios_app_id=(app.itunes_apps[0].app_id if app.itunes_apps else None),
    )


def _first_publisher_value(values: tuple[MetadataPublisherIdValue, ...]) -> str | None:
    """Return the first non-empty configured publisher value as text."""

    if not values:
        return None
    first_value = str(values[0]).strip()
    return first_value or None


# Short aliases keep the public adapter vocabulary easy to discover.
NormalizedMetadata = SensorTowerNormalizedMetadata
