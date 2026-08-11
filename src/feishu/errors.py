"""Sanitized errors for Feishu inspection and explicit field provisioning."""

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


class FeishuSchemaValidationError(FeishuConfigurationError):
    """Raised when the local desired Feishu schema is invalid."""


class FeishuSchemaIntegrityError(FeishuFieldIntegrityError):
    """Raised when the live table cannot safely be used for provisioning."""


class FeishuSchemaCompatibilityError(FeishuSchemaIntegrityError):
    """Raised when an existing desired-name field is incompatible."""

    def __init__(self, field_names: tuple[str, ...], details: str = "") -> None:
        self.field_names = field_names
        names = ", ".join(field_names)
        message = f"Feishu schema has incompatible desired fields: {names}"
        if details:
            message = f"{message}; {details}"
        super().__init__(message)


class FeishuSchemaVerificationError(FeishuSchemaIntegrityError):
    """Raised when the post-creation live schema is not complete and compatible."""


class FeishuPartialProvisioningError(FeishuRequestError):
    """Raised when field creation stops after one or more successful creates."""

    def __init__(self, created_field_names: tuple[str, ...]) -> None:
        self.created_field_names = created_field_names
        super().__init__(
            "Feishu field provisioning stopped after partial creation; rerun safely"
        )
