"""CLI boundary tests for DB-002 with no real credentials or network."""

from __future__ import annotations

from pathlib import Path

from src.__main__ import main

_ENVIRONMENT_NAMES = (
    "APP_CONFIG_FILE",
    "APP_DATABASE_PATH",
    "APP_EXPORT_DIRECTORY",
    "APP_METADATA_CACHE_MAX_AGE_DAYS",
    "APP_SENSOR_TOWER_AUTH_TOKEN",
)


def _clear_environment(monkeypatch: object) -> None:
    for name in _ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)  # type: ignore[attr-defined]


def test_plan_only_needs_no_token_and_creates_no_local_files(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    exit_code = main(["collect-month", "--month", "2026-07", "--plan-only"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "period_start=2026-07-01" in captured.out
    assert "period_end=2026-07-31" in captured.out
    assert "network=disabled" in captured.out
    assert not (tmp_path / "data" / "casual_theme_trends.duckdb").exists()
    assert not (tmp_path / "data" / "exports").exists()


def test_real_collection_without_token_fails_before_network_or_database(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    exit_code = main(["collect-month", "--month", "2026-07"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "APP_SENSOR_TOWER_AUTH_TOKEN is not configured" in captured.err
    assert not (tmp_path / "data" / "casual_theme_trends.duckdb").exists()
