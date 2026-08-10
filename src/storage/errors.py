"""Typed errors raised by the local DuckDB storage boundary."""

from __future__ import annotations


class StorageError(Exception):
    """Base class for storage errors that callers may handle explicitly."""


class RepositoryError(StorageError):
    """Base class for repository lifecycle errors."""


class RepositoryNotOpenError(RepositoryError):
    """Raised when a repository operation requires an open connection."""

    def __init__(self) -> None:
        super().__init__("DuckDBRepository is not open")


class SchemaError(StorageError):
    """Base class for schema initialization and compatibility errors."""


class SchemaNotInitializedError(SchemaError):
    """Raised when a repository method is used before explicit initialization."""

    def __init__(self) -> None:
        super().__init__("DuckDB schema is not initialized; call initialize_schema() first")


class SchemaInitializationError(SchemaError):
    """Raised when an existing database cannot be safely used by this schema."""


class UnsupportedSchemaVersionError(SchemaError):
    """Raised when a database contains a schema newer than this application supports."""

    def __init__(self, found_version: int, supported_version: int) -> None:
        self.found_version = found_version
        self.supported_version = supported_version
        super().__init__(
            "database schema version "
            f"{found_version} is newer than the supported version {supported_version}"
        )


class StorageValidationError(StorageError, ValueError):
    """Raised when an internal storage model or write request is invalid."""


class ParquetExportError(StorageError):
    """Raised when an atomic Parquet export cannot be completed."""

    def __init__(self, table_name: str, path: str) -> None:
        self.table_name = table_name
        self.path = path
        super().__init__(f"failed to export {table_name} to Parquet at {path}")
