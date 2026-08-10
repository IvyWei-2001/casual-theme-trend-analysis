"""Metadata batching and non-mutating attachment to selected market records."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .dto import SensorTowerMarketRecord
from .errors import (
    SensorTowerMetadataBatchError,
    SensorTowerMetadataIntegrityError,
    SensorTowerMetadataRequestError,
)
from .metadata_dto import (
    SensorTowerNormalizedMetadata,
    normalize_required_unified_app_id,
)
from .metadata_parser import SensorTowerMetadataFetchResult
from .metadata_request import SensorTowerMetadataRequest, SensorTowerMetadataRequestConfig

LOGGER = logging.getLogger(__name__)


class MetadataBatchClient(Protocol):
    """Minimal client boundary needed by the metadata enrichment workflow."""

    def fetch_metadata_batch(
        self,
        request: SensorTowerMetadataRequest,
    ) -> SensorTowerMetadataFetchResult:
        """Fetch and parse one metadata batch."""


@dataclass(frozen=True)
class EnrichedMarketRecord:
    """A selected market record paired with optional normalized metadata."""

    market_record: SensorTowerMarketRecord
    metadata: SensorTowerNormalizedMetadata | None


def fetch_metadata_for_market_records(
    client: MetadataBatchClient,
    selected_market_records: Sequence[SensorTowerMarketRecord],
    metadata_config: SensorTowerMetadataRequestConfig | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> SensorTowerMetadataFetchResult:
    """Fetch metadata only for the final selected market records.

    IDs are normalized, empty values are removed, and duplicate IDs are
    requested once in first-seen order. Requests are then split according to
    ``metadata_config.batch_size``. The injected sleeper makes retry and pacing
    behavior deterministic in tests.
    """

    requested_ids = extract_selected_unified_app_ids(selected_market_records)
    return fetch_metadata_for_unified_app_ids(
        client,
        requested_ids,
        metadata_config,
        sleep=sleep,
    )


def fetch_metadata_for_unified_app_ids(
    client: MetadataBatchClient,
    unified_app_ids: Sequence[object],
    metadata_config: SensorTowerMetadataRequestConfig | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> SensorTowerMetadataFetchResult:
    """Fetch metadata for explicit IDs in first-seen order.

    This is the cache-aware workflow boundary: callers provide only stale or
    missing IDs, so fresh metadata can be reused without being requested again.
    IDs are still normalized and deduplicated here to keep the external request
    contract safe for direct callers.
    """

    config = SensorTowerMetadataRequestConfig() if metadata_config is None else metadata_config
    requested_ids = _normalize_unified_app_ids(unified_app_ids)
    if not requested_ids:
        return _empty_metadata_result()

    metadata_by_id: dict[str, SensorTowerNormalizedMetadata] = {}
    batches = [
        requested_ids[index : index + config.batch_size]
        for index in range(0, len(requested_ids), config.batch_size)
    ]

    for batch_index, batch_ids in enumerate(batches, start=1):
        request = SensorTowerMetadataRequest.from_config(batch_ids, config)
        batch_result = _fetch_batch_with_retries(
            client,
            request,
            batch_number=batch_index,
            config=config,
            sleep=sleep,
        )
        for app_id, metadata in batch_result.metadata_by_unified_app_id.items():
            if app_id in metadata_by_id:
                raise SensorTowerMetadataIntegrityError(
                    "Sensor Tower metadata response contained a duplicate app ID across batches"
                )
            metadata_by_id[app_id] = metadata

        if batch_index < len(batches):
            sleep(config.batch_delay_seconds)

    missing_ids = tuple(app_id for app_id in requested_ids if app_id not in metadata_by_id)
    if missing_ids:
        LOGGER.warning(
            "Sensor Tower metadata enrichment is incomplete: requested=%d returned=%d missing=%d",
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


def _normalize_unified_app_ids(values: Sequence[object]) -> tuple[str, ...]:
    """Normalize and deduplicate explicit unified IDs while preserving order."""

    normalized_ids: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        app_id = normalize_required_unified_app_id(value)
        if app_id not in seen:
            normalized_ids.append(app_id)
            seen.add(app_id)
    return tuple(normalized_ids)


def attach_metadata(
    selected_market_records: Sequence[SensorTowerMarketRecord],
    metadata_result: SensorTowerMetadataFetchResult,
) -> list[EnrichedMarketRecord]:
    """Attach metadata in selected-record order without mutating market rows."""

    enriched: list[EnrichedMarketRecord] = []
    for record in selected_market_records:
        app_id = selected_record_unified_app_id(record)
        metadata = (
            metadata_result.metadata_by_unified_app_id.get(app_id)
            if app_id is not None
            else None
        )
        enriched.append(EnrichedMarketRecord(market_record=record, metadata=metadata))
    return enriched


def extract_selected_unified_app_ids(
    selected_market_records: Sequence[SensorTowerMarketRecord],
) -> tuple[str, ...]:
    """Return unique selected IDs in first-seen market-record order."""

    return extract_selected_unified_app_ids_from_records(selected_market_records)


def extract_selected_unified_app_ids_from_records(
    selected_market_records: Sequence[SensorTowerMarketRecord],
) -> tuple[str, ...]:
    """Compatibility helper with an explicit record-oriented name."""

    normalized_ids: list[str] = []
    seen: set[str] = set()
    for record in selected_market_records:
        app_id = selected_record_unified_app_id(record)
        if app_id is not None and app_id not in seen:
            normalized_ids.append(app_id)
            seen.add(app_id)
    return tuple(normalized_ids)


def selected_record_unified_app_id(record: SensorTowerMarketRecord) -> str | None:
    """Resolve a selected record's unified ID without changing the record.

    ST-002's verified unified market response exposes ``app_id`` as the
    selected identity. If a later source DTO carries an explicit
    ``unified_app_id``, that value takes precedence.
    """

    explicit_id = _record_value(record, "unified_app_id")
    if explicit_id is None:
        explicit_id = _record_value(record, "app_id")
    if explicit_id is None or (isinstance(explicit_id, str) and not explicit_id.strip()):
        return None
    try:
        return normalize_required_unified_app_id(explicit_id)
    except ValueError:
        return None


def _fetch_batch_with_retries(
    client: MetadataBatchClient,
    request: SensorTowerMetadataRequest,
    *,
    batch_number: int,
    config: SensorTowerMetadataRequestConfig,
    sleep: Callable[[float], None],
) -> SensorTowerMetadataFetchResult:
    """Retry one request and raise a sanitized final batch error if exhausted."""

    attempts = 0
    exhausted = False
    integrity_error: SensorTowerMetadataIntegrityError | None = None

    while attempts <= config.max_retries:
        attempts += 1
        try:
            return client.fetch_metadata_batch(request)
        except SensorTowerMetadataIntegrityError as error:
            integrity_error = error
            break
        except SensorTowerMetadataRequestError:
            if attempts > config.max_retries:
                exhausted = True
                break
            LOGGER.warning(
                "retrying Sensor Tower metadata batch: batch=%d attempt=%d max_attempts=%d",
                batch_number,
                attempts + 1,
                config.max_retries + 1,
            )
            sleep(config.retry_delay_seconds)

    if integrity_error is not None:
        raise integrity_error
    if exhausted:
        raise SensorTowerMetadataBatchError(batch_number, attempts)
    raise SensorTowerMetadataBatchError(batch_number, attempts)


def _empty_metadata_result() -> SensorTowerMetadataFetchResult:
    """Return the no-request result for an empty selected-ID list."""

    return SensorTowerMetadataFetchResult(
        metadata_by_unified_app_id={},
        requested_unified_app_ids=(),
        missing_unified_app_ids=(),
        requested_count=0,
        returned_count=0,
    )


def _record_value(record: SensorTowerMarketRecord, field_name: str) -> object:
    """Read a field from a DTO, including Pydantic-compatible extra fields."""

    value = getattr(record, field_name, None)
    if value is not None:
        return value

    extras = getattr(record, "model_extra", None)
    if isinstance(extras, Mapping):
        return extras.get(field_name)
    return None
