"""CLI tests for BACKTEST-001 configuration and no-network boundaries."""

from __future__ import annotations

import os
from pathlib import Path

from test_storage_model002 import _payload, _store_agg002, _store_model

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
            "backtest-themes",
            "--start",
            "2023-08",
            "--end",
            "2026-07",
            "--plan-only",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "legacy_6m_decision_month_count_t1=30" in captured.out
    assert "legacy_6m_decision_month_count_t2=29" in captured.out
    assert "legacy_6m_decision_month_count_t3=28" in captured.out
    assert "model_12m_decision_month_count_t1=24" in captured.out
    assert "model_36m_decision_month_count_t1=0" in captured.out
    assert "seasonality_decision_month_count_t1=12" in captured.out
    assert "feature_definition_count=19" in captured.out
    assert "primary_outcome_count=4" in captured.out
    assert "planned_feature_metric_row_count=228" in captured.out
    assert "database=disabled" in captured.out
    assert "file_writes=disabled" in captured.out
    assert "synthetic-token" not in captured.out
    assert not (tmp_path / "data" / "casual_theme_trends.duckdb").exists()


def test_complete_cli_can_skip_exports_without_external_requests(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    database_path = tmp_path / "data" / "backtest.duckdb"
    export_directory = tmp_path / "exports"
    monkeypatch.setenv("APP_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("APP_EXPORT_DIRECTORY", str(export_directory))

    repository = DuckDBRepository(database_path)
    repository.open()
    repository.initialize_schema()
    payload = _payload()
    _store_agg002(repository, payload)
    _store_model(repository, payload, calculated_at=payload.monthly_totals[0].calculated_at)
    repository.close()

    exit_code = main(
        [
            "backtest-themes",
            "--start",
            "2023-08",
            "--end",
            "2026-07",
            "--skip-export",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "source_model_summary_row_count=36" in captured.out
    assert "source_legacy_6m_score_row_count=31" in captured.out
    assert "outcome_row_count=87" in captured.out
    assert "feature_metric_row_count=228" in captured.out
    assert "verification=passed" in captured.out
    assert "parquet_export=skipped" in captured.out
    assert "game_theme=" not in captured.out
    assert "app-" not in captured.out
    assert not export_directory.exists()


def test_invalid_backtest_range_returns_configuration_exit_code(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    assert (
        main(
            [
                "backtest-themes",
                "--start",
                "2026-07",
                "--end",
                "2023-08",
                "--plan-only",
            ]
        )
        == 2
    )
    assert "error:" in capsys.readouterr().err
