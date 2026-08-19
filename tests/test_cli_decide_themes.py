"""Focused CLI contract tests for DECISION-001."""

from __future__ import annotations

import os
from pathlib import Path

from src.__main__ import main
from src.config import AppConfig
from src.workflows.errors import DecisionThemesError


def _clear_environment(monkeypatch) -> None:
    for name in tuple(os.environ):
        if name.startswith("APP_"):
            monkeypatch.delenv(name, raising=False)


def test_valid_plan_only_runs_before_configuration_logging_and_files(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)

    def fail_config() -> AppConfig:
        raise AssertionError("configuration must not load")

    monkeypatch.setattr("src.cli.load_config", fail_config)
    monkeypatch.setattr(
        "src.cli.configure_logging",
        lambda _level: (_ for _ in ()).throw(AssertionError("logging must not initialize")),
    )
    assert main(["decide-themes", "--month", "2026-07", "--plan-only"]) == 0
    output = capsys.readouterr().out
    assert "decision_policy_version=DECISION001_V1" in output
    assert "configuration=disabled" in output
    assert "database=disabled" in output
    assert "file_writes=disabled" in output
    assert not (tmp_path / "data").exists()


def test_invalid_current_and_future_months_are_argument_errors(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)
    for month in ("2026-08", "2026-09", "2026-7"):
        assert main(["decide-themes", "--month", month, "--plan-only"]) == 2
        assert "error:" in capsys.readouterr().err
    assert not (tmp_path / "data").exists()


def test_normal_cli_routes_to_workflow_and_honors_skip_export(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    config = AppConfig(
        database_path=tmp_path / "decision.duckdb",
        export_directory=tmp_path / "exports",
    )
    captured: dict[str, object] = {}

    def fake_workflow(request, passed_config, **kwargs):
        captured["request"] = request
        captured["config"] = passed_config
        return object()

    monkeypatch.setattr("src.cli.load_config", lambda: config)
    monkeypatch.setattr("src.cli.configure_logging", lambda _level: None)
    monkeypatch.setattr("src.cli.run_theme_decision_workflow", fake_workflow)
    monkeypatch.setattr(
        "src.cli.format_decide_themes_summary",
        lambda _summary: "sanitized decision summary",
    )
    assert main([
        "decide-themes",
        "--month",
        "2026-07",
        "--skip-export",
    ]) == 0
    assert "sanitized decision summary" in capsys.readouterr().out
    request = captured["request"]
    assert request.month == "2026-07"
    assert request.skip_export is True
    assert captured["config"] is config


def test_cli_sanitizes_unexpected_workflow_failure(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    _clear_environment(monkeypatch)
    config = AppConfig(
        database_path=tmp_path / "decision.duckdb",
        export_directory=tmp_path / "exports",
    )
    monkeypatch.setattr("src.cli.load_config", lambda: config)
    monkeypatch.setattr("src.cli.configure_logging", lambda _level: None)
    monkeypatch.setattr(
        "src.cli.run_theme_decision_workflow",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            DecisionThemesError("app_id=secret source token")
        ),
    )
    assert main(["decide-themes", "--month", "2026-07"]) == 4
    error_output = capsys.readouterr().err
    assert "DECISION-001 workflow failed" in error_output
    assert "app_id=secret" not in error_output
    assert "source token" not in error_output
