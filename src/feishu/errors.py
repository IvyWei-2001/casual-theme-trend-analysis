"""Sanitized errors raised by the read-only Feishu integration."""

from __future__ import annotations


class FeishuError(Exception):
    """Base class for expected Feishu integration failures."""


class FeishuConfigurationError(FeishuError):
    """Raised when the local Feishu inspection configuration is invalid."""


class FeishuRequestError(FeishuError):
    """Raised when a Feishu request cannot be completed safely."""


class FeishuAuthenticationError(FeishuRequestError):
    """Raised when tenant-token authentication fails."""


class FeishuHTTPError(FeishuRequestError):
    """Raised for a non-successful Feishu HTTP response."""

    def __init__(self, operation: str, status_code: int) -> None:
        self.operation = operation
        self.status_code = status_code
        super().__init__(
            f"Feishu {operation} failed with HTTP status {status_code}"
        )


class FeishuAPIError(FeishuRequestError):
    """Raised when Feishu returns a non-zero response code."""

    def __init__(self, operation: str, code: int) -> None:
        self.operation = operation
        self.code = code
        super().__init__(f"Feishu {operation} failed with response code {code}")


class FeishuTimeoutError(FeishuRequestError):
    """Raised when a Feishu request exceeds its configured timeout."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(f"Feishu {operation} request timed out")


class FeishuMalformedResponseError(FeishuRequestError):
    """Raised when a Feishu response is not valid JSON or the expected shape."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(f"Feishu {operation} response was malformed")


class FeishuFieldIntegrityError(FeishuError):
    """Raised when the field-list response violates integrity rules."""
