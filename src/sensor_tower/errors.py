"""Sanitized errors for the Sensor Tower request and selection boundaries."""

from __future__ import annotations


class SensorTowerError(Exception):
    """Base class for expected Sensor Tower integration failures."""


class SensorTowerConfigurationError(SensorTowerError):
    """Raised when required local Sensor Tower configuration is invalid."""


class SensorTowerRequestError(SensorTowerError):
    """Raised when a Sensor Tower request cannot be completed."""


class SensorTowerHTTPError(SensorTowerRequestError):
    """Raised for a non-successful Sensor Tower HTTP response."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Sensor Tower market request failed with HTTP status {status_code}")


class SensorTowerTimeoutError(SensorTowerRequestError):
    """Raised when the Sensor Tower request exceeds its configured timeout."""

    def __init__(self) -> None:
        super().__init__("Sensor Tower market request timed out")


class SensorTowerMalformedResponseError(SensorTowerRequestError):
    """Raised when a response is not valid JSON or not the verified shape."""


class SensorTowerMetadataError(SensorTowerError):
    """Base class for expected metadata-enrichment failures."""


class SensorTowerMetadataRequestError(SensorTowerMetadataError):
    """Raised when one metadata batch request cannot be completed safely."""


class SensorTowerMetadataHTTPError(SensorTowerMetadataRequestError):
    """Raised for a non-successful metadata HTTP response."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(
            f"Sensor Tower metadata request failed with HTTP status {status_code}"
        )


class SensorTowerMetadataTimeoutError(SensorTowerMetadataRequestError):
    """Raised when one metadata request exceeds its configured timeout."""

    def __init__(self) -> None:
        super().__init__("Sensor Tower metadata request timed out")


class SensorTowerMetadataMalformedResponseError(SensorTowerMetadataRequestError):
    """Raised when metadata JSON or its response envelope is malformed."""


class SensorTowerMetadataIntegrityError(SensorTowerMetadataError):
    """Raised when metadata IDs violate the requested-response integrity rules."""


class SensorTowerMetadataBatchError(SensorTowerMetadataRequestError):
    """Raised after all sanitized attempts for one metadata batch fail."""

    def __init__(self, batch_number: int, attempts: int) -> None:
        self.batch_number = batch_number
        self.attempts = attempts
        super().__init__(
            "Sensor Tower metadata batch "
            f"{batch_number} failed after {attempts} attempts"
        )


class SensorTowerSelectionConfigurationError(SensorTowerError):
    """Raised when local candidate-selection settings are invalid."""


class NoEligibleMarketRecordsError(SensorTowerError):
    """Raised when no candidate survives the local eligibility rules."""

    def __init__(self, candidate_count: int) -> None:
        self.candidate_count = candidate_count
        self.selected_count = 0
        super().__init__(
            "No eligible Sensor Tower market records remain "
            f"after local filtering (candidates={candidate_count}, selected=0)"
        )
