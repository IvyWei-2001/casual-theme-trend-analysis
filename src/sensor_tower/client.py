"""HTTP client for the verified Sensor Tower market endpoint."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Self

import httpx
from pydantic import SecretStr

from .dto import SensorTowerMarketRecord
from .errors import (
    SensorTowerConfigurationError,
    SensorTowerHTTPError,
    SensorTowerMalformedResponseError,
    SensorTowerRequestError,
    SensorTowerTimeoutError,
)
from .parser import parse_market_response
from .request import (
    DEFAULT_SENSOR_TOWER_BASE_URL,
    DEFAULT_SENSOR_TOWER_TIMEOUT_SECONDS,
    SENSOR_TOWER_MARKET_ENDPOINT_PATH,
    SensorTowerMarketRequest,
    resolve_auth_token,
)

LOGGER = logging.getLogger(__name__)


class SensorTowerClient:
    """Synchronous Sensor Tower market client with injectable HTTP transport."""

    def __init__(
        self,
        auth_token: SecretStr | str,
        *,
        base_url: str = DEFAULT_SENSOR_TOWER_BASE_URL,
        timeout: float = DEFAULT_SENSOR_TOWER_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise SensorTowerConfigurationError("Sensor Tower API base URL is not configured")
        if timeout <= 0:
            raise SensorTowerConfigurationError("Sensor Tower timeout must be positive")

        self._auth_token = resolve_auth_token(auth_token)
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
        )

    def __repr__(self) -> str:
        """Represent client configuration without exposing the auth token."""

        return f"SensorTowerClient(base_url={self._base_url!r}, timeout={self._timeout!r})"

    def fetch_market_candidates(
        self,
        request: SensorTowerMarketRequest,
    ) -> list[SensorTowerMarketRecord]:
        """Fetch and parse one market response without pagination or retries."""

        LOGGER.info(
            "requesting Sensor Tower market candidates: endpoint=%s date=%s end_date=%s limit=%s",
            SENSOR_TOWER_MARKET_ENDPOINT_PATH,
            request.date.isoformat(),
            request.end_date.isoformat(),
            request.api_limit,
        )

        try:
            with _suppress_httpx_request_logging():
                response = self._client.get(
                    SENSOR_TOWER_MARKET_ENDPOINT_PATH,
                    params=request.to_query_params(self._auth_token),
                )
        except httpx.TimeoutException as error:
            raise SensorTowerTimeoutError() from error
        except httpx.RequestError as error:
            raise SensorTowerRequestError("Sensor Tower market request failed") from error

        if not 200 <= response.status_code < 300:
            raise SensorTowerHTTPError(response.status_code)

        try:
            payload = response.json()
        except ValueError as error:
            raise SensorTowerMalformedResponseError(
                "Sensor Tower response did not contain valid JSON"
            ) from error

        try:
            return parse_market_response(payload)
        except (TypeError, ValueError) as error:
            raise SensorTowerMalformedResponseError(
                "Sensor Tower response did not match the verified market record shape"
            ) from error

    def close(self) -> None:
        """Close the underlying HTTP client."""

        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


@contextmanager
def _suppress_httpx_request_logging() -> Iterator[None]:
    """Prevent HTTPX/httpcore full-request logs from exposing the query token."""

    request_loggers = (logging.getLogger("httpx"), logging.getLogger("httpcore"))
    previous_levels = tuple((logger, logger.level) for logger in request_loggers)
    for logger, _ in previous_levels:
        logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        for logger, previous_level in previous_levels:
            logger.setLevel(previous_level)
