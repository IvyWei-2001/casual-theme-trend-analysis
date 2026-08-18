"""Static boundary checks for the offline MONETIZATION-001 implementation."""

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
        "sensor_tower",
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


def test_proxy_accepts_only_observable_revenue_and_has_no_model_input() -> None:
    tree = _module_ast(Path("src/analysis/monetization_models.py"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "classify_observable_revenue"
    )
    identifiers = {
        node.id.casefold() for node in ast.walk(function) if isinstance(node, ast.Name)
    }
    forbidden_identifiers = {
        "downloads",
        "units_absolute",
        "game_product_model",
        "arpdau",
        "rpd",
        "iaa",
        "llm",
        "custom_tags",
    }
    assert identifiers.isdisjoint(forbidden_identifiers)
    assert [argument.arg for argument in function.args.args] == ["revenue_absolute"]


def test_cli_has_offline_range_command_and_no_network_monetization_command() -> None:
    source = Path("src/cli.py").read_text(encoding="utf-8")
    assert '"derive-monetization"' in source
    assert '"collect-monetization"' not in source
    assert "SensorTowerClient" not in Path(
        "src/workflows/derive_monetization.py"
    ).read_text(encoding="utf-8")
