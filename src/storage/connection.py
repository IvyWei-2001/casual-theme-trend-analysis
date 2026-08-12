"""DuckDB connection creation for the storage package."""

from __future__ import annotations

from pathlib import Path

import duckdb


def open_duckdb_connection(database_path: str | Path) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB file after creating only its required parent directory."""

    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def open_duckdb_read_only_connection(
    database_path: str | Path,
) -> duckdb.DuckDBPyConnection:
    """Open an existing DuckDB file without allowing any local mutation."""

    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError("configured DuckDB database does not exist")
    return duckdb.connect(str(path), read_only=True)


connect = open_duckdb_connection
