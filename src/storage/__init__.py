"""Internal DuckDB storage package for market snapshots and metadata cache."""

from .errors import (
    ParquetExportError,
    RepositoryError,
    RepositoryNotOpenError,
    SchemaError,
    SchemaInitializationError,
    SchemaNotInitializedError,
    StorageError,
    StorageValidationError,
    UnsupportedSchemaVersionError,
)
from .mappers import build_app_metadata_rows, build_market_snapshot_rows
from .models import (
    AppMetadataRow,
    Cadence,
    MarketSnapshotRow,
    MetadataCacheLookup,
    PublisherResolutionSource,
    SnapshotPeriodKey,
    normalize_id_sequence,
    normalize_opaque_id_sequence,
    normalize_positive_id,
    normalize_storage_opaque_id,
)
from .parquet import export_app_metadata_to_parquet, export_market_snapshots_to_parquet
from .repository import DuckDBRepository
from .schema import CURRENT_SCHEMA_VERSION, initialize_schema

__all__ = [
    "AppMetadataRow",
    "Cadence",
    "CURRENT_SCHEMA_VERSION",
    "DuckDBRepository",
    "MarketSnapshotRow",
    "MetadataCacheLookup",
    "ParquetExportError",
    "PublisherResolutionSource",
    "RepositoryError",
    "RepositoryNotOpenError",
    "SchemaError",
    "SchemaInitializationError",
    "SchemaNotInitializedError",
    "SnapshotPeriodKey",
    "StorageError",
    "StorageValidationError",
    "UnsupportedSchemaVersionError",
    "build_app_metadata_rows",
    "build_market_snapshot_rows",
    "export_app_metadata_to_parquet",
    "export_market_snapshots_to_parquet",
    "initialize_schema",
    "normalize_opaque_id_sequence",
    "normalize_id_sequence",
    "normalize_positive_id",
    "normalize_storage_opaque_id",
]
