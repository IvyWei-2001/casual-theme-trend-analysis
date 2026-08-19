"""Focused stored-evidence DECISION-001 workflow tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from test_analysis_decision_v1 import (
    SCOPE,
    TARGET_MONTH,
    _aggregate,
    _period_end,
    _summary,
)

from src.analysis.decision_v1 import calculate_theme_decisions as real_calculate
from src.config import AppConfig
from src.storage import DuckDBRepository, SnapshotPeriodKey
from src.workflows.decision_themes import (
    format_decide_themes_summary,
    run_theme_decision_workflow,
)
from src.workflows.errors import DecisionReadbackVerificationError, DecisionThemesError
from src.workflows.models import DecideThemesRequest

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


class EvidenceRepository:
    """Synthetic repository double with no external-system boundary."""

    def __init__(self, *, subgenres: dict[str, str | None] | None = None) -> None:
        self.total, self.structures, self.aggregate = _aggregate(
            ("Theme",),
            subgenres=subgenres,
        )
        self.summaries = (_summary("Theme"),)
        self.result = None
        self.calls: list[tuple[str, object]] = []
        self.export_calls: list[Path] = []
        self.future_dimension = False
        self.future_representative = False

    def open(self) -> object:
        self.calls.append(("open", None))
        return self

    def initialize_schema(self) -> None:
        self.calls.append(("initialize_schema", None))

    def close(self) -> None:
        self.calls.append(("close", None))

    def get_monthly_market_totals(self, **kwargs: object) -> list[object]:
        self.calls.append(("monthly_total", kwargs))
        return [self.total]

    def get_theme_market_structure_metrics(self, **kwargs: object) -> list[object]:
        self.calls.append(("market_structure", kwargs))
        return [row for row in self.structures if row.period_start == TARGET_MONTH]

    def get_theme_growth_source_metrics(self, **kwargs: object) -> list[object]:
        self.calls.append(("growth_source", kwargs))
        return [
            row
            for row in self.aggregate.theme_growth_source_metrics
            if row.period_start == TARGET_MONTH
        ]

    def get_theme_trend_scores(self, **kwargs: object) -> list[object]:
        self.calls.append(("trend_score", kwargs))
        return []

    def get_theme_model_summaries(self, **kwargs: object) -> list[object]:
        self.calls.append(("model_summary", kwargs))
        return list(self.summaries)

    def get_theme_dimension_monthly_metrics(self, **kwargs: object) -> list[object]:
        self.calls.append(("dimension", kwargs))
        rows = [
            row
            for row in self.aggregate.theme_dimension_monthly_metrics
            if row.period_start >= kwargs["period_start"]
            and row.period_end <= kwargs["period_end"]
        ]
        if self.future_dimension and rows:
            rows.append(
                replace(
                    rows[-1],
                    period_start=date(2026, 8, 1),
                    period_end=date(2026, 8, 31),
                )
            )
        return rows

    def get_theme_representative_games(self, **kwargs: object) -> list[object]:
        self.calls.append(("representative", kwargs))
        rows = [
            row
            for row in self.aggregate.theme_representative_games
            if row.period_start >= kwargs["period_start"]
            and row.period_end <= kwargs["period_end"]
        ]
        if self.future_representative and rows:
            rows.append(
                replace(
                    rows[-1],
                    period_start=date(2026, 8, 1),
                    period_end=date(2026, 8, 31),
                )
            )
        return rows

    def get_theme_monetization_observability_metrics(self, **kwargs: object) -> list[object]:
        self.calls.append(("monetization", kwargs))
        return []

    def replace_theme_decision_result(self, result: object, **kwargs: object) -> None:
        self.calls.append(("replace", kwargs))
        self.result = result

    def get_theme_decision_summaries(self, **kwargs: object) -> list[object]:
        self.calls.append(("decision_summaries", kwargs))
        return [] if self.result is None else list(self.result.decision_summaries)

    def get_theme_launch_window_assessments(self, **kwargs: object) -> list[object]:
        self.calls.append(("launch_windows", kwargs))
        return [] if self.result is None else list(self.result.launch_window_assessments)

    def get_theme_decision_risks(self, **kwargs: object) -> list[object]:
        self.calls.append(("risks", kwargs))
        return [] if self.result is None else list(self.result.decision_risks)

    def get_theme_category_fit_assessments(self, **kwargs: object) -> list[object]:
        self.calls.append(("category_fits", kwargs))
        return [] if self.result is None else list(self.result.category_fit_assessments)

    def get_theme_migration_hypotheses(self, **kwargs: object) -> list[object]:
        self.calls.append(("migrations", kwargs))
        return [] if self.result is None else list(self.result.migration_hypotheses)

    def _export(self, path: Path) -> None:
        self.export_calls.append(path)

    export_theme_decision_summaries_to_parquet = _export
    export_theme_launch_window_assessments_to_parquet = _export
    export_theme_decision_risks_to_parquet = _export
    export_theme_category_fit_assessments_to_parquet = _export
    export_theme_migration_hypotheses_to_parquet = _export


def _request(
    tmp_path: Path,
    *,
    skip_export: bool = False,
    plan_only: bool = False,
) -> DecideThemesRequest:
    return DecideThemesRequest(
        month="2026-07",
        database_path=tmp_path / "decision.duckdb",
        export_directory=tmp_path / "exports",
        skip_export=skip_export,
        plan_only=plan_only,
    )


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        sensor_tower_scope_name=SCOPE,
        database_path=tmp_path / "decision.duckdb",
        export_directory=tmp_path / "exports",
    )


def test_complete_synthetic_workflow_persists_and_exports_with_temp_duckdb(
    tmp_path: Path,
) -> None:
    total, structures, aggregate = _aggregate(("Theme",))
    database_path = tmp_path / "decision.duckdb"
    repository = DuckDBRepository(database_path)
    repository.open()
    repository.initialize_schema()
    repository.replace_theme_opportunity_range(
        aggregate.monthly_totals,
        aggregate.theme_metrics,
        aggregate.theme_market_structure_metrics,
        aggregate.theme_growth_source_metrics,
        aggregate.theme_dimension_monthly_metrics,
        aggregate.theme_representative_games,
    )
    key = SnapshotPeriodKey(SCOPE, "monthly", TARGET_MONTH, _period_end(TARGET_MONTH))
    repository.replace_theme_model_range(
        (),
        (),
        (_summary("Theme"),),
        (),
        target_periods=(key,),
    )
    summary = run_theme_decision_workflow(
        _request(tmp_path),
        _config(tmp_path),
        current_utc=NOW,
        repository=repository,
    )
    assert summary.verification == "passed"
    assert summary.summary_row_count == 1
    assert summary.launch_window_row_count == 3
    assert summary.recommendation_distribution == (("selective_validation", 1),)
    assert all(path is not None and path.is_file() for path in (
        summary.summaries_parquet_path,
        summary.launch_windows_parquet_path,
        summary.risks_parquet_path,
        summary.category_fits_parquet_path,
        summary.migrations_parquet_path,
    ))
    stored_summary = repository.get_theme_decision_summaries()[0]
    stored_launches = repository.get_theme_launch_window_assessments()
    assert len(stored_launches) == 3
    assert {
        row.source_policy_references for row in stored_launches
    } == {stored_summary.source_policy_references}
    assert total.period_start == TARGET_MONTH
    assert structures
    repository.close()


def test_workflow_ignores_historical_only_trailing_evidence(tmp_path: Path) -> None:
    total, structures, aggregate = _aggregate(
        ("Theme",),
        subgenres={"Theme": "Validated"},
    )
    historical_dimension_source = next(
        row
        for row in aggregate.theme_dimension_monthly_metrics
        if row.period_start == TARGET_MONTH
    )
    historical_dimension = replace(
        historical_dimension_source,
        game_theme="Historical Only",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )
    historical_theme_metric = replace(
        next(
            row
            for row in aggregate.theme_metrics
            if row.period_start == date(2026, 6, 1)
        ),
        game_theme="Historical Only",
    )
    historical_structure = replace(
        next(
            row
            for row in aggregate.theme_market_structure_metrics
            if row.period_start == date(2026, 6, 1)
        ),
        game_theme="Historical Only",
    )
    historical_growth = replace(
        next(
            row
            for row in aggregate.theme_growth_source_metrics
            if row.period_start == date(2026, 6, 1)
        ),
        game_theme="Historical Only",
    )
    historical_representative_source = next(
        row
        for row in aggregate.theme_representative_games
        if row.period_start == TARGET_MONTH
    )
    historical_representative = replace(
        historical_representative_source,
        game_theme="Historical Only",
        source_app_id="historical-source-app",
        unified_app_id="historical-unified-app",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
    )
    database_path = tmp_path / "decision.duckdb"
    repository = DuckDBRepository(database_path)
    repository.open()
    repository.initialize_schema()
    repository.replace_theme_opportunity_range(
        aggregate.monthly_totals,
        (*aggregate.theme_metrics, historical_theme_metric),
        (*aggregate.theme_market_structure_metrics, historical_structure),
        (*aggregate.theme_growth_source_metrics, historical_growth),
        (*aggregate.theme_dimension_monthly_metrics, historical_dimension),
        (*aggregate.theme_representative_games, historical_representative),
    )
    key = SnapshotPeriodKey(SCOPE, "monthly", TARGET_MONTH, _period_end(TARGET_MONTH))
    repository.replace_theme_model_range(
        (),
        (),
        (_summary("Theme"),),
        (),
        target_periods=(key,),
    )
    summary = run_theme_decision_workflow(
        _request(tmp_path),
        _config(tmp_path),
        current_utc=NOW,
        repository=repository,
    )
    assert summary.verification == "passed"
    assert summary.summary_row_count == 1
    assert summary.launch_window_row_count == 3
    stored_rows = (
        *repository.get_theme_decision_summaries(),
        *repository.get_theme_launch_window_assessments(),
        *repository.get_theme_decision_risks(),
        *repository.get_theme_category_fit_assessments(),
        *repository.get_theme_migration_hypotheses(),
    )
    assert all(row.game_theme != "Historical Only" for row in stored_rows)
    assert all(
        path is not None and path.is_file()
        for path in (
            summary.summaries_parquet_path,
            summary.launch_windows_parquet_path,
            summary.risks_parquet_path,
            summary.category_fits_parquet_path,
            summary.migrations_parquet_path,
        )
    )
    assert total.period_start == TARGET_MONTH
    assert structures
    repository.close()


def test_workflow_calls_pure_calculation_once_and_uses_no_future_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = EvidenceRepository(subgenres={"Theme": "Validated"})
    calls = 0

    def calculate_once(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return real_calculate(*args, **kwargs)

    monkeypatch.setattr("src.workflows.decision_themes.calculate_theme_decisions", calculate_once)
    summary = run_theme_decision_workflow(
        _request(tmp_path, skip_export=True),
        _config(tmp_path),
        current_utc=NOW,
        repository=repository,
    )
    assert calls == 1
    assert summary.verification == "passed"
    dimension_call = next(value for name, value in repository.calls if name == "dimension")
    representative_call = next(
        value for name, value in repository.calls if name == "representative"
    )
    assert dimension_call["period_end"] == date(2026, 7, 31)
    assert representative_call["period_end"] == date(2026, 7, 31)
    assert not any(name == "launch_outcomes" for name, _value in repository.calls)


def test_future_category_evidence_fails_before_persistence(tmp_path: Path) -> None:
    repository = EvidenceRepository(subgenres={"Theme": "Validated"})
    repository.future_dimension = True
    with pytest.raises(DecisionThemesError, match="future month"):
        run_theme_decision_workflow(
            _request(tmp_path, skip_export=True),
            _config(tmp_path),
            current_utc=NOW,
            repository=repository,
        )
    assert not any(name == "replace" for name, _value in repository.calls)


def test_missing_required_target_evidence_fails_before_persistence(tmp_path: Path) -> None:
    repository = EvidenceRepository()
    repository.structures = []
    with pytest.raises(DecisionThemesError, match="market structure"):
        run_theme_decision_workflow(
            _request(tmp_path, skip_export=True),
            _config(tmp_path),
            current_utc=NOW,
            repository=repository,
        )
    assert not any(name == "replace" for name, _value in repository.calls)


def test_identity_mismatch_fails_before_persistence(tmp_path: Path) -> None:
    repository = EvidenceRepository()
    repository.total = replace(repository.total, scope_name="wrong-scope")
    with pytest.raises(DecisionThemesError, match="mixed scope"):
        run_theme_decision_workflow(
            _request(tmp_path, skip_export=True),
            _config(tmp_path),
            current_utc=NOW,
            repository=repository,
        )
    assert not any(name == "replace" for name, _value in repository.calls)


def test_optional_evidence_remains_unavailable_and_post_commit_counts_reconcile(
    tmp_path: Path,
) -> None:
    repository = EvidenceRepository()
    summary = run_theme_decision_workflow(
        _request(tmp_path, skip_export=True),
        _config(tmp_path),
        current_utc=NOW,
        repository=repository,
    )
    assert summary.risk_row_count == len(repository.result.decision_risks)
    assert summary.category_fit_row_count == 0
    assert summary.migration_hypothesis_row_count == 0
    assert summary.confidence_distribution == (("medium", 1),)


def test_skip_export_commits_and_calls_no_exporter(tmp_path: Path) -> None:
    repository = EvidenceRepository()
    summary = run_theme_decision_workflow(
        _request(tmp_path, skip_export=True),
        _config(tmp_path),
        current_utc=NOW,
        repository=repository,
    )
    assert summary.skip_export is True
    assert summary.summaries_parquet_path is None
    assert repository.export_calls == []


def test_plan_only_validates_month_without_config_repository_or_files(
    tmp_path: Path,
) -> None:
    def fail_repository(_path: Path) -> EvidenceRepository:
        raise AssertionError("repository must not be constructed")

    summary = run_theme_decision_workflow(
        _request(tmp_path, plan_only=True),
        config=None,
        current_utc=NOW,
        repository_factory=fail_repository,
    )
    assert summary.plan_only is True
    assert summary.verification == "not_run"
    assert not (tmp_path / "decision.duckdb").exists()
    assert not (tmp_path / "exports").exists()


def test_format_is_sanitized_and_does_not_include_product_identities(tmp_path: Path) -> None:
    repository = EvidenceRepository()
    summary = run_theme_decision_workflow(
        _request(tmp_path, skip_export=True),
        _config(tmp_path),
        current_utc=NOW,
        repository=repository,
    )
    output = format_decide_themes_summary(summary)
    assert "summary_count=1" in output
    assert "recommendation_distribution=selective_validation:1" in output
    assert "game_theme" not in output
    assert "source_app_id" not in output
    assert "app" not in output.lower()


def test_workflow_source_has_no_external_or_future_outcome_boundary() -> None:
    source = Path("src/workflows/decision_themes.py").read_text(encoding="utf-8").lower()
    assert "sensortowerclient" not in source
    assert "feishuclient" not in source
    assert "sensor_tower.client" not in source
    assert "httpx" not in source
    assert "launch_window_outcomes" not in source


def test_post_commit_mismatch_is_sanitized(tmp_path: Path) -> None:
    repository = EvidenceRepository()
    repository.get_theme_decision_summaries = lambda **kwargs: []  # type: ignore[method-assign]
    with pytest.raises(DecisionReadbackVerificationError, match="post-commit"):
        run_theme_decision_workflow(
            _request(tmp_path, skip_export=True),
            _config(tmp_path),
            current_utc=NOW,
            repository=repository,
        )
