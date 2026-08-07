"""Minimal DuckDB connection boundary with no business tables."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Self

import duckdb


class DuckDBRepository:
    """Open and close a configurable DuckDB database safely."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._connection: duckdb.DuckDBPyConnection | None = None

    def open(self) -> duckdb.DuckDBPyConnection:
        """Create the parent directory and open the database connection."""

        if self._connection is None:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = duckdb.connect(str(self.database_path))
        return self._connection

    def close(self) -> None:
        """Close the connection if it is open; repeated calls are safe."""

        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
