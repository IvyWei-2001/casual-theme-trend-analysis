"""CLI tests for AGG-001 with no network or developer database access."""

from __future__ import annotations

import os
from pathlib import Path

from src.__main__ import main


def _clear_environment(monkeypatch) -> None:
    for name in tuple(os.environ):
        if name.startswith("APP_"):
            monkeypatch.delenv(name, raising=False)


def test_plan_only_needs_no_token_database_or_output_files(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "aggregate-themes",
            "--start",
            "2025-08",
            "--end",
            "2026-07",
            "--plan-only",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "planned_month_count=12" in captured.out
    assert "month_sequence=2025-08" in captured.out
    assert "2026-07" in captured.out
    assert "network=disabled" in captured.out
    assert "v2_outputs=theme_market_structure_metrics" in captured.out
    assert "token" not in captured.out.lower()
    assert not (tmp_path / "data" / "casual_theme_trends.duckdb").exists()
    assert not (tmp_path / "data" / "exports").exists()


def test_malformed_or_current_range_returns_argument_error(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "aggregate-themes",
            "--start",
            "2026-8",
            "--end",
            "2026-09",
            "--plan-only",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "YYYY-MM" in captured.err
