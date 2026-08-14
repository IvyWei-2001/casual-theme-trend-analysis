"""Mock-only integration tests for the BACKTEST-001 local workflow."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_storage_model002 import _payload, _store_agg002, _store_model

from src.analysis.backtest_v1 import calculate_theme_launch_window_backtest
from src.analysis.model_v2 import calculate_theme_model_metrics
from src.analysis.trend_score import calculate_theme_trend_scores
from src.config import AppConfig
from src.storage import DuckDBRepository
from src.workflows import (
    BacktestReadbackVerificationError,
    BacktestThemesRequest,
    backtest_themes,
    format_backtest_themes_summary,
)

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
NOW_AFTER_AUGUST = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)


def _request(
    tmp_path: Path,
    *,
    end_month: str = "2026-07",
    plan_only: bool = False,
    skip_export: bool = False,
):
    return BacktestThemesRequest(
        start_month="2023-08",
        end_month=end_month,
        database_path=tmp_path / "data" / "backtest.duckdb",
        export_directory=tmp_path / "exports",
        plan_only=plan_only,
        skip_export=skip_export,
    )


def _expected_backtest(payload, *, calculated_at: datetime):
    model = calculate_theme_model_metrics(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        payload.monthly_totals[0].calculated_at,
    )
    scores = calculate_theme_trend_scores(
        payload.monthly_totals,
        payload.theme_metrics,
        calculated_at=payload.monthly_totals[0].calculated_at,
    )
    return calculate_theme_launch_window_backtest(
        payload.monthly_totals,
        payload.theme_market_structure_metrics,
        payload.theme_growth_source_metrics,
        scores,
        model.model_summaries,
        model.seasonality_profiles,
        calculated_at=calculated_at,
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


def test_monthly_expansion_reads_only_the_new_exact_aggregate_run(
    tmp_path: Path,
) -> None:
    repository = DuckDBRepository(tmp_path / "monthly-expansion.duckdb")
    repository.open()
    repository.initialize_schema()
    payload36 = _payload()
    _store_agg002(repository, payload36)
    _store_model(repository, payload36, calculated_at=payload36.monthly_totals[0].calculated_at)

    request36 = _request(tmp_path, skip_export=True)
    expected36 = _expected_backtest(payload36, calculated_at=NOW)
    summary36 = backtest_themes(
        request36,
        AppConfig(),
        current_utc=NOW,
        repository=repository,
    )
    exact36_features = repository.get_theme_backtest_feature_metrics_exact(
        scope_name=expected36.feature_metrics[0].scope_name,
        backtest_start=expected36.feature_metrics[0].backtest_start,
        backtest_end=expected36.feature_metrics[0].backtest_end,
    )
    exact36_segments = repository.get_theme_backtest_segment_metrics_exact(
        scope_name=expected36.segment_metrics[0].scope_name,
        backtest_start=expected36.segment_metrics[0].backtest_start,
        backtest_end=expected36.segment_metrics[0].backtest_end,
    )
    assert summary36.feature_metric_row_count == 228
    assert len(exact36_features) == 228
    assert set(exact36_features) == set(expected36.feature_metrics)
    assert set(exact36_segments) == set(expected36.segment_metrics)

    payload37 = _payload(month_count=37)
    _store_agg002(repository, payload37)
    _store_model(repository, payload37, calculated_at=payload37.monthly_totals[0].calculated_at)
    request37 = _request(tmp_path, end_month="2026-08", skip_export=True)
    expected37 = _expected_backtest(payload37, calculated_at=NOW_AFTER_AUGUST)
    summary37 = backtest_themes(
        request37,
        AppConfig(),
        current_utc=NOW_AFTER_AUGUST,
        repository=repository,
    )
    rendered37 = format_backtest_themes_summary(summary37)
    exact37_features = repository.get_theme_backtest_feature_metrics_exact(
        scope_name=expected37.feature_metrics[0].scope_name,
        backtest_start=expected37.feature_metrics[0].backtest_start,
        backtest_end=expected37.feature_metrics[0].backtest_end,
    )
    exact37_segments = repository.get_theme_backtest_segment_metrics_exact(
        scope_name=expected37.segment_metrics[0].scope_name,
        backtest_start=expected37.segment_metrics[0].backtest_start,
        backtest_end=expected37.segment_metrics[0].backtest_end,
    )
    assert summary37.verification_passed is True
    assert summary37.feature_metric_row_count == 228
    assert len(exact37_features) == 228
    assert set(exact37_features) == set(expected37.feature_metrics)
    assert set(exact37_segments) == set(expected37.segment_metrics)
    assert {row.backtest_end for row in exact37_features} == {
        expected37.feature_metrics[0].backtest_end
    }
    assert {row.backtest_end for row in exact37_segments} == {
        expected37.segment_metrics[0].backtest_end
    }
    assert set(
        repository.get_theme_backtest_feature_metrics_exact(
            scope_name=expected36.feature_metrics[0].scope_name,
            backtest_start=expected36.feature_metrics[0].backtest_start,
            backtest_end=expected36.feature_metrics[0].backtest_end,
        )
    ) == set(expected36.feature_metrics)
    assert "verification=passed" in rendered37

    snapshot37 = (
        repository.get_theme_launch_window_outcomes(),
        exact37_features,
        exact37_segments,
    )
    rerun_summary = backtest_themes(
        request37,
        AppConfig(),
        current_utc=NOW_AFTER_AUGUST,
        repository=repository,
    )
    assert rerun_summary.verification_passed is True
    assert (
        repository.get_theme_launch_window_outcomes(),
        repository.get_theme_backtest_feature_metrics_exact(
            scope_name=expected37.feature_metrics[0].scope_name,
            backtest_start=expected37.feature_metrics[0].backtest_start,
            backtest_end=expected37.feature_metrics[0].backtest_end,
        ),
        repository.get_theme_backtest_segment_metrics_exact(
            scope_name=expected37.segment_metrics[0].scope_name,
            backtest_start=expected37.segment_metrics[0].backtest_start,
            backtest_end=expected37.segment_metrics[0].backtest_end,
        ),
    ) == snapshot37
    repository.close()


class _PublicReadbackMismatchRepository(DuckDBRepository):
    corrupt_feature_readback = False

    def get_theme_backtest_feature_metrics_exact(self, *args: object, **kwargs: object):
        rows = super().get_theme_backtest_feature_metrics_exact(  # type: ignore[arg-type]
            *args,
            **kwargs,
        )
        if self.corrupt_feature_readback and rows:
            self.corrupt_feature_readback = False
            return [
                replace(rows[0], calculated_at=rows[0].calculated_at + timedelta(seconds=1)),
                *rows[1:],
            ]
        return rows


def test_public_workflow_readback_mismatch_is_sanitized(tmp_path: Path) -> None:
    request = _request(tmp_path, skip_export=True)
    repository = _PublicReadbackMismatchRepository(request.database_path)
    repository.open()
    repository.initialize_schema()
    payload = _payload()
    _store_agg002(repository, payload)
    _store_model(repository, payload, calculated_at=payload.monthly_totals[0].calculated_at)
    repository.corrupt_feature_readback = True

    with pytest.raises(
        BacktestReadbackVerificationError,
        match="BACKTEST-001 readback verification failed",
    ) as error:
        backtest_themes(request, AppConfig(), current_utc=NOW, repository=repository)

    assert "Theme" not in str(error.value)
    assert "app-" not in str(error.value)
    repository.close()
