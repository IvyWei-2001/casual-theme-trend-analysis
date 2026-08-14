"""Sanitized errors raised by collection workflows."""

from __future__ import annotations

from typing import Literal


class WorkflowError(Exception):
    """Base class for expected workflow failures."""


class InvalidMonthError(WorkflowError, ValueError):
    """Raised when a requested month is not a completed natural month."""


class WorkflowMetadataIntegrityError(WorkflowError):
    """Raised when cached and newly fetched metadata cannot be joined safely."""


class ModelThemesError(WorkflowError):
    """Raised when the MODEL-002 workflow cannot complete safely."""


class ModelReadbackVerificationError(ModelThemesError):
    """Raised when committed MODEL-002 rows do not match the calculated payload."""


class BacktestThemesError(WorkflowError):
    """Raised when the BACKTEST-001 workflow cannot complete safely."""


class BacktestReadbackVerificationError(BacktestThemesError):
    """Raised when committed BACKTEST-001 rows do not match the payload."""


type BackfillFailureKind = Literal[
    "configuration",
    "sensor_tower",
    "storage",
    "workflow",
]


class BackfillMonthsError(WorkflowError):
    """Sanitized fail-fast error identifying the month that could not complete."""

    def __init__(
        self,
        failed_month: str,
        *,
        failure_kind: BackfillFailureKind,
        reason: str,
    ) -> None:
        self.failed_month = failed_month
        self.failure_kind = failure_kind
        super().__init__(f"backfill failed for month {failed_month}: {reason}")
