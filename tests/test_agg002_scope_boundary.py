"""Static scope-boundary checks for the AGG-002 implementation."""

from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AGGREGATION_FILES = (
    REPOSITORY_ROOT / "src" / "analysis" / "opportunity_aggregation.py",
    REPOSITORY_ROOT / "src" / "workflows" / "aggregate_themes.py",
)
FORBIDDEN_FRAGMENTS = (
    "SensorTowerClient",
    "FeishuClient",
    "httpx.Client",
    "requests",
    "score_themes",
    "sync_feishu_trends",
    "view/dashboard",
)


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def test_agg002_analysis_and_workflow_have_no_external_scope_dependencies() -> None:
    for path in AGGREGATION_FILES:
        source = path.read_text(encoding="utf-8")
        lowered_source = source.lower()
        assert not any(fragment.lower() in lowered_source for fragment in FORBIDDEN_FRAGMENTS)
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called_name = _dotted_name(node.func)
                assert called_name not in {
                    "SensorTowerClient",
                    "FeishuClient",
                    "httpx.Client",
                }
