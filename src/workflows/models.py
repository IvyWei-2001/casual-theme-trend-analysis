"""Typed inputs, validated monthly boundaries, and collection results."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from .errors import InvalidMonthError, WorkflowError

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


def _utc_date(value: datetime | date) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise InvalidMonthError("current UTC time must be timezone-aware")
        return value.astimezone(UTC).date()
    if isinstance(value, date):
        return value
    raise InvalidMonthError("current UTC time must be a date or timezone-aware datetime")
