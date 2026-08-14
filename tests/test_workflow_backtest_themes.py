"""Mock-only integration tests for the BACKTEST-001 local workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from test_storage_model002 import _payload, _store_agg002, _store_model

from src.config import AppConfig
from src.storage import DuckDBRepository
from src.workflows import (
    BacktestThemesRequest,
    backtest_themes,
    format_backtest_themes_summary,
)

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _request(tmp_path: Path, *, plan_only: bool = False, skip_export: bool = False):
    return BacktestThemesRequest(
        start_month="2023-08",
        end_month="2026-07",
        database_path=tmp_path / "data" / "backtest.duckdb",
        export_directory=tmp_path / "exports",
        plan_only=plan_only,
        skip_export=skip_export,
    )


def test_plan_only_uses_exact_registry_counts_without_repository(tmp_path: Path) -> None:
    request = _request(tmp_path, plan_only=True)

    def fail_repository_factory(path: Path) -> DuckDBRepository:
        raise AssertionError(f"repository must not be created: {path}")

    summary = backtest_themes(
        request,
        AppConfig(),
        current_utc=NOW,
        repository_factory=fail_repository_factory,
    )
    rendered = format_backtest_themes_summary(summary)

    assert summary.history_month_count == 36
    assert (
        summary.legacy_6m_decision_month_count_t1,
        summary.legacy_6m_decision_month_count_t2,
        summary.legacy_6m_decision_month_count_t3,
    ) == (30, 29, 28)
    assert (
        summary.model_12m_decision_month_count_t1,
        summary.model_12m_decision_month_count_t2,
        summary.model_12m_decision_month_count_t3,
    ) == (24, 23, 22)
    assert (
        summary.model_36m_decision_month_count_t1,
        summary.model_36m_decision_month_count_t2,
        summary.model_36m_decision_month_count_t3,
    ) == (0, 0, 0)
    assert (
        summary.seasonality_decision_month_count_t1,
        summary.seasonality_decision_month_count_t2,
        summary.seasonality_decision_month_count_t3,
    ) == (12, 11, 10)
    assert summary.planned_feature_metric_row_count == 228
    assert "network=disabled" in rendered
    assert "database=disabled" in rendered
    assert "file_writes=disabled" in rendered
    assert not request.database_path.exists()
    assert not request.export_directory.exists()


def test_complete_workflow_replaces_backtest_outputs_and_exports_them(tmp_path: Path) -> None:
    request = _request(tmp_path)
    repository = DuckDBRepository(request.database_path)
    repository.open()
    repository.initialize_schema()
    payload = _payload()
    _store_agg002(repository, payload)
    _store_model(repository, payload, calculated_at=payload.monthly_totals[0].calculated_at)

    summary = backtest_themes(request, AppConfig(), current_utc=NOW, repository=repository)
    rendered = format_backtest_themes_summary(summary)

    assert summary.source_model_summary_row_count == 36
    assert summary.source_legacy_6m_score_row_count == 31
    assert summary.outcome_row_count == 87
    assert (
        summary.horizon_1_outcome_row_count,
        summary.horizon_2_outcome_row_count,
        summary.horizon_3_outcome_row_count,
    ) == (30, 29, 28)
    assert summary.feature_metric_row_count == 228
    assert summary.segment_metric_row_count == 132
    assert summary.zero_eligible_36m_feature_metric_count == 24
    assert summary.verification_passed is True
    assert summary.outcomes_parquet_path is not None and summary.outcomes_parquet_path.exists()
    assert summary.feature_metrics_parquet_path is not None
    assert summary.feature_metrics_parquet_path.exists()
    assert summary.segment_metrics_parquet_path is not None
    assert summary.segment_metrics_parquet_path.exists()
    assert "verification=passed" in rendered
    assert "game_theme=" not in rendered
    assert "app-" not in rendered
    repository.close()
