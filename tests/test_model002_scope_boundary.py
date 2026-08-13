"""Static boundary checks for the pure MODEL-002 calculation layer."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_model_calculation_has_no_external_or_storage_dependencies() -> None:
    pure_files = (
        REPOSITORY_ROOT / "src" / "analysis" / "model_v2.py",
        REPOSITORY_ROOT / "src" / "analysis" / "model_v2_models.py",
    )
    forbidden_fragments = (
        "duckdb",
        "SensorTowerClient",
        "FeishuClient",
        "httpx",
        "requests",
        "AppConfig",
        "load_config",
        "open_duckdb",
    )
    for path in pure_files:
        source = path.read_text(encoding="utf-8").lower()
        assert not any(fragment.lower() in source for fragment in forbidden_fragments)


def test_model_workflow_does_not_call_collection_aggregation_or_sync() -> None:
    source = (REPOSITORY_ROOT / "src" / "workflows" / "model_themes.py").read_text(
        encoding="utf-8"
    ).lower()
    forbidden_fragments = (
        "sensortowerclient",
        "feishuclient",
        "httpx",
        "requests",
        "collect_month",
        "aggregate_themes",
        "backfill_months",
        "sync_feishu_trends",
    )
    assert not any(fragment in source for fragment in forbidden_fragments)
