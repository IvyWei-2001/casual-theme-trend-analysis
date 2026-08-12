"""Focused consistency checks for the CONTRACT-002 documentation set."""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AUTHORITATIVE_DOCUMENTS = (
    "docs/BUSINESS_DECISION_CONTRACT.md",
    "docs/API_MAPPING.md",
    "docs/DATA_MODEL.md",
    "docs/TREND_SCORE.md",
    "docs/PRD.md",
    "docs/CURRENT_SYSTEM.md",
    "PROJECT_PLAN.md",
)
V2_ISSUES = (
    "CONTRACT-002",
    "HIST-002",
    "AGG-002",
    "MODEL-002",
    "BACKTEST-001",
    "DECISION-001",
    "FEISHU-004",
    "AUTOMATION-001",
)


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_authoritative_business_contract_contains_required_v2_terms() -> None:
    contract_path = REPOSITORY_ROOT / "docs/BUSINESS_DECISION_CONTRACT.md"
    assert contract_path.is_file()

    contract = contract_path.read_text(encoding="utf-8")
    lowered = contract.lower()
    required_dimensions = (
        "market size",
        "growth quality",
        "competitive white space",
        "launch window",
        "category fit and migration potential",
        "risk and confidence",
    )
    for dimension in required_dimensions:
        assert dimension in lowered

    required_terms = (
        "units_absolute",
        "downloads",
        "revenue_absolute",
        "revenue (usd)",
        "36 consecutive completed natural months",
        "t+1",
        "t+2",
        "t+3",
        "theme opportunity overview",
    )
    for term in required_terms:
        assert term in lowered


def test_project_plan_contains_the_authoritative_v2_order() -> None:
    project_plan = _read("PROJECT_PLAN.md")
    positions = [project_plan.index(issue) for issue in V2_ISSUES]
    assert positions == sorted(positions)
    assert not re.search(
        r"current focus.{0,100}(?:phase\s*1|inf-001)",
        project_plan,
        flags=re.IGNORECASE | re.DOTALL,
    )


def test_current_system_no_longer_describes_the_original_empty_scaffold() -> None:
    current_system = _read("docs/CURRENT_SYSTEM.md").lower()
    assert "no python package" not in current_system
    assert "no feishu integration" not in current_system
    assert "duckdb" in current_system
    assert "idempotent" in current_system


def test_authoritative_docs_do_not_reintroduce_resolved_metric_contradictions() -> None:
    authoritative_text = "\n".join(
        _read(relative_path).lower() for relative_path in AUTHORITATIVE_DOCUMENTS
    )
    forbidden_contradictions = (
        "their business semantics remain unresolved",
        "their business semantics remain source-contract todos",
        "these source names and their business semantics remain unresolved",
        "source metric semantics remain todo",
        "source fields retain their exact names and unresolved semantics",
        "are not renamed to downloads",
        "are not renamed to revenue",
        "not changed into downloads",
        "not changed into revenue",
        "whether any observed `*_units_*` field represents downloads",
    )
    for contradiction in forbidden_contradictions:
        assert contradiction not in authoritative_text
