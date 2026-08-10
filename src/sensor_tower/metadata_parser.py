"""Parsing and integrity validation for the verified metadata response."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from ..identifiers import normalize_required_opaque_id
from .errors import (
    SensorTowerMetadataIntegrityError,
    SensorTowerMetadataMalformedResponseError,
)
from .metadata_dto import (
    SensorTowerMetadataApp,
    SensorTowerNormalizedMetadata,
    normalize_metadata_app,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SensorTowerMetadataFetchResult:
    """Normalized metadata and request/response coverage for one or more batches."""

    metadata_by_unified_app_id: Mapping[str, SensorTowerNormalizedMetadata]
    requested_unified_app_ids: tuple[str, ...]
    missing_unified_app_ids: tuple[str, ...]
    requested_count: int
    returned_count: int


def parse_metadata_response(
    payload: object,
    requested_unified_app_ids: Sequence[object],
) -> SensorTowerMetadataFetchResult:
    """Parse one metadata response and validate its requested-ID integrity.

    The verified envelope is an object containing an ``apps`` array. If the
    ``apps`` field is absent, this adapter documents and treats it as an empty
    result. A present non-list value is malformed and fails clearly.
    """

    if not isinstance(payload, Mapping):
        raise SensorTowerMetadataMalformedResponseError(
            "Sensor Tower metadata response must be a JSON object"
        )

    requested_ids = _normalize_requested_ids(requested_unified_app_ids)
    apps_value = payload.get("apps", [])
    if not isinstance(apps_value, list):
        raise SensorTowerMetadataMalformedResponseError(
            "Sensor Tower metadata response apps field must be a JSON array"
        )

    metadata_by_id: dict[str, SensorTowerNormalizedMetadata] = {}
    requested_id_set = set(requested_ids)
    for item in apps_value:
        if not isinstance(item, Mapping):
            raise SensorTowerMetadataMalformedResponseError(
                "Sensor Tower metadata app entries must be JSON objects"
            )

        app: SensorTowerMetadataApp | None = None
        validation_failed = False
        try:
            app = SensorTowerMetadataApp.model_validate(item)
        except (TypeError, ValueError, ValidationError):
            validation_failed = True
        if validation_failed or app is None:
            raise SensorTowerMetadataMalformedResponseError(
                "Sensor Tower metadata app entry did not match the verified shape"
            )

        normalized = normalize_metadata_app(app)
        if normalized.unified_app_id not in requested_id_set:
            raise SensorTowerMetadataIntegrityError(
                "Sensor Tower metadata response contained an unrequested app ID"
            )
        if normalized.unified_app_id in metadata_by_id:
            raise SensorTowerMetadataIntegrityError(
                "Sensor Tower metadata response contained a duplicate app ID"
            )
        metadata_by_id[normalized.unified_app_id] = normalized

    missing_ids = tuple(app_id for app_id in requested_ids if app_id not in metadata_by_id)
    if missing_ids:
        LOGGER.warning(
            "Sensor Tower metadata response omitted IDs: requested=%d returned=%d missing=%d",
            len(requested_ids),
            len(metadata_by_id),
            len(missing_ids),
        )

    return SensorTowerMetadataFetchResult(
        metadata_by_unified_app_id=metadata_by_id,
        requested_unified_app_ids=requested_ids,
        missing_unified_app_ids=missing_ids,
        requested_count=len(requested_ids),
        returned_count=len(metadata_by_id),
    )


def _normalize_requested_ids(values: Sequence[object]) -> tuple[str, ...]:
    """Normalize and deduplicate requested IDs while preserving first-seen order."""

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        app_id = normalize_required_opaque_id(value, field_name="unified_app_id")
        if app_id not in seen:
            normalized.append(app_id)
            seen.add(app_id)
    return tuple(normalized)


# Concise aliases for callers that use the generic metadata vocabulary.
MetadataFetchResult = SensorTowerMetadataFetchResult
MetadataBatchResult = SensorTowerMetadataFetchResult
