"""Read-only DuckDB boundary regression tests."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from src.storage import DuckDBRepository, RepositoryConnectionModeError
from src.storage import schema as schema_module


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
        connection.execute("SELECT count(*) FROM schema_migrations").fetchone() == migrations_before
    )
    with pytest.raises(duckdb.Error):
        connection.execute("CREATE TABLE forbidden_write (value INTEGER)")
    read_only.close()


def test_read_only_v5_schema_is_not_migrated_to_v6(tmp_path: Path) -> None:
    database_path = tmp_path / "v5.duckdb"
    connection = duckdb.connect(str(database_path))
    connection.execute(schema_module._CREATE_SCHEMA_MIGRATIONS_SQL)
    for version, apply_version in (
        (1, schema_module._apply_version_one),
        (2, schema_module._apply_version_two),
        (3, schema_module._apply_version_three),
        (4, schema_module._apply_version_four),
        (5, schema_module._apply_version_five),
    ):
        apply_version(connection)
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
            [version],
        )
    connection.close()

    repository = DuckDBRepository(database_path)
    read_only = repository.open_read_only()
    repository.verify_read_only_schema()
    assert read_only.execute("SELECT max(version) FROM schema_migrations").fetchone() == (5,)
    assert read_only.execute(
        "SELECT count(*) FROM duckdb_tables() "
        "WHERE table_name IN ('theme_launch_window_outcomes', "
        "'theme_backtest_feature_metrics', 'theme_backtest_segment_metrics')"
    ).fetchone() == (0,)
    repository.close()


def test_writable_then_read_only_mode_reuse_is_rejected(tmp_path: Path) -> None:
    repository = DuckDBRepository(tmp_path / "history.duckdb")
    repository.open()

    with pytest.raises(RepositoryConnectionModeError, match="read-write"):
        repository.open_read_only()

    repository.close()


def test_read_only_then_writable_mode_reuse_is_rejected(tmp_path: Path) -> None:
    writable = DuckDBRepository(tmp_path / "history.duckdb")
    writable.open()
    writable.initialize_schema()
    writable.close()

    repository = DuckDBRepository(tmp_path / "history.duckdb")
    repository.open_read_only()

    with pytest.raises(RepositoryConnectionModeError, match="read-only"):
        repository.open()

    repository.close()


def test_close_resets_connection_mode_for_switching(tmp_path: Path) -> None:
    database_path = tmp_path / "history.duckdb"
    writable = DuckDBRepository(database_path)
    writable.open()
    writable.initialize_schema()
    writable.close()

    repository = DuckDBRepository(database_path)
    repository.open_read_only()
    repository.close()
    repository.open()
    repository.initialize_schema()
    repository.close()
