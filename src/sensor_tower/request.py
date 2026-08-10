"""Typed request and local selection configuration for Sensor Tower."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import date as Date
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from .errors import SensorTowerConfigurationError

DEFAULT_SENSOR_TOWER_BASE_URL: Final = "https://api.sensortower.com"
SENSOR_TOWER_MARKET_ENDPOINT_PATH: Final = (
    "/v1/unified/sales_report_estimates_comparison_attributes"
)
DEFAULT_SENSOR_TOWER_ENDPOINT_PATH: Final = SENSOR_TOWER_MARKET_ENDPOINT_PATH
DEFAULT_SENSOR_TOWER_CATEGORY: Final = 7012
DEFAULT_SENSOR_TOWER_COUNTRY: Final = "WW"
DEFAULT_SENSOR_TOWER_DEVICE_TYPE: Final = "total"
DEFAULT_SENSOR_TOWER_CUSTOM_TAGS_MODE: Final = "include_unified_apps"
DEFAULT_SENSOR_TOWER_DATA_MODEL: Final = "DM_2025_Q2"
DEFAULT_SENSOR_TOWER_FILTER_FIELD_NAME: Final = "Game Genre"
DEFAULT_SENSOR_TOWER_FILTER_GLOBAL: Final = True
DEFAULT_SENSOR_TOWER_FILTER_EXCLUDE: Final = False
DEFAULT_SENSOR_TOWER_API_LIMIT: Final = 1200
DEFAULT_SENSOR_TOWER_FINAL_TOP_N: Final = 1000
DEFAULT_SENSOR_TOWER_EXCLUDE_CHINA_REVENUE_MARKET: Final = True
DEFAULT_SENSOR_TOWER_TIMEOUT_SECONDS: Final = 30.0
DEFAULT_SENSOR_TOWER_ALLOWED_GENRES: Final[tuple[str, ...]] = ("Puzzle", "Tabletop")
DEFAULT_SENSOR_TOWER_SCOPE_NAME: Final = "casual_puzzle_tabletop"

type QueryParameterValue = str | int


class SensorTowerCustomFieldFilter(BaseModel):
    """One verified Sensor Tower custom-field filter clause."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    values: tuple[str, ...]
    is_global: bool = Field(default=True, alias="global")
    exclude: bool = False

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("custom field name must be non-empty")
        return cleaned

    @field_validator("values")
    @classmethod
    def _validate_values(cls, value: Iterable[str]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value)
        if not cleaned or any(not item for item in cleaned):
            raise ValueError("custom field values must be non-empty")
        return cleaned


class SensorTowerCustomFieldsFilter(BaseModel):
    """Typed value serialized into ``custom_fields_filter_id``."""

    model_config = ConfigDict(extra="forbid")

    custom_fields: tuple[SensorTowerCustomFieldFilter, ...]

    @field_validator("custom_fields")
    @classmethod
    def _validate_custom_fields(
        cls,
        value: Iterable[SensorTowerCustomFieldFilter],
    ) -> tuple[SensorTowerCustomFieldFilter, ...]:
        fields = tuple(value)
        if not fields:
            raise ValueError("custom_fields must contain at least one field")
        return fields

    @classmethod
    def for_allowed_genres(
        cls,
        allowed_genres: Sequence[str],
        *,
        field_name: str = DEFAULT_SENSOR_TOWER_FILTER_FIELD_NAME,
        is_global: bool = DEFAULT_SENSOR_TOWER_FILTER_GLOBAL,
        exclude: bool = DEFAULT_SENSOR_TOWER_FILTER_EXCLUDE,
    ) -> SensorTowerCustomFieldsFilter:
        """Build a custom-field filter from the configured request scope."""

        return cls(
            custom_fields=(
                SensorTowerCustomFieldFilter.model_validate(
                    {
                        "name": field_name,
                        "values": tuple(allowed_genres),
                        "global": is_global,
                        "exclude": exclude,
                    }
                ),
            )
        )

    def matches_scope(
        self,
        allowed_genres: Sequence[str],
        *,
        field_name: str,
        is_global: bool,
        exclude: bool,
    ) -> bool:
        """Return whether this explicit filter matches the configured scope."""

        if len(self.custom_fields) != 1:
            return False
        field = self.custom_fields[0]
        return (
            field.name == field_name
            and field.values == tuple(allowed_genres)
            and field.is_global == is_global
            and field.exclude == exclude
        )

    def compact_json(self) -> str:
        """Serialize the filter once, leaving URL encoding to httpx."""

        return json.dumps(
            self.model_dump(mode="json", by_alias=True),
            separators=(",", ":"),
            ensure_ascii=False,
        )


class SensorTowerRequestConfig(BaseModel):
    """Configurable, verified Sensor Tower request-boundary values."""

    model_config = ConfigDict(extra="forbid")

    endpoint_path: str = DEFAULT_SENSOR_TOWER_ENDPOINT_PATH
    category: int = Field(default=DEFAULT_SENSOR_TOWER_CATEGORY, gt=0)
    country: str = DEFAULT_SENSOR_TOWER_COUNTRY
    device_type: str = DEFAULT_SENSOR_TOWER_DEVICE_TYPE
    custom_tags_mode: str = DEFAULT_SENSOR_TOWER_CUSTOM_TAGS_MODE
    data_model: str = DEFAULT_SENSOR_TOWER_DATA_MODEL
    filter_field_name: str = DEFAULT_SENSOR_TOWER_FILTER_FIELD_NAME
    filter_global: bool = DEFAULT_SENSOR_TOWER_FILTER_GLOBAL
    filter_exclude: bool = DEFAULT_SENSOR_TOWER_FILTER_EXCLUDE

    @field_validator("endpoint_path")
    @classmethod
    def _validate_endpoint_path(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Sensor Tower endpoint path must be non-empty")
        if not cleaned.startswith("/"):
            raise ValueError("Sensor Tower endpoint path must start with /")
        if "?" in cleaned:
            raise ValueError("Sensor Tower endpoint path must not contain a query string")
        return cleaned

    @field_validator(
        "country",
        "device_type",
        "custom_tags_mode",
        "data_model",
        "filter_field_name",
    )
    @classmethod
    def _validate_nonempty_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Sensor Tower request text fields must be non-empty")
        return cleaned


class SensorTowerSelectionConfig(BaseModel):
    """Configurable local over-fetch and eligibility-selection settings."""

    model_config = ConfigDict(extra="forbid")

    api_limit: int = Field(default=DEFAULT_SENSOR_TOWER_API_LIMIT, gt=0)
    final_top_n: int = Field(default=DEFAULT_SENSOR_TOWER_FINAL_TOP_N, gt=0)
    allowed_genres: tuple[str, ...] = DEFAULT_SENSOR_TOWER_ALLOWED_GENRES
    exclude_china_revenue_market: bool = DEFAULT_SENSOR_TOWER_EXCLUDE_CHINA_REVENUE_MARKET
    scope_name: str = DEFAULT_SENSOR_TOWER_SCOPE_NAME

    @field_validator("allowed_genres")
    @classmethod
    def _validate_allowed_genres(cls, value: Iterable[str]) -> tuple[str, ...]:
        genres = tuple(item.strip() for item in value)
        if not genres or any(not genre for genre in genres):
            raise ValueError("allowed genre names must be non-empty")
        return genres

    @field_validator("scope_name")
    @classmethod
    def _validate_scope_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Sensor Tower scope name must be non-empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_limits(self) -> SensorTowerSelectionConfig:
        if self.api_limit < self.final_top_n:
            raise ValueError("api_limit must be greater than or equal to final_top_n")
        return self


class SensorTowerMarketRequest(BaseModel):
    """Verified Sensor Tower market request plus local selection settings.

    The local settings are part of this typed boundary so their relationship
    can be validated alongside ``api_limit``.  ``to_query_params`` deliberately
    emits only verified API parameters; ``final_top_n`` and the other local
    settings never become request parameters.
    """

    model_config = ConfigDict(extra="forbid")

    endpoint_path: str = DEFAULT_SENSOR_TOWER_ENDPOINT_PATH
    comparison_attribute: str = "absolute"
    time_range: str = "day"
    measure: str = "units"
    device_type: str = DEFAULT_SENSOR_TOWER_DEVICE_TYPE
    category: int = Field(default=DEFAULT_SENSOR_TOWER_CATEGORY, gt=0)
    country: str = DEFAULT_SENSOR_TOWER_COUNTRY
    date: Date
    end_date: Date
    api_limit: int = Field(default=DEFAULT_SENSOR_TOWER_API_LIMIT, gt=0)
    custom_tags_mode: str = DEFAULT_SENSOR_TOWER_CUSTOM_TAGS_MODE
    data_model: str = DEFAULT_SENSOR_TOWER_DATA_MODEL
    filter_field_name: str = DEFAULT_SENSOR_TOWER_FILTER_FIELD_NAME
    filter_global: bool = DEFAULT_SENSOR_TOWER_FILTER_GLOBAL
    filter_exclude: bool = DEFAULT_SENSOR_TOWER_FILTER_EXCLUDE
    custom_fields_filter: SensorTowerCustomFieldsFilter | None = None

    final_top_n: int = Field(default=DEFAULT_SENSOR_TOWER_FINAL_TOP_N, gt=0)
    allowed_genres: tuple[str, ...] = DEFAULT_SENSOR_TOWER_ALLOWED_GENRES
    exclude_china_revenue_market: bool = DEFAULT_SENSOR_TOWER_EXCLUDE_CHINA_REVENUE_MARKET
    scope_name: str = DEFAULT_SENSOR_TOWER_SCOPE_NAME

    @field_validator(
        "comparison_attribute",
        "time_range",
        "measure",
        "device_type",
        "country",
        "custom_tags_mode",
        "data_model",
    )
    @classmethod
    def _validate_nonempty_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("request text fields must be non-empty")
        return cleaned

    @field_validator("allowed_genres")
    @classmethod
    def _validate_allowed_genres(cls, value: Iterable[str]) -> tuple[str, ...]:
        genres = tuple(item.strip() for item in value)
        if not genres or any(not genre for genre in genres):
            raise ValueError("allowed genre names must be non-empty")
        return genres

    @field_validator("scope_name")
    @classmethod
    def _validate_scope_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Sensor Tower scope name must be non-empty")
        return cleaned

    @model_validator(mode="after")
    def _validate_request(self) -> SensorTowerMarketRequest:
        self.request_config()
        if self.date > self.end_date:
            raise ValueError("date must be less than or equal to end_date")
        if self.api_limit < self.final_top_n:
            raise ValueError("api_limit must be greater than or equal to final_top_n")
        expected_filter = SensorTowerCustomFieldsFilter.for_allowed_genres(
            self.allowed_genres,
            field_name=self.filter_field_name,
            is_global=self.filter_global,
            exclude=self.filter_exclude,
        )
        if self.custom_fields_filter is None:
            object.__setattr__(self, "custom_fields_filter", expected_filter)
        elif not self.custom_fields_filter.matches_scope(
            self.allowed_genres,
            field_name=self.filter_field_name,
            is_global=self.filter_global,
            exclude=self.filter_exclude,
        ):
            raise ValueError("custom_fields_filter must match the configured request scope")
        return self

    def request_config(self) -> SensorTowerRequestConfig:
        """Return the verified request settings represented by this request."""

        return SensorTowerRequestConfig(
            endpoint_path=self.endpoint_path,
            category=self.category,
            country=self.country,
            device_type=self.device_type,
            custom_tags_mode=self.custom_tags_mode,
            data_model=self.data_model,
            filter_field_name=self.filter_field_name,
            filter_global=self.filter_global,
            filter_exclude=self.filter_exclude,
        )

    def selection_config(self) -> SensorTowerSelectionConfig:
        """Return the local selection settings represented by this request."""

        return SensorTowerSelectionConfig(
            api_limit=self.api_limit,
            final_top_n=self.final_top_n,
            allowed_genres=self.allowed_genres,
            exclude_china_revenue_market=self.exclude_china_revenue_market,
            scope_name=self.scope_name,
        )

    def custom_fields_filter_id(self) -> str:
        """Return the compact, not-yet-URL-encoded custom-field JSON."""

        if self.custom_fields_filter is None:
            raise SensorTowerConfigurationError(
                "Sensor Tower custom field filter is not configured"
            )
        return self.custom_fields_filter.compact_json()

    @classmethod
    def from_config(
        cls,
        observation_date: Date,
        *,
        request_config: SensorTowerRequestConfig,
        selection_config: SensorTowerSelectionConfig,
        end_date: Date | None = None,
    ) -> SensorTowerMarketRequest:
        """Build a request from one validated application configuration."""

        return cls(
            endpoint_path=request_config.endpoint_path,
            category=request_config.category,
            country=request_config.country,
            device_type=request_config.device_type,
            custom_tags_mode=request_config.custom_tags_mode,
            data_model=request_config.data_model,
            filter_field_name=request_config.filter_field_name,
            filter_global=request_config.filter_global,
            filter_exclude=request_config.filter_exclude,
            date=observation_date,
            end_date=observation_date if end_date is None else end_date,
            api_limit=selection_config.api_limit,
            final_top_n=selection_config.final_top_n,
            allowed_genres=selection_config.allowed_genres,
            exclude_china_revenue_market=selection_config.exclude_china_revenue_market,
            scope_name=selection_config.scope_name,
        )

    def to_query_params(self, auth_token: SecretStr | str) -> dict[str, QueryParameterValue]:
        """Build the verified query mapping for httpx.

        ``final_top_n`` and all other local selection settings are intentionally
        absent.  httpx performs the only URL encoding step when it sends this
        mapping.
        """

        token = resolve_auth_token(auth_token)
        return {
            "comparison_attribute": self.comparison_attribute,
            "time_range": self.time_range,
            "measure": self.measure,
            "device_type": self.device_type,
            "category": self.category,
            "country": self.country,
            "date": self.date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "limit": self.api_limit,
            "custom_tags_mode": self.custom_tags_mode,
            "data_model": self.data_model,
            "auth_token": token,
            "custom_fields_filter_id": self.custom_fields_filter_id(),
        }


def build_market_request(
    observation_date: Date,
    *,
    end_date: Date | None = None,
    endpoint_path: str = DEFAULT_SENSOR_TOWER_ENDPOINT_PATH,
    category: int = DEFAULT_SENSOR_TOWER_CATEGORY,
    country: str = DEFAULT_SENSOR_TOWER_COUNTRY,
    api_limit: int = DEFAULT_SENSOR_TOWER_API_LIMIT,
    final_top_n: int = DEFAULT_SENSOR_TOWER_FINAL_TOP_N,
    allowed_genres: Sequence[str] = DEFAULT_SENSOR_TOWER_ALLOWED_GENRES,
    exclude_china_revenue_market: bool = DEFAULT_SENSOR_TOWER_EXCLUDE_CHINA_REVENUE_MARKET,
    scope_name: str = DEFAULT_SENSOR_TOWER_SCOPE_NAME,
    comparison_attribute: str = "absolute",
    time_range: str = "day",
    measure: str = "units",
    device_type: str = DEFAULT_SENSOR_TOWER_DEVICE_TYPE,
    custom_tags_mode: str = DEFAULT_SENSOR_TOWER_CUSTOM_TAGS_MODE,
    data_model: str = DEFAULT_SENSOR_TOWER_DATA_MODEL,
    filter_field_name: str = DEFAULT_SENSOR_TOWER_FILTER_FIELD_NAME,
    filter_global: bool = DEFAULT_SENSOR_TOWER_FILTER_GLOBAL,
    filter_exclude: bool = DEFAULT_SENSOR_TOWER_FILTER_EXCLUDE,
) -> SensorTowerMarketRequest:
    """Construct a verified market request for one observation date."""

    return SensorTowerMarketRequest(
        endpoint_path=endpoint_path,
        comparison_attribute=comparison_attribute,
        time_range=time_range,
        measure=measure,
        device_type=device_type,
        category=category,
        country=country,
        date=observation_date,
        end_date=observation_date if end_date is None else end_date,
        api_limit=api_limit,
        custom_tags_mode=custom_tags_mode,
        data_model=data_model,
        filter_field_name=filter_field_name,
        filter_global=filter_global,
        filter_exclude=filter_exclude,
        final_top_n=final_top_n,
        allowed_genres=tuple(allowed_genres),
        exclude_china_revenue_market=exclude_china_revenue_market,
        scope_name=scope_name,
    )


def resolve_auth_token(auth_token: SecretStr | str) -> str:
    """Extract a configured token without ever including it in an error."""

    value = auth_token.get_secret_value() if isinstance(auth_token, SecretStr) else auth_token
    if not isinstance(value, str) or not value.strip():
        raise SensorTowerConfigurationError("APP_SENSOR_TOWER_AUTH_TOKEN is not configured")
    return value
