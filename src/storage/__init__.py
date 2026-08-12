"""Internal DuckDB storage package for market snapshots and metadata cache."""

from ..analysis.models import MonthlyMarketTotal, ThemeMonthlyMetric
from ..analysis.trend_models import ThemeTrendScore
from .errors import (
    ParquetExportError,
    RepositoryConnectionModeError,
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
from .parquet import (
    export_app_metadata_to_parquet,
    export_market_snapshots_to_parquet,
    export_monthly_market_totals_to_parquet,
    export_theme_monthly_metrics_to_parquet,
    export_theme_trend_scores_to_parquet,
)
from .repository import DuckDBRepository
from .schema import CURRENT_SCHEMA_VERSION, initialize_schema

__all__ = [
    "AppMetadataRow",
    "Cadence",
    "CURRENT_SCHEMA_VERSION",
    "DuckDBRepository",
    "MarketSnapshotRow",
    "MonthlyMarketTotal",
    "MetadataCacheLookup",
    "ParquetExportError",
    "RepositoryConnectionModeError",
    "PublisherResolutionSource",
    "RepositoryError",
    "RepositoryNotOpenError",
    "SchemaError",
    "SchemaInitializationError",
    "SchemaNotInitializedError",
    "SnapshotPeriodKey",
    "StorageError",
    "StorageValidationError",
    "ThemeMonthlyMetric",
    "ThemeTrendScore",
    "UnsupportedSchemaVersionError",
    "build_app_metadata_rows",
    "build_market_snapshot_rows",
    "export_app_metadata_to_parquet",
    "export_market_snapshots_to_parquet",
    "export_monthly_market_totals_to_parquet",
    "export_theme_monthly_metrics_to_parquet",
    "export_theme_trend_scores_to_parquet",
    "initialize_schema",
    "normalize_opaque_id_sequence",
    "normalize_id_sequence",
    "normalize_positive_id",
    "normalize_storage_opaque_id",
]
