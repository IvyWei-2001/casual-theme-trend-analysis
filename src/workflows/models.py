"""Typed inputs, validated monthly boundaries, and collection results."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from .errors import InvalidMonthError, WorkflowError

if TYPE_CHECKING:
    from ..analysis.trend_models import ThemeTrendScore

_MONTH_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}$")
type MonthlyCadence = Literal["monthly"]


@dataclass(frozen=True, slots=True)
class MonthlyPeriod:
    """One completed natural calendar month in UTC date boundaries."""

    month: str
    period_start: date
    period_end: date
    cadence: MonthlyCadence = "monthly"

    @classmethod
    def parse(
        cls,
        month: str,
        *,
        current_utc: datetime | date,
    ) -> MonthlyPeriod:
        """Validate a ``YYYY-MM`` month against one injected UTC clock value."""

        if not isinstance(month, str) or _MONTH_PATTERN.fullmatch(month) is None:
            raise InvalidMonthError("month must use the exact YYYY-MM format")

        year = int(month[:4])
        month_number = int(month[5:7])
        try:
            period_start = date(year, month_number, 1)
        except ValueError as error:
            raise InvalidMonthError("month is not a valid calendar month") from error

        period_end = date(year, month_number, calendar.monthrange(year, month_number)[1])
        current_date = _utc_date(current_utc)
        requested_key = (period_start.year, period_start.month)
        current_key = (current_date.year, current_date.month)
        if requested_key > current_key:
            raise InvalidMonthError("future months are not allowed")
        if requested_key == current_key:
            raise InvalidMonthError("the current incomplete calendar month is not allowed")

        return cls(
            month=month,
            period_start=period_start,
            period_end=period_end,
        )

    @classmethod
    def from_month(
        cls,
        month: str,
        *,
        current_utc: datetime | date,
    ) -> MonthlyPeriod:
        """Alias for callers that prefer a constructor-style name."""

        return cls.parse(month, current_utc=current_utc)


@dataclass(frozen=True, slots=True)
class CollectMonthRequest:
    """Validated workflow inputs supplied by the CLI or an embedding caller."""

    month: str
    database_path: Path
    export_directory: Path
    plan_only: bool = False
    skip_export: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.month, str) or not self.month:
            raise WorkflowError("month must be a non-empty string")
        for field_name in ("database_path", "export_directory"):
            value = getattr(self, field_name)
            if not isinstance(value, (Path, str)) or not str(value).strip():
                raise WorkflowError(f"{field_name} must be a non-empty path")
            object.__setattr__(self, field_name, Path(value))
        for field_name in ("plan_only", "skip_export"):
            if not isinstance(getattr(self, field_name), bool):
                raise WorkflowError(f"{field_name} must be a boolean")


@dataclass(frozen=True, slots=True)
class BackfillMonthRange:
    """Validated inclusive sequence of completed natural calendar months."""

    start_month: str
    end_month: str
    periods: tuple[MonthlyPeriod, ...]

    @classmethod
    def parse(
        cls,
        start_month: str,
        end_month: str,
        *,
        current_utc: datetime | date,
    ) -> BackfillMonthRange:
        """Validate both boundaries and build the chronological month sequence."""

        start_period = MonthlyPeriod.parse(start_month, current_utc=current_utc)
        end_period = MonthlyPeriod.parse(end_month, current_utc=current_utc)
        if start_period.period_start > end_period.period_start:
            raise InvalidMonthError("start month must be on or before end month")

        periods: list[MonthlyPeriod] = []
        period = start_period
        while period.period_start <= end_period.period_start:
            periods.append(period)
            if period.period_start == end_period.period_start:
                break
            next_month = _next_month(period.period_start.year, period.period_start.month)
            period = MonthlyPeriod.parse(next_month, current_utc=current_utc)

        return cls(
            start_month=start_period.month,
            end_month=end_period.month,
            periods=tuple(periods),
        )

    @property
    def months(self) -> tuple[str, ...]:
        """Return the inclusive month names in oldest-to-newest order."""

        return tuple(period.month for period in self.periods)


# Keep the plural spelling available for callers that name the operation rather
# than the boundary represented by the type.
BackfillMonthsRange = BackfillMonthRange


@dataclass(frozen=True, slots=True)
class BackfillMonthsRequest:
    """Validated inputs for a resumable inclusive monthly backfill."""

    start_month: str
    end_month: str
    database_path: Path
    export_directory: Path
    plan_only: bool = False
    refresh_existing: bool = False
    skip_export: bool = False

    def __post_init__(self) -> None:
        for field_name in ("start_month", "end_month"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise WorkflowError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value)
        for field_name in ("database_path", "export_directory"):
            value = getattr(self, field_name)
            if not isinstance(value, (Path, str)) or not str(value).strip():
                raise WorkflowError(f"{field_name} must be a non-empty path")
            object.__setattr__(self, field_name, Path(value))
        for field_name in ("plan_only", "refresh_existing", "skip_export"):
            if not isinstance(getattr(self, field_name), bool):
                raise WorkflowError(f"{field_name} must be a boolean")


@dataclass(frozen=True, slots=True)
class AggregateThemesRequest:
    """Validated inputs for a local monthly Game Theme aggregation."""

    start_month: str
    end_month: str
    database_path: Path
    export_directory: Path
    plan_only: bool = False
    skip_export: bool = False

    def __post_init__(self) -> None:
        for field_name in ("start_month", "end_month"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise WorkflowError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value)
        for field_name in ("database_path", "export_directory"):
            value = getattr(self, field_name)
            if not isinstance(value, (Path, str)) or not str(value).strip():
                raise WorkflowError(f"{field_name} must be a non-empty path")
            object.__setattr__(self, field_name, Path(value))
        for field_name in ("plan_only", "skip_export"):
            if not isinstance(getattr(self, field_name), bool):
                raise WorkflowError(f"{field_name} must be a boolean")


@dataclass(frozen=True, slots=True)
class ScoreThemesRequest:
    """Validated inputs for the local monthly theme trend score workflow."""

    start_month: str
    end_month: str
    database_path: Path
    export_directory: Path
    plan_only: bool = False
    skip_export: bool = False
    top_n: int = 20

    def __post_init__(self) -> None:
        for field_name in ("start_month", "end_month"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise WorkflowError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value)
        for field_name in ("database_path", "export_directory"):
            value = getattr(self, field_name)
            if not isinstance(value, (Path, str)) or not str(value).strip():
                raise WorkflowError(f"{field_name} must be a non-empty path")
            object.__setattr__(self, field_name, Path(value))
        for field_name in ("plan_only", "skip_export"):
            if not isinstance(getattr(self, field_name), bool):
                raise WorkflowError(f"{field_name} must be a boolean")
        if isinstance(self.top_n, bool) or not isinstance(self.top_n, int) or self.top_n <= 0:
            raise WorkflowError("top_n must be a positive integer")


@dataclass(frozen=True, slots=True)
class SyncFeishuTrendsRequest:
    """Validated inputs for complete DuckDB-to-Feishu trend synchronization."""

    database_path: Path
    plan_only: bool = False
    apply: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.database_path, (Path, str)) or not str(self.database_path).strip():
            raise WorkflowError("database_path must be a non-empty path")
        object.__setattr__(self, "database_path", Path(self.database_path))
        for field_name in ("plan_only", "apply"):
            if not isinstance(getattr(self, field_name), bool):
                raise WorkflowError(f"{field_name} must be a boolean")
        if self.plan_only and self.apply:
            raise WorkflowError("plan_only and apply are mutually exclusive")


@dataclass(frozen=True, slots=True)
class CollectMonthSummary:
    """Sanitized result of one plan or completed collection run."""

    month: str
    period_start: date
    period_end: date
    scope_name: str
    candidate_count: int
    selected_count: int
    metadata_cache_fresh_count: int
    metadata_stale_count: int
    metadata_missing_count: int
    metadata_requested_count: int
    metadata_returned_count: int
    metadata_unresolved_count: int
    snapshot_rows_written: int
    database_path: Path
    market_parquet_path: Path | None
    metadata_parquet_path: Path | None
    plan_only: bool
    started_at: datetime
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class BackfillMonthsSummary:
    """Sanitized result of a validated or completed monthly backfill."""

    start_month: str
    end_month: str
    planned_month_count: int
    planned_months: tuple[str, ...]
    collected_month_count: int
    skipped_existing_month_count: int
    failed_month: str | None
    total_candidate_count: int
    total_selected_count: int
    total_metadata_cache_fresh_count: int
    total_metadata_requested_count: int
    total_metadata_returned_count: int
    total_metadata_unresolved_count: int
    total_snapshot_rows_written: int
    database_path: Path
    market_parquet_path: Path | None
    metadata_parquet_path: Path | None
    plan_only: bool
    started_at: datetime
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class AggregateThemesSummary:
    """Sanitized result of a validated or completed theme aggregation."""

    start_month: str
    end_month: str
    planned_month_count: int
    planned_months: tuple[str, ...]
    aggregated_month_count: int
    monthly_totals_row_count: int
    theme_metrics_row_count: int
    source_snapshot_row_count: int
    source_missing_theme_count: int
    source_units_coverage_count: int
    source_revenue_coverage_count: int
    market_structure_row_count: int
    growth_source_row_count: int
    dimension_row_count: int
    game_subgenre_dimension_row_count: int
    game_product_model_dimension_row_count: int
    game_art_style_dimension_row_count: int
    game_setting_dimension_row_count: int
    representative_game_row_count: int
    verification_passed: bool
    database_path: Path
    monthly_totals_parquet_path: Path | None
    theme_metrics_parquet_path: Path | None
    market_structure_parquet_path: Path | None
    growth_source_parquet_path: Path | None
    dimension_parquet_path: Path | None
    representative_games_parquet_path: Path | None
    plan_only: bool
    started_at: datetime
    completed_at: datetime

    @property
    def legacy_theme_metrics_row_count(self) -> int:
        """Return the AGG-001 theme row count under the V2 summary name."""

        return self.theme_metrics_row_count

    @property
    def verification(self) -> str:
        """Return the sanitized readback status used by CLI summaries."""

        return "passed" if self.verification_passed else "not_run"


@dataclass(frozen=True, slots=True)
class ScoreThemesSummary:
    """Sanitized result of a validated or completed theme trend score run."""

    start_month: str
    end_month: str
    history_month_count: int
    scorable_target_month_count: int
    trend_row_count: int
    actionable_row_count: int
    non_actionable_row_count: int
    latest_target_month: str | None
    latest_actionable_theme_count: int
    database_path: Path
    trend_parquet_path: Path | None
    plan_only: bool
    started_at: datetime
    completed_at: datetime
    top_n: int
    latest_scores: tuple[ThemeTrendScore, ...]


def _next_month(year: int, month: int) -> str:
    if month == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{month + 1:02d}"


def _utc_date(value: datetime | date) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise InvalidMonthError("current UTC time must be timezone-aware")
        return value.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    raise InvalidMonthError("current UTC time must be a date or timezone-aware datetime")
