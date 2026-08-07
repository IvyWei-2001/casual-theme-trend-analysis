"""Typed application configuration with optional YAML and environment overrides."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import yaml  # type: ignore[import-untyped]
from dotenv import dotenv_values
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .sensor_tower.request import (
    DEFAULT_SENSOR_TOWER_ALLOWED_GENRES,
    DEFAULT_SENSOR_TOWER_API_LIMIT,
    DEFAULT_SENSOR_TOWER_EXCLUDE_CHINA_REVENUE_MARKET,
    DEFAULT_SENSOR_TOWER_FINAL_TOP_N,
    DEFAULT_SENSOR_TOWER_SCOPE_NAME,
    DEFAULT_SENSOR_TOWER_TIMEOUT_SECONDS,
    SensorTowerSelectionConfig,
)

DEFAULT_CONFIG_PATH: Final[Path] = Path("configs/app.yaml")
DEFAULT_DATABASE_PATH: Final[Path] = Path("data/casual_theme_trends.duckdb")

_ENVIRONMENT_VARIABLES: Final[dict[str, str]] = {
    "APP_APP_NAME": "app_name",
    "APP_ENVIRONMENT": "environment",
    "APP_DATABASE_PATH": "database_path",
    "APP_LOG_LEVEL": "log_level",
    "APP_SENSOR_TOWER_API_URL": "sensor_tower_api_url",
    "APP_SENSOR_TOWER_AUTH_TOKEN": "sensor_tower_auth_token",
    "APP_SENSOR_TOWER_API_LIMIT": "sensor_tower_api_limit",
    "APP_SENSOR_TOWER_FINAL_TOP_N": "sensor_tower_final_top_n",
    "APP_SENSOR_TOWER_ALLOWED_GENRES": "sensor_tower_allowed_genres",
    "APP_SENSOR_TOWER_EXCLUDE_CHINA_REVENUE_MARKET": (
        "sensor_tower_exclude_china_revenue_market"
    ),
    "APP_SENSOR_TOWER_SCOPE_NAME": "sensor_tower_scope_name",
    "APP_SENSOR_TOWER_TIMEOUT_SECONDS": "sensor_tower_timeout_seconds",
    "APP_FEISHU_APP_ID": "feishu_app_id",
    "APP_FEISHU_APP_SECRET": "feishu_app_secret",
}


class AppConfig(BaseSettings):
    """Application settings required by the local bootstrap foundation.

    Integration credentials are optional by design. They are not validated while
    loading the local configuration because no integration is used by the
    bootstrap entrypoint.
    """

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_prefix="APP_",
        extra="ignore",
    )

    app_name: str = "casual-theme-trend-analysis"
    environment: str = "development"
    database_path: Path = DEFAULT_DATABASE_PATH
    log_level: str = "INFO"
    sensor_tower_api_url: str | None = None
    sensor_tower_auth_token: SecretStr | None = None
    sensor_tower_api_limit: int = DEFAULT_SENSOR_TOWER_API_LIMIT
    sensor_tower_final_top_n: int = DEFAULT_SENSOR_TOWER_FINAL_TOP_N
    sensor_tower_allowed_genres: tuple[str, ...] = DEFAULT_SENSOR_TOWER_ALLOWED_GENRES
    sensor_tower_exclude_china_revenue_market: bool = (
        DEFAULT_SENSOR_TOWER_EXCLUDE_CHINA_REVENUE_MARKET
    )
    sensor_tower_scope_name: str = DEFAULT_SENSOR_TOWER_SCOPE_NAME
    sensor_tower_timeout_seconds: float = DEFAULT_SENSOR_TOWER_TIMEOUT_SECONDS
    feishu_app_id: str | None = None
    feishu_app_secret: SecretStr | None = None

    @model_validator(mode="after")
    def _validate_sensor_tower_settings(self) -> AppConfig:
        SensorTowerSelectionConfig(
            api_limit=self.sensor_tower_api_limit,
            final_top_n=self.sensor_tower_final_top_n,
            allowed_genres=self.sensor_tower_allowed_genres,
            exclude_china_revenue_market=self.sensor_tower_exclude_china_revenue_market,
            scope_name=self.sensor_tower_scope_name,
        )
        if self.sensor_tower_timeout_seconds <= 0:
            raise ValueError("sensor_tower_timeout_seconds must be positive")
        return self

    @property
    def sensor_tower_selection_config(self) -> SensorTowerSelectionConfig:
        """Return validated local market selection settings."""

        return SensorTowerSelectionConfig(
            api_limit=self.sensor_tower_api_limit,
            final_top_n=self.sensor_tower_final_top_n,
            allowed_genres=self.sensor_tower_allowed_genres,
            exclude_china_revenue_market=self.sensor_tower_exclude_china_revenue_market,
            scope_name=self.sensor_tower_scope_name,
        )


def _resolve_config_path(
    config_path: str | Path | None,
    environ: Mapping[str, str],
) -> Path | None:
    if config_path is not None:
        return Path(config_path)

    environment_path = environ.get("APP_CONFIG_FILE")
    if environment_path:
        return Path(environment_path)

    if DEFAULT_CONFIG_PATH.is_file():
        return DEFAULT_CONFIG_PATH
    return None


def _load_yaml_values(config_path: Path | None) -> dict[str, Any]:
    if config_path is None:
        return {}

    with config_path.open("r", encoding="utf-8") as config_file:
        values: Any = yaml.safe_load(config_file)

    if values is None:
        return {}
    if not isinstance(values, dict):
        raise ValueError("YAML configuration must contain a top-level mapping")
    return {str(key): value for key, value in values.items()}


def _environment_values(environ: Mapping[str, str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for environment_name, field_name in _ENVIRONMENT_VARIABLES.items():
        if environment_name not in environ:
            continue
        value = environ[environment_name]
        if field_name == "sensor_tower_allowed_genres":
            values[field_name] = _parse_allowed_genres_environment_value(value)
        else:
            values[field_name] = value
    return values


def _dotenv_values() -> dict[str, Any]:
    """Read only supported ``APP_*`` settings from the local .env file."""

    raw_values = {
        key: value
        for key, value in dotenv_values(".env").items()
        if key in _ENVIRONMENT_VARIABLES and value is not None
    }
    return _environment_values(raw_values)


def _parse_allowed_genres_environment_value(value: str) -> list[str]:
    """Normalize JSON or comma-separated genre values for Pydantic."""

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in value.split(",")]

    if not isinstance(parsed, list):
        raise ValueError("APP_SENSOR_TOWER_ALLOWED_GENRES must be a JSON array or CSV list")
    return [item for item in parsed if isinstance(item, str)]


def load_config(
    config_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> AppConfig:
    """Load optional YAML settings and apply environment overrides.

    Explicit function arguments select the YAML file. Otherwise
    ``APP_CONFIG_FILE`` is used when set, followed by the optional
    ``configs/app.yaml`` file. Environment variables have precedence over YAML.
    """

    environment = os.environ if environ is None else environ
    resolved_path = _resolve_config_path(config_path, environment)
    values = _load_yaml_values(resolved_path)
    values.update(_dotenv_values())
    values.update(_environment_values(environment))
    return AppConfig.model_validate(values)
