"""Tests for typed local configuration loading."""

from pathlib import Path

import pytest

from src.config import DEFAULT_DATABASE_PATH, load_config

_CONFIG_ENVIRONMENT_NAMES = (
    "APP_APP_NAME",
    "APP_ENVIRONMENT",
    "APP_DATABASE_PATH",
    "APP_LOG_LEVEL",
    "APP_CONFIG_FILE",
    "APP_SENSOR_TOWER_API_URL",
    "APP_SENSOR_TOWER_AUTH_TOKEN",
    "APP_SENSOR_TOWER_API_LIMIT",
    "APP_SENSOR_TOWER_FINAL_TOP_N",
    "APP_SENSOR_TOWER_ALLOWED_GENRES",
    "APP_SENSOR_TOWER_EXCLUDE_CHINA_REVENUE_MARKET",
    "APP_SENSOR_TOWER_SCOPE_NAME",
    "APP_SENSOR_TOWER_TIMEOUT_SECONDS",
    "APP_FEISHU_APP_ID",
    "APP_FEISHU_APP_SECRET",
)


def _clear_config_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _CONFIG_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_default_config_loads_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_config_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    config = load_config()

    assert config.environment == "development"
    assert config.database_path == DEFAULT_DATABASE_PATH
    assert config.sensor_tower_api_url is None
    assert config.sensor_tower_auth_token is None
    assert config.feishu_app_id is None
    assert config.feishu_app_secret is None
    assert not (tmp_path / DEFAULT_DATABASE_PATH).exists()


def test_yaml_config_can_load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_config_environment(monkeypatch)
    config_file = tmp_path / "app.yaml"
    config_file.write_text(
        "app_name: yaml-test\n"
        "environment: test\n"
        "database_path: data/yaml.duckdb\n"
        "log_level: WARNING\n",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.app_name == "yaml-test"
    assert config.environment == "test"
    assert config.database_path == Path("data/yaml.duckdb")
    assert config.log_level == "WARNING"


def test_environment_variables_override_yaml(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_config_environment(monkeypatch)
    config_file = tmp_path / "app.yaml"
    config_file.write_text(
        "database_path: data/from-yaml.duckdb\nlog_level: WARNING\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_DATABASE_PATH", "data/from-env.duckdb")
    monkeypatch.setenv("APP_LOG_LEVEL", "DEBUG")

    config = load_config(config_file)

    assert config.database_path == Path("data/from-env.duckdb")
    assert config.log_level == "DEBUG"


def test_local_dotenv_settings_are_loaded_without_exposing_the_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_config_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)
    token = "local-dotenv-token"
    (tmp_path / ".env").write_text(
        "APP_SENSOR_TOWER_AUTH_TOKEN=local-dotenv-token\n"
        "APP_SENSOR_TOWER_API_LIMIT=1200\n"
        "APP_SENSOR_TOWER_FINAL_TOP_N=1000\n"
        "APP_SENSOR_TOWER_ALLOWED_GENRES=[\"Puzzle\",\"Tabletop\"]\n",
        encoding="utf-8",
    )

    config = load_config()

    assert config.sensor_tower_auth_token is not None
    assert config.sensor_tower_auth_token.get_secret_value() == token
    assert token not in repr(config)
