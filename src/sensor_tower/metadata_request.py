"""Configuration and request models for the verified metadata endpoint."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from ..identifiers import normalize_required_opaque_id
from .request import resolve_auth_token

DEFAULT_SENSOR_TOWER_METADATA_ENDPOINT_PATH: Final = "/v1/unified/apps"
DEFAULT_SENSOR_TOWER_METADATA_BATCH_SIZE: Final = 50
DEFAULT_SENSOR_TOWER_METADATA_APP_ID_TYPE: Final = "unified"
DEFAULT_SENSOR_TOWER_METADATA_FIELDS: Final[tuple[str, ...]] = (
    "name",
    "publisher",
    "android_publisher_ids",
    "itunes_publisher_ids",
    "android_apps",
    "itunes_apps",
    "unified_app_id",
)
DEFAULT_SENSOR_TOWER_METADATA_MAX_RETRIES: Final = 2
DEFAULT_SENSOR_TOWER_METADATA_RETRY_DELAY_SECONDS: Final = 1.5
DEFAULT_SENSOR_TOWER_METADATA_BATCH_DELAY_SECONDS: Final = 0.3

type MetadataQueryParameterValue = str


class SensorTowerMetadataRequestConfig(BaseModel):
    """Validated settings for metadata endpoint requests and pacing."""

    model_config = ConfigDict(extra="forbid")

    endpoint_path: str = DEFAULT_SENSOR_TOWER_METADATA_ENDPOINT_PATH
    batch_size: int = Field(default=DEFAULT_SENSOR_TOWER_METADATA_BATCH_SIZE, gt=0)
    app_id_type: str = DEFAULT_SENSOR_TOWER_METADATA_APP_ID_TYPE
    fields: tuple[str, ...] = DEFAULT_SENSOR_TOWER_METADATA_FIELDS
    max_retries: int = Field(default=DEFAULT_SENSOR_TOWER_METADATA_MAX_RETRIES, ge=0)
    retry_delay_seconds: float = Field(
        default=DEFAULT_SENSOR_TOWER_METADATA_RETRY_DELAY_SECONDS,
        ge=0,
    )
    batch_delay_seconds: float = Field(
        default=DEFAULT_SENSOR_TOWER_METADATA_BATCH_DELAY_SECONDS,
        ge=0,
    )

    @field_validator("endpoint_path")
    @classmethod
    def _validate_endpoint_path(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Sensor Tower metadata endpoint path must be non-empty")
        if not cleaned.startswith("/"):
            raise ValueError("Sensor Tower metadata endpoint path must start with /")
        if "?" in cleaned:
            raise ValueError("Sensor Tower metadata endpoint path must not contain a query string")
        return cleaned

    @field_validator("app_id_type")
    @classmethod
    def _validate_app_id_type(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Sensor Tower metadata app_id_type must be non-empty")
        return cleaned

    @field_validator("fields")
    @classmethod
    def _validate_fields(cls, value: Iterable[str]) -> tuple[str, ...]:
        fields = tuple(item.strip() for item in value)
        if not fields or any(not field for field in fields):
            raise ValueError("Sensor Tower metadata fields must be non-empty")
        if len(set(fields)) != len(fields):
            raise ValueError("Sensor Tower metadata fields must not contain duplicates")
        return fields


class SensorTowerMetadataRequest(BaseModel):
    """One batched GET request to ``/v1/unified/apps``."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    endpoint_path: str = DEFAULT_SENSOR_TOWER_METADATA_ENDPOINT_PATH
    app_id_type: str = DEFAULT_SENSOR_TOWER_METADATA_APP_ID_TYPE
    app_ids: tuple[str, ...]
    fields: tuple[str, ...] = DEFAULT_SENSOR_TOWER_METADATA_FIELDS

    @field_validator("endpoint_path")
    @classmethod
    def _validate_endpoint_path(cls, value: str) -> str:
        return SensorTowerMetadataRequestConfig(endpoint_path=value).endpoint_path

    @field_validator("app_id_type")
    @classmethod
    def _validate_app_id_type(cls, value: str) -> str:
        return SensorTowerMetadataRequestConfig(app_id_type=value).app_id_type

    @field_validator("app_ids", mode="before")
    @classmethod
    def _normalize_app_ids(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("metadata app_ids must be a sequence")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if item is None or (isinstance(item, str) and not item.strip()):
                continue
            app_id = normalize_required_opaque_id(item, field_name="unified_app_id")
            if app_id not in seen:
                normalized.append(app_id)
                seen.add(app_id)
        if not normalized:
            raise ValueError("metadata app_ids must contain at least one ID")
        return tuple(normalized)

    @field_validator("fields")
    @classmethod
    def _validate_fields(cls, value: Iterable[str]) -> tuple[str, ...]:
        return SensorTowerMetadataRequestConfig(fields=tuple(value)).fields

    @classmethod
    def from_config(
        cls,
        unified_app_ids: Sequence[object],
        config: SensorTowerMetadataRequestConfig,
    ) -> SensorTowerMetadataRequest:
        """Build one request from a validated batch and metadata settings."""

        normalized_app_ids = tuple(
            normalize_required_opaque_id(app_id, field_name="unified_app_id")
            for app_id in unified_app_ids
        )
        return cls(
            endpoint_path=config.endpoint_path,
            app_id_type=config.app_id_type,
            app_ids=normalized_app_ids,
            fields=config.fields,
        )

    def to_query_params(
        self,
        auth_token: SecretStr | str,
    ) -> dict[str, MetadataQueryParameterValue]:
        """Return only the verified metadata query parameters."""

        return {
            "app_id_type": self.app_id_type,
            "app_ids": ",".join(self.app_ids),
            "fields": ",".join(self.fields),
            "auth_token": resolve_auth_token(auth_token),
        }


def build_metadata_request(
    unified_app_ids: Sequence[object],
    *,
    config: SensorTowerMetadataRequestConfig | None = None,
) -> SensorTowerMetadataRequest:
    """Build one normalized metadata request for a caller-provided batch."""

    metadata_config = SensorTowerMetadataRequestConfig() if config is None else config
    return SensorTowerMetadataRequest.from_config(
        tuple(item for item in unified_app_ids if item is not None),
        metadata_config,
    )


# A concise alias for callers that do not need the request-specific name.
SensorTowerMetadataConfig = SensorTowerMetadataRequestConfig
