"""CLI tests for HIST-001 that never access a live integration."""

from __future__ import annotations

import os
from pathlib import Path

from src.__main__ import main


def _clear_app_environment(monkeypatch) -> None:
    for name in tuple(os.environ):
        if name.startswith("APP_"):
            monkeypatch.delenv(name, raising=False)


def test_plan_only_cli_validates_range_without_token_database_or_parquet(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_app_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "backfill-months",
            "--start",
            "2026-06",
            "--end",
            "2026-07",
            "--plan-only",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "start_month=2026-06" in captured.out
    assert "end_month=2026-07" in captured.out
    assert "planned_month_count=2" in captured.out
    assert "month_sequence=2026-06,2026-07" in captured.out
    assert "token" not in captured.out.lower()
    assert "app-" not in captured.out
    assert not (tmp_path / "data" / "casual_theme_trends.duckdb").exists()
    assert not (tmp_path / "data" / "exports").exists()


def test_invalid_backfill_range_returns_argument_exit_code(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_app_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "backfill-months",
            "--start",
            "2026-08",
            "--end",
            "2026-09",
            "--plan-only",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "current incomplete" in captured.err or "future" in captured.err
