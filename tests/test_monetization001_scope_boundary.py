"""Static boundary checks for the pure MONETIZATION-001 policy module."""

from __future__ import annotations

import ast
from pathlib import Path

PURE_MODULES = (
    Path("src/analysis/monetization_models.py"),
    Path("src/analysis/monetization_observability.py"),
)


def _module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_pure_modules_have_no_external_service_imports() -> None:
    forbidden_fragments = (
        "feishu",
        "sensor_tower.client",
        "duckdb",
        "httpx",
        "openai",
        "backtest",
        "model_v2",
        "config",
    )
    for path in PURE_MODULES:
        tree = _module_ast(path)
        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name.casefold() for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.append(node.module.casefold())
        assert not any(
            fragment in module_name
            for module_name in imported_modules
            for fragment in forbidden_fragments
        )


def test_product_policy_has_no_revenue_or_model_mapping_inputs() -> None:
    tree = _module_ast(Path("src/analysis/monetization_models.py"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "classify_product_monetization_proxy"
    )
    identifiers = {
        node.id.casefold() for node in ast.walk(function) if isinstance(node, ast.Name)
    }
    forbidden_identifiers = {
        "revenue",
        "downloads",
        "units_absolute",
        "game_product_model",
        "arpdau",
        "rpd",
        "iaa",
        "llm",
    }
    assert identifiers.isdisjoint(forbidden_identifiers)
    assert [argument.arg for argument in function.args.args] == [
        "ads_state",
        "meaningful_iap_states",
    ]


def test_pure_layer_contains_no_decision_or_recommendation_writer() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in PURE_MODULES).casefold()
    assert "decision-001" not in source
    assert "recommendation" not in source
    assert "feishuclient" not in source
