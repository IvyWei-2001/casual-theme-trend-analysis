"""CLI tests for MODEL-002 with configuration and network boundaries."""

from __future__ import annotations

import os
from pathlib import Path

from test_storage_model002 import _payload, _store_agg002

from src.__main__ import main
from src.storage import DuckDBRepository


def _clear_environment(monkeypatch) -> None:
    for name in tuple(os.environ):
        if name.startswith("APP_"):
            monkeypatch.delenv(name, raising=False)


def test_plan_only_runs_before_configuration_and_writes_nothing(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    monkeypatch.setenv("APP_FEISHU_API_BASE_URL", "not a URL")
    monkeypatch.setenv("APP_SENSOR_TOWER_AUTH_TOKEN", "synthetic-token")
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "model-themes",
            "--start",
            "2023-08",
            "--end",
            "2026-07",
            "--plan-only",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "history_month_count=36" in captured.out
    assert "horizon_6m_target_month_count=31" in captured.out
    assert "horizon_12m_target_month_count=25" in captured.out
    assert "horizon_36m_target_month_count=1" in captured.out
    assert "seasonality_target_month_count=13" in captured.out
    assert "database=disabled" in captured.out
    assert "file_writes=disabled" in captured.out
    assert "synthetic-token" not in captured.out
    assert not (tmp_path / "data" / "casual_theme_trends.duckdb").exists()
    assert not (tmp_path / "data" / "exports").exists()


def test_complete_cli_can_skip_exports_without_network_or_raw_values(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    database_path = tmp_path / "data" / "model.duckdb"
    export_directory = tmp_path / "exports"
    monkeypatch.setenv("APP_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("APP_EXPORT_DIRECTORY", str(export_directory))
    repository = DuckDBRepository(database_path)
    repository.open()
    repository.initialize_schema()
    _store_agg002(repository, _payload())
    repository.close()

    exit_code = main(
        [
            "model-themes",
            "--start",
            "2023-08",
            "--end",
            "2026-07",
            "--skip-export",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "source_market_structure_row_count=36" in captured.out
    assert "legacy_6m_score_row_count=31" in captured.out
    assert "horizon_metric_row_count=342" in captured.out
    assert "model_summary_row_count=36" in captured.out
    assert "seasonality_profile_row_count=936" in captured.out
    assert "verification=passed" in captured.out
    assert "parquet_export=skipped" in captured.out
    assert "game_theme=" not in captured.out
    assert "app-" not in captured.out
    assert not export_directory.exists()


def test_invalid_model_range_returns_configuration_exit_code(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert main(
        [
            "model-themes",
            "--start",
            "2026-07",
            "--end",
            "2023-08",
            "--plan-only",
        ]
    ) == 2
    assert "error:" in capsys.readouterr().err
