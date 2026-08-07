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
