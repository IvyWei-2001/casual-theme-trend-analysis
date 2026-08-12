"""Sanitized errors for Feishu inspection, provisioning, and synchronization."""

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


class FeishuRecordIntegrityError(FeishuFieldIntegrityError):
    """Raised when the record-list response violates integrity rules."""


class FeishuSyncIntegrityError(FeishuRecordIntegrityError):
    """Raised when a synchronization source or managed record is unsafe."""


class FeishuSourceValidationError(FeishuSyncIntegrityError):
    """Raised when the authoritative DuckDB score set is invalid."""


class FeishuManagedRecordIntegrityError(FeishuSyncIntegrityError):
    """Raised when a managed Feishu record has an unsupported cell shape."""


class FeishuDuplicateManagedKeyError(FeishuSyncIntegrityError):
    """Raised when multiple Feishu records claim one managed key."""

    def __init__(self, duplicate_count: int) -> None:
        self.duplicate_count = duplicate_count
        super().__init__(
            "Feishu trend synchronization found duplicate managed keys; "
            f"duplicate_count={duplicate_count}"
        )


class FeishuStaleManagedRecordError(FeishuSyncIntegrityError):
    """Raised when an apply would leave managed records outside the source set."""

    def __init__(self, stale_count: int) -> None:
        self.stale_count = stale_count
        super().__init__(
            "Feishu trend synchronization found stale managed records; "
            f"stale_count={stale_count}"
        )


class FeishuReconciliationVerificationError(FeishuSyncIntegrityError):
    """Raised when a post-write reread does not converge to the source set."""


class FeishuPartialSynchronizationError(FeishuRequestError):
    """Raised when one or more writes succeeded before a later write failed."""

    def __init__(self, successful_write_request_count: int) -> None:
        self.successful_write_request_count = successful_write_request_count
        super().__init__(
            "Feishu trend synchronization stopped after partial writes; "
            "reread and rerun safely; "
            f"successful_write_request_count={successful_write_request_count}"
        )


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
