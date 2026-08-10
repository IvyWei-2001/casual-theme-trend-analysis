"""HTTP client for the verified Sensor Tower market endpoint."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

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
    DEFAULT_SENSOR_TOWER_ENDPOINT_PATH,
    DEFAULT_SENSOR_TOWER_TIMEOUT_SECONDS,
    SensorTowerMarketRequest,
    SensorTowerRequestConfig,
    resolve_auth_token,
)

LOGGER = logging.getLogger(__name__)


class SensorTowerClientConfig(BaseModel):
    """Validated configuration required to construct a Sensor Tower client."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = DEFAULT_SENSOR_TOWER_BASE_URL
    endpoint_path: str = DEFAULT_SENSOR_TOWER_ENDPOINT_PATH
    auth_token: SecretStr
    timeout: float = Field(default=DEFAULT_SENSOR_TOWER_TIMEOUT_SECONDS, gt=0)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Sensor Tower API base URL is not configured")
        return cleaned.rstrip("/")

    @field_validator("endpoint_path")
    @classmethod
    def _validate_endpoint_path(cls, value: str) -> str:
        return SensorTowerRequestConfig(endpoint_path=value).endpoint_path


class SensorTowerClient:
    """Synchronous Sensor Tower market client with injectable HTTP transport."""

    def __init__(
        self,
        auth_token: SecretStr | str,
        *,
        base_url: str = DEFAULT_SENSOR_TOWER_BASE_URL,
        endpoint_path: str = DEFAULT_SENSOR_TOWER_ENDPOINT_PATH,
        timeout: float = DEFAULT_SENSOR_TOWER_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise SensorTowerConfigurationError("Sensor Tower API base URL is not configured")
        if timeout <= 0:
            raise SensorTowerConfigurationError("Sensor Tower timeout must be positive")

        self._auth_token = resolve_auth_token(auth_token)
        self._base_url = base_url.rstrip("/")
        self._endpoint_path = SensorTowerRequestConfig(endpoint_path=endpoint_path).endpoint_path
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_config(
        cls,
        config: SensorTowerClientConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> SensorTowerClient:
        """Construct a client from one validated application configuration."""

        return cls(
            config.auth_token,
            base_url=config.base_url,
            endpoint_path=config.endpoint_path,
            timeout=config.timeout,
            transport=transport,
        )

    def __repr__(self) -> str:
        """Represent client configuration without exposing the auth token."""

        return (
            f"SensorTowerClient(base_url={self._base_url!r}, "
            f"endpoint_path={self._endpoint_path!r}, timeout={self._timeout!r})"
        )

    def fetch_market_candidates(
        self,
        request: SensorTowerMarketRequest,
    ) -> list[SensorTowerMarketRecord]:
        """Fetch and parse one market response without pagination or retries."""

        if request.endpoint_path != self._endpoint_path:
            raise SensorTowerConfigurationError(
                "Sensor Tower request endpoint path does not match client endpoint path"
            )

        LOGGER.info(
            "requesting Sensor Tower market candidates: endpoint=%s date=%s end_date=%s limit=%s",
            self._endpoint_path,
            request.date.isoformat(),
            request.end_date.isoformat(),
            request.api_limit,
        )

        response, request_error = self._get_response(request)
        if request_error is not None:
            raise request_error
        if response is None:
            raise SensorTowerRequestError("Sensor Tower market request failed")

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

    def _get_response(
        self,
        request: SensorTowerMarketRequest,
    ) -> tuple[httpx.Response | None, SensorTowerRequestError | None]:
        """Return a response or a sanitized error after the HTTP exception scope ends."""

        try:
            with _suppress_httpx_request_logging():
                return self._client.get(
                    self._endpoint_path,
                    params=request.to_query_params(self._auth_token),
                ), None
        except httpx.TimeoutException:
            return None, SensorTowerTimeoutError()
        except httpx.RequestError:
            return None, SensorTowerRequestError("Sensor Tower market request failed")

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
