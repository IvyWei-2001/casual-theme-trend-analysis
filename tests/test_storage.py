"""Tests for the connection-only DuckDB boundary."""

from pathlib import Path

from src.storage import DuckDBRepository


def test_temporary_duckdb_database_can_be_opened_and_closed(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "test.duckdb"
    repository = DuckDBRepository(database_path)

    connection = repository.open()

    assert database_path.exists()
    assert connection.execute("SELECT 1").fetchone() == (1,)
    assert connection.execute("SHOW TABLES").fetchall() == []

    repository.close()
    repository.close()


def test_close_does_not_create_a_database_file(tmp_path: Path) -> None:
    database_path = tmp_path / "not-opened.duckdb"
    repository = DuckDBRepository(database_path)

    repository.close()

    assert not database_path.exists()
