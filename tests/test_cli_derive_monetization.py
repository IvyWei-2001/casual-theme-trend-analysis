"""Plan-only CLI isolation tests for offline MONETIZATION-001."""

from __future__ import annotations

from src import cli


def test_derive_monetization_plan_only_bypasses_config_and_logging(
    monkeypatch,
    capsys,
) -> None:
    def fail_config() -> object:
        raise AssertionError("plan-only must not load configuration")

    def fail_logging(_: object) -> None:
        raise AssertionError("plan-only must not configure logging")

    monkeypatch.setattr(cli, "load_config", fail_config)
    monkeypatch.setattr(cli, "configure_logging", fail_logging)

    assert cli.main(
        [
            "derive-monetization",
            "--start",
            "2023-08",
            "--end",
            "2026-07",
            "--plan-only",
        ]
    ) == 0
    assert capsys.readouterr().out == (
        "Monetization derivation plan:\n"
        "mode=plan-only\n"
        "start_month=2023-08\n"
        "end_month=2026-07\n"
        "planned_month_count=36\n"
        "policy_version=MONETIZATION001_OBSERVABLE_REVENUE_PROXY_V1\n"
        "source=stored_market_snapshots_only\n"
        "historical_custom_fields=disabled\n"
        "network=disabled\n"
        "database=disabled\n"
        "file_writes=disabled\n"
    )
