"""Sanitized errors raised by collection workflows."""

from __future__ import annotations


class WorkflowError(Exception):
    """Base class for expected workflow failures."""


class InvalidMonthError(WorkflowError, ValueError):
    """Raised when a requested month is not a completed natural month."""


class WorkflowMetadataIntegrityError(WorkflowError):
    """Raised when cached and newly fetched metadata cannot be joined safely."""
