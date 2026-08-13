"""Deterministic, atomic Parquet exports from the local DuckDB store."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol

import duckdb

from .errors import ParquetExportError
from .schema import (
    APP_METADATA_COLUMNS,
    MARKET_SNAPSHOT_COLUMNS,
    MONTHLY_MARKET_TOTALS_COLUMNS,
    THEME_DIMENSION_MONTHLY_METRICS_COLUMNS,
    THEME_GROWTH_SOURCE_METRICS_COLUMNS,
    THEME_HORIZON_METRICS_COLUMNS,
    THEME_MARKET_STRUCTURE_METRICS_COLUMNS,
    THEME_MODEL_SUMMARIES_COLUMNS,
    THEME_MONTHLY_METRICS_COLUMNS,
    THEME_REPRESENTATIVE_GAMES_COLUMNS,
    THEME_SEASONALITY_PROFILES_COLUMNS,
    THEME_TREND_SCORES_COLUMNS,
)


class StorageRepositoryProtocol(Protocol):
    """Minimal repository contract needed by the export functions."""

    def _require_storage_connection(self) -> duckdb.DuckDBPyConnection:
        """Return an open, explicitly initialized storage connection."""


def export_market_snapshots_to_parquet(
    repository: StorageRepositoryProtocol,
    path: str | Path,
) -> None:
    """Export all market snapshots in stable column and rank order."""

    _export_table(
        repository,
        path=path,
        table_name="market_snapshots",
        columns=MARKET_SNAPSHOT_COLUMNS,
        order_by=("scope_name", "cadence", "period_start", "period_end", "rank_position"),
    )


def export_app_metadata_to_parquet(
    repository: StorageRepositoryProtocol,
    path: str | Path,
) -> None:
    """Export all metadata rows in stable column and ID order."""

    _export_table(
        repository,
        path=path,
        table_name="app_metadata",
        columns=APP_METADATA_COLUMNS,
        order_by=("unified_app_id",),
    )


def export_monthly_market_totals_to_parquet(
    repository: StorageRepositoryProtocol,
    path: str | Path,
) -> None:
    """Export derived monthly totals with stable columns and identity order."""

    _export_table(
        repository,
        path=path,
        table_name="monthly_market_totals",
        columns=MONTHLY_MARKET_TOTALS_COLUMNS,
        order_by=("scope_name", "period_start", "period_end"),
    )


def export_theme_monthly_metrics_to_parquet(
    repository: StorageRepositoryProtocol,
    path: str | Path,
) -> None:
    """Export derived theme metrics with stable columns and identity order."""

    _export_table(
        repository,
        path=path,
        table_name="theme_monthly_metrics",
        columns=THEME_MONTHLY_METRICS_COLUMNS,
        order_by=("scope_name", "period_start", "period_end", "game_theme"),
    )


def export_theme_market_structure_metrics_to_parquet(
    repository: StorageRepositoryProtocol,
    path: str | Path,
) -> None:
    """Export V2 market-structure metrics with stable identity ordering."""

    _export_table(
        repository,
        path=path,
        table_name="theme_market_structure_metrics",
        columns=THEME_MARKET_STRUCTURE_METRICS_COLUMNS,
        order_by=("scope_name", "period_start", "period_end", "game_theme"),
    )


def export_theme_growth_source_metrics_to_parquet(
    repository: StorageRepositoryProtocol,
    path: str | Path,
) -> None:
    """Export V2 growth-source metrics with stable identity ordering."""

    _export_table(
        repository,
        path=path,
        table_name="theme_growth_source_metrics",
        columns=THEME_GROWTH_SOURCE_METRICS_COLUMNS,
        order_by=("scope_name", "period_start", "period_end", "game_theme"),
    )


def export_theme_dimension_monthly_metrics_to_parquet(
    repository: StorageRepositoryProtocol,
    path: str | Path,
) -> None:
    """Export V2 observed dimension metrics with stable identity ordering."""

    _export_table(
        repository,
        path=path,
        table_name="theme_dimension_monthly_metrics",
        columns=THEME_DIMENSION_MONTHLY_METRICS_COLUMNS,
        order_by=(
            "scope_name",
            "period_start",
            "period_end",
            "game_theme",
            "dimension_type",
            "dimension_value",
        ),
    )


def export_theme_representative_games_to_parquet(
    repository: StorageRepositoryProtocol,
    path: str | Path,
) -> None:
    """Export V2 representative-game evidence with stable identity ordering."""

    _export_table(
        repository,
        path=path,
        table_name="theme_representative_games",
        columns=THEME_REPRESENTATIVE_GAMES_COLUMNS,
        order_by=(
            "scope_name",
            "period_start",
            "period_end",
            "game_theme",
            "evidence_type",
            "evidence_rank",
        ),
    )


def export_theme_trend_scores_to_parquet(
    repository: StorageRepositoryProtocol,
    path: str | Path,
) -> None:
    """Export schema-v3 trend scores in stable ranking order."""

    _export_table(
        repository,
        path=path,
        table_name="theme_trend_scores",
        columns=THEME_TREND_SCORES_COLUMNS,
        order_by=("scope_name", "period_start", "trend_rank NULLS LAST", "game_theme"),
    )


def export_theme_horizon_metrics_to_parquet(
    repository: StorageRepositoryProtocol,
    path: str | Path,
) -> None:
    """Export long-form horizon evidence with stable identity ordering."""

    _export_table(
        repository,
        path=path,
        table_name="theme_horizon_metrics",
        columns=THEME_HORIZON_METRICS_COLUMNS,
        order_by=(
            "scope_name",
            "period_start",
            "period_end",
            "game_theme",
            "horizon_month_count",
            "metric_name",
        ),
    )


def export_theme_model_summaries_to_parquet(
    repository: StorageRepositoryProtocol,
    path: str | Path,
) -> None:
    """Export model summaries with stable identity ordering."""

    _export_table(
        repository,
        path=path,
        table_name="theme_model_summaries",
        columns=THEME_MODEL_SUMMARIES_COLUMNS,
        order_by=("scope_name", "period_start", "period_end", "game_theme"),
    )


def export_theme_seasonality_profiles_to_parquet(
    repository: StorageRepositoryProtocol,
    path: str | Path,
) -> None:
    """Export leakage-safe seasonality profiles with stable ordering."""

    _export_table(
        repository,
        path=path,
        table_name="theme_seasonality_profiles",
        columns=THEME_SEASONALITY_PROFILES_COLUMNS,
        order_by=(
            "scope_name",
            "period_start",
            "period_end",
            "game_theme",
            "metric_name",
            "calendar_month",
        ),
    )


def _export_table(
    repository: StorageRepositoryProtocol,
    *,
    path: str | Path,
    table_name: str,
    columns: tuple[str, ...],
    order_by: tuple[str, ...],
) -> None:
    connection = repository._require_storage_connection()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = _temporary_sibling(destination)
    column_sql = ", ".join(columns)
    order_sql = ", ".join(order_by)
    copy_sql = (
        f"COPY (SELECT {column_sql} FROM {table_name} "
        f"ORDER BY {order_sql}) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)"
    )

    try:
        connection.execute(copy_sql, [str(temporary_path)])
        os.replace(temporary_path, destination)
    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ParquetExportError(table_name, str(destination)) from None


def _temporary_sibling(destination: Path) -> Path:
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".parquet.tmp",
        dir=str(destination.parent),
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)
    temporary_path.unlink()
    return temporary_path
