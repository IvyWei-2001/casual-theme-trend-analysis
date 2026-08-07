"""Typed application configuration with optional YAML and environment overrides."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import yaml  # type: ignore[import-untyped]
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_PATH: Final[Path] = Path("configs/app.yaml")
DEFAULT_DATABASE_PATH: Final[Path] = Path("data/casual_theme_trends.duckdb")

_ENVIRONMENT_VARIABLES: Final[dict[str, str]] = {
    "APP_APP_NAME": "app_name",
    "APP_ENVIRONMENT": "environment",
    "APP_DATABASE_PATH": "database_path",
    "APP_LOG_LEVEL": "log_level",
    "APP_SENSOR_TOWER_API_URL": "sensor_tower_api_url",
    "APP_SENSOR_TOWER_AUTH_TOKEN": "sensor_tower_auth_token",
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
    feishu_app_id: str | None = None
    feishu_app_secret: SecretStr | None = None


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


def _environment_values(environ: Mapping[str, str]) -> dict[str, str]:
    return {
        field_name: environ[environment_name]
        for environment_name, field_name in _ENVIRONMENT_VARIABLES.items()
        if environment_name in environ
    }


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
    values.update(_environment_values(environment))
    return AppConfig.model_validate(values)
