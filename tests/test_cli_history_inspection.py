"""CLI contracts for HIST-002 planning and completion exit behavior."""

from __future__ import annotations

from datetime import UTC, datetime

from src import cli
from src.workflows import history_inspection


def test_history_plan_only_bypasses_config_logging_and_duckdb(
    monkeypatch, capsys
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("must not be called during plan-only")

    monkeypatch.setattr(cli, "load_config", fail)
    monkeypatch.setattr(cli, "configure_logging", fail)
    monkeypatch.setattr(history_inspection, "DuckDBRepository", fail)
    monkeypatch.setattr(cli, "datetime", _FixedDatetime)

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


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz: object = None) -> datetime:
        assert tz is UTC
        return datetime(2026, 8, 12, tzinfo=UTC)
