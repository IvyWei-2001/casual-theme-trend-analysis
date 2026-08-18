"""Validation errors raised by the monthly aggregation boundary."""

from __future__ import annotations


class AggregationError(Exception):
    """Base class for deterministic aggregation failures."""


class AggregationValidationError(AggregationError, ValueError):
    """Raised when source rows, metadata, or derived values are invalid."""


class MonetizationValidationError(AggregationError, ValueError):
    """Raised when MONETIZATION-001 inputs or derived evidence are invalid."""


class MissingSourcePeriodError(AggregationValidationError):
    """Raised when a requested monthly source period is absent or empty."""

    def __init__(self, month: str) -> None:
        self.month = month
        super().__init__(f"source month {month} is missing or empty in DuckDB")


class BacktestValidationError(AggregationValidationError):
    """Raised when normalized BACKTEST-001 evidence cannot be evaluated safely."""
