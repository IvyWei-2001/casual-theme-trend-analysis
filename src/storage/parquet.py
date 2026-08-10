"""Deterministic, atomic Parquet exports from the local DuckDB store."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol

import duckdb

from .errors import ParquetExportError
from .schema import APP_METADATA_COLUMNS, MARKET_SNAPSHOT_COLUMNS


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
