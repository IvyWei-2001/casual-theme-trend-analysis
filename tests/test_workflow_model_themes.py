"""Mock-only integration tests for the MODEL-002 local workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_storage_model002 import _payload, _store_agg002

from src.config import AppConfig
from src.storage import DuckDBRepository
from src.storage.errors import ParquetExportError
from src.workflows import ModelThemesRequest, format_model_themes_summary, model_themes

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _request(tmp_path: Path, *, plan_only: bool = False, skip_export: bool = False):
    return ModelThemesRequest(
        start_month="2023-08",
        end_month="2026-07",
        database_path=tmp_path / "data" / "model.duckdb",
        export_directory=tmp_path / "exports",
        plan_only=plan_only,
        skip_export=skip_export,
    )


def test_plan_only_has_exact_36_month_targets_without_database_or_files(tmp_path: Path) -> None:
    request = _request(tmp_path, plan_only=True)

    def fail_repository_factory(path: Path) -> DuckDBRepository:
        raise AssertionError(f"repository must not be created: {path}")

    summary = model_themes(
        request,
        AppConfig(),
        current_utc=NOW,
        repository_factory=fail_repository_factory,
    )
    rendered = format_model_themes_summary(summary)
    assert summary.history_month_count == 36
    assert summary.horizon_6m_target_month_count == 31
    assert summary.horizon_12m_target_month_count == 25
    assert summary.horizon_36m_target_month_count == 1
    assert summary.seasonality_target_month_count == 13
    assert "legacy_6m_baseline=recomputed_with_existing_formula" in rendered
    assert "network=disabled" in rendered
    assert "database=disabled" in rendered
    assert "file_writes=disabled" in rendered
    assert not request.database_path.exists()
    assert not request.export_directory.exists()


def test_complete_workflow_replaces_four_outputs_and_exports_sanitized_summary(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    repository = DuckDBRepository(request.database_path)
    repository.open()
    repository.initialize_schema()
    payload = _payload()
    _store_agg002(repository, payload)

    summary = model_themes(request, AppConfig(), current_utc=NOW, repository=repository)
    rendered = format_model_themes_summary(summary)
    assert summary.source_market_structure_row_count == 36
    assert summary.legacy_6m_score_row_count == 31
    assert summary.horizon_metric_row_count == 342
    assert summary.horizon_6m_row_count == 186
    assert summary.horizon_12m_row_count == 150
    assert summary.horizon_36m_row_count == 6
    assert summary.model_summary_row_count == 36
    assert summary.seasonality_profile_row_count == 936
    assert summary.seasonality_profile_group_count == 78
    assert summary.lifecycle_insufficient_history_count == 11
    assert summary.lifecycle_mature_count == 25
    assert summary.verification_passed is True
    assert summary.trend_parquet_path is not None and summary.trend_parquet_path.exists()
    assert summary.horizon_parquet_path is not None and summary.horizon_parquet_path.exists()
    assert summary.summaries_parquet_path is not None and summary.summaries_parquet_path.exists()
    assert (
        summary.seasonality_parquet_path is not None
        and summary.seasonality_parquet_path.exists()
    )
    assert "source_market_structure_row_count=36" in rendered
    assert "parquet_export=written" in rendered
    assert "game_theme=" not in rendered
    assert "app-" not in rendered
    repository.close()


def test_export_failure_leaves_committed_model_rows(tmp_path: Path) -> None:
    request = _request(tmp_path, skip_export=False)
    repository = DuckDBRepository(request.database_path)
    repository.open()
    repository.initialize_schema()
    payload = _payload()
    _store_agg002(repository, payload)

    def fail_export(_repository: object, path: Path) -> None:
        raise ParquetExportError("theme_horizon_metrics", str(path))

    with pytest.raises(ParquetExportError):
        model_themes(
            request,
            AppConfig(),
            current_utc=NOW,
            repository=repository,
            horizon_exporter=fail_export,
        )
    assert len(repository.get_theme_model_summaries()) == 36
    assert len(repository.get_theme_horizon_metrics()) == 342
    assert len(repository.get_theme_seasonality_profiles()) == 936
    repository.close()
