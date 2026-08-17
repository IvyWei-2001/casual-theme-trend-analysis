"""Plan-only CLI isolation tests for MONETIZATION-001."""

from __future__ import annotations

from src import cli


def test_collect_monetization_plan_only_bypasses_config_and_logging(
    monkeypatch,
    capsys,
) -> None:
    def fail_config() -> object:
        raise AssertionError("plan-only must not load configuration")

    def fail_logging(_: object) -> None:
        raise AssertionError("plan-only must not configure logging")

    monkeypatch.setattr(cli, "load_config", fail_config)
    monkeypatch.setattr(cli, "configure_logging", fail_logging)

    assert cli.main(["collect-monetization", "--month", "2026-07", "--plan-only"]) == 0
    assert capsys.readouterr().out == (
        "Monetization observability plan:\n"
        "mode=plan-only\n"
        "month=2026-07\n"
        "policy_version=MONETIZATION001_V1\n"
        "verified_tag_count=11\n"
        "meaningful_iap_tag_count=7\n"
        "new_outputs=app_monetization_profiles,theme_monetization_observability_metrics\n"
        "historical_backfill=disabled\n"
        "network=disabled\n"
        "database=disabled\n"
        "file_writes=disabled\n"
    )
