"""Mock-only integration tests for the MODEL-002 local workflow."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from test_storage_model002 import _payload, _store_agg002

from src.analysis.trend_models import ThemeTrendScore
from src.config import AppConfig
from src.storage import DuckDBRepository
from src.storage.errors import ParquetExportError
from src.workflows import ModelThemesRequest, format_model_themes_summary, model_themes
from src.workflows.errors import ModelReadbackVerificationError

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


class _LegacyThemeMismatchRepository(DuckDBRepository):
    def get_theme_trend_scores(
        self,
        scope_name: str | None = None,
        cadence: str = "monthly",
        period_start: date | None = None,
        period_end: date | None = None,
        game_theme: str | None = None,
    ) -> list[ThemeTrendScore]:
        rows = super().get_theme_trend_scores(
            scope_name=scope_name,
            cadence=cadence,
            period_start=period_start,
            period_end=period_end,
            game_theme=game_theme,
        )
        if not rows:
            return rows
        return [replace(rows[0], game_theme="replacement-theme"), *rows[1:]]


class _SeasonalityMeanMismatchRepository(DuckDBRepository):
    def get_theme_seasonality_profiles(self, *args: object, **kwargs: object):
        rows = super().get_theme_seasonality_profiles(*args, **kwargs)  # type: ignore[arg-type]
        if not rows:
            return rows
        first = rows[0]
        malformed_index = first.seasonal_index + 0.1
        malformed = replace(
            first,
            seasonal_index=malformed_index,
            index_deviation=malformed_index - 1,
        )
        return [malformed, *rows[1:]]


class _SeasonalityMetadataMismatchRepository(DuckDBRepository):
    malformed_field: str = ""

    def get_theme_seasonality_profiles(self, *args: object, **kwargs: object):
        rows = super().get_theme_seasonality_profiles(*args, **kwargs)  # type: ignore[arg-type]
        target = max(row.period_start for row in rows if row.history_month_count == 36)
        index = next(
            index
            for index, row in enumerate(rows)
            if row.period_start == target and row.metric_name == "product_count"
        )
        first = rows[index]
        if self.malformed_field == "observation_count":
            malformed = replace(first, observation_count=2)
        elif self.malformed_field == "history_start":
            malformed = replace(first, history_start=date(2023, 9, 1))
        elif self.malformed_field == "complete_year_count":
            malformed = replace(first)
            object.__setattr__(malformed, "complete_year_count", 2)
        else:
            raise AssertionError("unknown synthetic malformed field")
        return [malformed if row_index == index else row for row_index, row in enumerate(rows)]


class _SeasonalitySummaryMismatchRepository(DuckDBRepository):
    def get_theme_model_summaries(self, *args: object, **kwargs: object):
        rows = super().get_theme_model_summaries(*args, **kwargs)  # type: ignore[arg-type]
        malformed = next(row for row in rows if row.seasonality_history_month_count == 36)
        object.__setattr__(malformed, "seasonality_complete_year_count", 2)
        return rows


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
    assert summary.lifecycle_mixed_count == 0
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


def test_legacy_score_readback_uses_exact_theme_identity_and_sanitizes_mismatch(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, skip_export=True)
    repository = _LegacyThemeMismatchRepository(request.database_path)
    repository.open()
    repository.initialize_schema()
    _store_agg002(repository, _payload())

    with pytest.raises(
        ModelReadbackVerificationError,
        match="legacy score readback verification failed",
    ) as error:
        model_themes(request, AppConfig(), current_utc=NOW, repository=repository)

    message = str(error.value)
    assert "Theme" not in message
    assert "replacement-theme" not in message
    repository.close()


def test_seasonality_readback_rejects_malformed_mean_with_sanitized_error(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, skip_export=True)
    repository = _SeasonalityMeanMismatchRepository(request.database_path)
    repository.open()
    repository.initialize_schema()
    _store_agg002(repository, _payload())

    with pytest.raises(
        ModelReadbackVerificationError,
        match="seasonality mean readback verification failed",
    ) as error:
        model_themes(request, AppConfig(), current_utc=NOW, repository=repository)

    message = str(error.value)
    assert "Theme" not in message
    repository.close()


@pytest.mark.parametrize(
    "malformed_field",
    ("observation_count", "history_start", "complete_year_count"),
)
def test_seasonality_readback_rejects_mixed_metadata_with_sanitized_error(
    tmp_path: Path,
    malformed_field: str,
) -> None:
    request = _request(tmp_path, skip_export=True)
    repository = _SeasonalityMetadataMismatchRepository(request.database_path)
    repository.malformed_field = malformed_field
    repository.open()
    repository.initialize_schema()
    _store_agg002(repository, _payload())

    with pytest.raises(
        ModelReadbackVerificationError,
        match="seasonality metadata readback verification failed",
    ) as error:
        model_themes(request, AppConfig(), current_utc=NOW, repository=repository)

    message = str(error.value)
    assert "Theme" not in message
    assert "2023" not in message
    repository.close()


def test_seasonality_summary_profile_complete_year_mismatch_is_sanitized(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, skip_export=True)
    repository = _SeasonalitySummaryMismatchRepository(request.database_path)
    repository.open()
    repository.initialize_schema()
    _store_agg002(repository, _payload())

    with pytest.raises(
        ModelReadbackVerificationError,
        match="seasonality summary readback verification failed",
    ) as error:
        model_themes(request, AppConfig(), current_utc=NOW, repository=repository)

    message = str(error.value)
    assert "Theme" not in message
    assert "36" not in message
    assert "3" not in message
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
