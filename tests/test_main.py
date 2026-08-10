"""Tests for the local module entrypoint."""

import logging
from pathlib import Path

import pytest

from src.__main__ import main

_CONFIG_ENVIRONMENT_NAMES = (
    "APP_APP_NAME",
    "APP_ENVIRONMENT",
    "APP_DATABASE_PATH",
    "APP_LOG_LEVEL",
    "APP_CONFIG_FILE",
    "APP_SENSOR_TOWER_API_URL",
    "APP_SENSOR_TOWER_AUTH_TOKEN",
    "APP_SENSOR_TOWER_ENDPOINT_PATH",
    "APP_SENSOR_TOWER_CATEGORY",
    "APP_SENSOR_TOWER_COUNTRY",
    "APP_SENSOR_TOWER_DEVICE_TYPE",
    "APP_SENSOR_TOWER_CUSTOM_TAGS_MODE",
    "APP_SENSOR_TOWER_DATA_MODEL",
    "APP_SENSOR_TOWER_FILTER_FIELD_NAME",
    "APP_SENSOR_TOWER_FILTER_GLOBAL",
    "APP_SENSOR_TOWER_FILTER_EXCLUDE",
    "APP_SENSOR_TOWER_API_LIMIT",
    "APP_SENSOR_TOWER_FINAL_TOP_N",
    "APP_SENSOR_TOWER_ALLOWED_GENRES",
    "APP_SENSOR_TOWER_EXCLUDE_CHINA_REVENUE_MARKET",
    "APP_SENSOR_TOWER_SCOPE_NAME",
    "APP_SENSOR_TOWER_TIMEOUT_SECONDS",
    "APP_FEISHU_APP_ID",
    "APP_FEISHU_APP_SECRET",
)


def test_entrypoint_runs_without_integration_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    for name in _CONFIG_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.INFO):
        exit_code = main()

    assert exit_code == 0
    assert "bootstrap startup complete" in caplog.text
    assert not (tmp_path / "data" / "casual_theme_trends.duckdb").exists()
