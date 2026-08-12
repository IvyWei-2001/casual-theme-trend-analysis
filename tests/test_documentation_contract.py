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
    assert "on the contract-002 branch" not in current_system
    assert "technical and quality fields remain visible" not in current_system
    assert "duckdb" in current_system
    assert "idempotent" in current_system


def test_authoritative_docs_use_bounded_selected_top_n_sample_wording() -> None:
    authoritative_text = "\n".join(
        _read(relative_path).lower() for relative_path in AUTHORITATIVE_DOCUMENTS
    )
    assert "selected top-n sample" in authoritative_text
    assert "cap 1000" in authoritative_text
    assert "final top 1000 sample" not in authoritative_text
    assert "selected top 1000 sample" not in authoritative_text


def test_competitive_white_space_requires_new_entry_evidence() -> None:
    contract = _read("docs/BUSINESS_DECISION_CONTRACT.md")
    section_match = re.search(
        r"(?ms)^### 2\.3 Is there competitive room for a new product\?.*?^### 2\.4 ",
        contract,
    )
    assert section_match is not None
    section = section_match.group(0).lower()

    required_evidence = (
        ("new-entry", "new entrant"),
        ("success rate",),
        ("downloads share",),
        ("revenue (usd) share",),
        ("top 100", "top 500"),
        ("turnover",),
        ("incumbent", "product age"),
        ("established products",),
        ("break the existing structure",),
    )
    for alternatives in required_evidence:
        assert any(term in section for term in alternatives)


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
        "final top 1000 sample",
        "selected top 1000 sample",
    )
    for contradiction in forbidden_contradictions:
        assert contradiction not in authoritative_text
