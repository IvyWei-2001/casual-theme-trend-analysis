"""CLI contracts for HIST-002 planning and completion exit behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src import cli
from src.config import AppConfig
from src.storage.errors import StorageError
from src.workflows import history_inspection
from src.workflows.history_inspection import HistoryInspectionSummary


def _summary(*, complete: bool) -> HistoryInspectionSummary:
    return HistoryInspectionSummary(
        mode="read-only",
        scope_name="casual_puzzle_tabletop",
        start_month="2026-07",
        end_month="2026-07",
        expected_month_count=1,
        expected_months=("2026-07",),
        present_month_count=1 if complete else 0,
        missing_month_count=0 if complete else 1,
        missing_months=() if complete else ("2026-07",),
        total_snapshot_count=1 if complete else 0,
        minimum_snapshot_count=1 if complete else None,
        maximum_snapshot_count=1 if complete else None,
        average_snapshot_count=1.0 if complete else None,
        provenance_variant_count=1 if complete else 0,
        expected_provenance=("WW", "total", 7012, "DM_2025_Q2"),
        structural_issue_count=0,
        structurally_complete=complete,
        month_results=(),
    )


def test_history_plan_only_bypasses_config_logging_and_duckdb(
    monkeypatch, capsys
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("must not be called during plan-only")

    monkeypatch.setattr(cli, "load_config", fail)
    monkeypatch.setattr(cli, "configure_logging", fail)
    monkeypatch.setattr(history_inspection, "DuckDBRepository", fail)
    monkeypatch.setattr(cli, "datetime", _FixedDatetime)
    monkeypatch.setattr(history_inspection, "normalize_game_genre", fail)

    import builtins
    import importlib

    from src.sensor_tower import selection as selection_module
    from src.storage import connection as connection_module

    backfill_module = importlib.import_module("src.workflows.backfill_months")

    monkeypatch.setattr(connection_module, "open_duckdb_connection", fail)
    monkeypatch.setattr(connection_module, "open_duckdb_read_only_connection", fail)
    monkeypatch.setattr(backfill_module, "SensorTowerClient", fail)
    monkeypatch.setattr(Path, "mkdir", fail)
    monkeypatch.setattr(Path, "touch", fail)
    monkeypatch.setattr(Path, "write_text", fail)
    monkeypatch.setattr(Path, "write_bytes", fail)
    monkeypatch.setattr(builtins, "open", fail)
    monkeypatch.setattr(selection_module, "select_market_records", fail)

    assert (
        cli.main(
            ["inspect-history", "--start", "2023-08", "--end", "2026-07", "--plan-only"]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "expected_month_count=36" in output
    assert "configuration=disabled" in output
    assert "file_writes=disabled" in output


@pytest.mark.parametrize("require_complete", [False, True])
def test_incomplete_history_default_and_require_complete_exit_codes(
    monkeypatch, capsys, require_complete: bool
) -> None:
    config = AppConfig(database_path=Path("unused-history.duckdb"))
    incomplete = _summary(complete=False)
    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "configure_logging", lambda _level: None)
    monkeypatch.setattr(
        cli,
        "inspect_history",
        lambda _request, _config, current_utc: incomplete,
    )

    exit_code = cli.main(
        [
            "inspect-history",
            "--start",
            "2026-07",
            "--end",
            "2026-07",
            *(["--require-complete"] if require_complete else []),
        ]
    )

    assert exit_code == (4 if require_complete else 0)
    output = capsys.readouterr().out
    assert "Historical data quality inspection:" in output
    assert "missing_month_count=1" in output


def test_complete_history_returns_zero(monkeypatch, capsys) -> None:
    config = AppConfig(database_path=Path("unused-history.duckdb"))
    complete = _summary(complete=True)
    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "configure_logging", lambda _level: None)
    monkeypatch.setattr(
        cli,
        "inspect_history",
        lambda _request, _config, current_utc: complete,
    )

    assert cli.main(
        ["inspect-history", "--start", "2026-07", "--end", "2026-07", "--require-complete"]
    ) == 0
    assert "structurally_complete=true" in capsys.readouterr().out


def test_invalid_range_returns_two_without_loading_configuration(monkeypatch, capsys) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("configuration must be bypassed")

    monkeypatch.setattr(cli, "load_config", fail)
    monkeypatch.setattr(cli, "configure_logging", fail)
    monkeypatch.setattr(cli, "datetime", _FixedDatetime)

    assert cli.main(
        ["inspect-history", "--start", "2027-01", "--end", "2026-07", "--plan-only"]
    ) == 2
    assert "future" in capsys.readouterr().err


def test_storage_failure_returns_four_without_leaking_error_details(monkeypatch, capsys) -> None:
    config = AppConfig(database_path=Path("unused-history.duckdb"))
    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "configure_logging", lambda _level: None)
    monkeypatch.setattr(
        cli,
        "inspect_history",
        lambda _request, _config, current_utc: (_ for _ in ()).throw(
            StorageError(
                "synthetic-unified-id Synthetic App Synthetic Publisher "
                "https://user:password@example.test/token"
            )
        ),
    )

    assert cli.main(
        ["inspect-history", "--start", "2026-07", "--end", "2026-07"]
    ) == 4
    error = capsys.readouterr().err
    assert error == "error: local read-only history inspection failed\n"


def test_history_error_path_sanitizes_workflow_details(monkeypatch, capsys) -> None:
    config = AppConfig(database_path=Path("unused-history.duckdb"))
    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "configure_logging", lambda _level: None)
    monkeypatch.setattr(
        cli,
        "inspect_history",
        lambda _request, _config, current_utc: (_ for _ in ()).throw(
            history_inspection.WorkflowError("Synthetic App Synthetic Publisher")
        ),
    )

    assert cli.main(
        ["inspect-history", "--start", "2026-07", "--end", "2026-07"]
    ) == 2
    assert capsys.readouterr().err == "error: invalid history inspection request\n"


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz: object = None) -> datetime:
        assert tz is UTC
        return datetime(2026, 8, 12, tzinfo=UTC)
