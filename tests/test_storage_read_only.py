"""Read-only DuckDB boundary regression tests."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from src.storage import DuckDBRepository


def test_read_only_connection_verifies_schema_without_migrating(tmp_path: Path) -> None:
    database_path = tmp_path / "history.duckdb"
    writable = DuckDBRepository(database_path)
    writable.open()
    writable.initialize_schema()
    migrations_before = writable.open().execute("SELECT count(*) FROM schema_migrations").fetchone()
    writable.close()

    read_only = DuckDBRepository(database_path)
    connection = read_only.open_read_only()
    read_only.verify_read_only_schema()
    assert (
        connection.execute("SELECT count(*) FROM schema_migrations").fetchone()
        == migrations_before
    )
    with pytest.raises(duckdb.Error):
        connection.execute("CREATE TABLE forbidden_write (value INTEGER)")
    read_only.close()
