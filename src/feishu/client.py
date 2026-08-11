"""Strictly read-only HTTP client for Feishu authentication and field metadata."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from types import TracebackType
from typing import Self, cast
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from .errors import (
    FeishuAPIError,
    FeishuAuthenticationError,
    FeishuConfigurationError,
    FeishuFieldIntegrityError,
    FeishuHTTPError,
    FeishuMalformedResponseError,
    FeishuRequestError,
    FeishuTimeoutError,
)
from .models import (
    FEISHU_AUTHENTICATION_PATH,
    FEISHU_FIELD_PAGE_SIZE,
    FEISHU_FIELDS_PATH_PREFIX,
    FeishuAccessToken,
    FeishuBitableField,
    FeishuClientConfig,
)

LOGGER = logging.getLogger(__name__)


class FeishuClient:
    """Synchronous Feishu client with injectable mock transport.

    The client deliberately implements only tenant-token authentication and the
    Bitable field-list GET endpoint required by FEISHU-001.
    """

    def __init__(
        self,
        config: FeishuClientConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._app_id = config.app_id
        self._app_secret = config.app_secret
        self._base_url = config.base_url
        self._timeout = config.timeout_seconds
        self._tenant_access_token: SecretStr | None = None
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=transport,
        )

    @classmethod
    def from_config(
        cls,
        config: FeishuClientConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> FeishuClient:
        """Construct a client from one validated required configuration."""

        return cls(config, transport=transport)

    def __repr__(self) -> str:
        """Represent client state without credentials, target tokens, or auth URLs."""

        return (
            f"FeishuClient(base_url={self._base_url!r}, timeout={self._timeout!r}, "
            f"authenticated={self._tenant_access_token is not None})"
        )

    def get_tenant_access_token(self) -> FeishuAccessToken:
        """Authenticate once and retain the tenant token only in memory."""

        LOGGER.info("requesting Feishu tenant access token")
        request_body = {
            "app_id": self._app_id,
            "app_secret": self._app_secret.get_secret_value(),
        }
        response = self._post_authentication(request_body)
        payload = self._decode_json(response, operation="authentication", authentication=True)
        code = self._response_code(payload, operation="authentication", authentication=True)
        if code != 0:
            raise FeishuAuthenticationError(
                f"Feishu authentication failed with response code {code}"
            )

        token_value = payload.get("tenant_access_token")
        if not isinstance(token_value, str) or not token_value.strip():
            raise FeishuMalformedResponseError("authentication")

        expire_value = payload.get("expire")
        if expire_value is not None and (
            isinstance(expire_value, bool)
            or not isinstance(expire_value, int)
            or expire_value < 0
        ):
            raise FeishuMalformedResponseError("authentication")

        token = FeishuAccessToken(
            tenant_access_token=SecretStr(token_value),
            expire=expire_value,
        )

        self._tenant_access_token = token.tenant_access_token
        return token

    def list_fields(
        self,
        *,
        app_token: str,
        table_id: str,
        view_id: str | None = None,
    ) -> list[FeishuBitableField]:
        """List every field in one Bitable table using GET-only pagination."""

        self._validate_target(app_token=app_token, table_id=table_id, view_id=view_id)
        tenant_access_token = self._require_tenant_access_token()
        field_path = self._fields_path(app_token=app_token, table_id=table_id)
        fields: list[FeishuBitableField] = []
        field_ids: set[str] = set()
        page_token: str | None = None
        seen_page_tokens: set[str] = set()

        while True:
            params: dict[str, str | int] = {"page_size": FEISHU_FIELD_PAGE_SIZE}
            if view_id is not None:
                params["view_id"] = view_id
            if page_token is not None:
                params["page_token"] = page_token

            response = self._get_fields_page(
                field_path,
                tenant_access_token=tenant_access_token,
                params=params,
            )
            payload = self._decode_json(response, operation="field inspection")
            code = self._response_code(payload, operation="field inspection")
            if code != 0:
                raise FeishuAPIError("field inspection", code)

            data = payload.get("data")
            if not isinstance(data, Mapping):
                raise FeishuMalformedResponseError("field inspection")
            items = data.get("items")
            if not isinstance(items, list):
                raise FeishuMalformedResponseError("field inspection")

            for item in items:
                field = self._parse_field(item)
                if field.field_id in field_ids:
                    raise FeishuFieldIntegrityError(
                        "Feishu Bitable field list contains a duplicate field_id"
                    )
                field_ids.add(field.field_id)
                fields.append(field)

            raw_has_more = data.get("has_more")
            if raw_has_more is not None and not isinstance(raw_has_more, bool):
                raise FeishuMalformedResponseError("field inspection")
            raw_next_page_token = data.get("page_token")
            if raw_next_page_token is not None and not isinstance(raw_next_page_token, str):
                raise FeishuMalformedResponseError("field inspection")
            next_page_token = raw_next_page_token or None
            if raw_has_more is False or next_page_token is None:
                break
            if next_page_token in seen_page_tokens:
                raise FeishuFieldIntegrityError(
                    "Feishu Bitable field pagination repeated a page token"
                )
            seen_page_tokens.add(next_page_token)
            page_token = next_page_token

        duplicate_names = _duplicate_names(fields)
        if duplicate_names:
            LOGGER.warning(
                "Feishu Bitable field list contains duplicate field names: count=%d",
                len(duplicate_names),
            )
        return fields

    def _post_authentication(self, request_body: dict[str, str]) -> httpx.Response:
        """Send the one permitted POST request without logging its JSON body."""

        request_failure: str | None = None
        try:
            with _suppress_httpx_request_logging():
                response = self._client.post(
                    FEISHU_AUTHENTICATION_PATH,
                    json=request_body,
                )
        except httpx.TimeoutException:
            request_failure = "timeout"
        except httpx.RequestError:
            request_failure = "request"

        if request_failure == "timeout":
            raise FeishuAuthenticationError(
                "Feishu authentication request timed out"
            ) from None
        if request_failure == "request":
            raise FeishuAuthenticationError("Feishu authentication request failed") from None

        if not 200 <= response.status_code < 300:
            raise FeishuAuthenticationError(
                "Feishu authentication failed with "
                f"HTTP status {response.status_code}"
            )
        return response

    def _get_fields_page(
        self,
        field_path: str,
        *,
        tenant_access_token: str,
        params: dict[str, str | int],
    ) -> httpx.Response:
        """Send one authenticated Bitable field-list GET request."""

        request_failure: str | None = None
        try:
            with _suppress_httpx_request_logging():
                response = self._client.get(
                    field_path,
                    headers={"Authorization": f"Bearer {tenant_access_token}"},
                    params=params,
                )
        except httpx.TimeoutException:
            request_failure = "timeout"
        except httpx.RequestError:
            request_failure = "request"

        if request_failure == "timeout":
            raise FeishuTimeoutError("field inspection") from None
        if request_failure == "request":
            raise FeishuRequestError("Feishu field inspection request failed") from None

        if not 200 <= response.status_code < 300:
            raise FeishuHTTPError("field inspection", response.status_code)
        return response

    @staticmethod
    def _decode_json(
        response: httpx.Response,
        *,
        operation: str,
        authentication: bool = False,
    ) -> Mapping[str, object]:
        """Decode one response without retaining raw bodies or decoder context."""

        decoding_failed = False
        try:
            payload = response.json()
        except (TypeError, ValueError):
            decoding_failed = True
            payload = None
        if decoding_failed:
            if authentication:
                raise FeishuAuthenticationError(
                    "Feishu authentication response was not valid JSON"
                ) from None
            raise FeishuMalformedResponseError(operation) from None
        if not isinstance(payload, Mapping):
            if authentication:
                raise FeishuAuthenticationError(
                    "Feishu authentication response was malformed"
                ) from None
            raise FeishuMalformedResponseError(operation)
        return cast(Mapping[str, object], payload)

    @staticmethod
    def _response_code(
        payload: Mapping[str, object],
        *,
        operation: str,
        authentication: bool = False,
    ) -> int:
        """Validate the Feishu response envelope without retaining ``msg``."""

        code = payload.get("code")
        if isinstance(code, bool) or not isinstance(code, int):
            if authentication:
                raise FeishuAuthenticationError(
                    "Feishu authentication response was malformed"
                ) from None
            raise FeishuMalformedResponseError(operation)
        return code

    @staticmethod
    def _parse_field(item: object) -> FeishuBitableField:
        """Map only approved field metadata and discard the raw property object."""

        if not isinstance(item, Mapping):
            raise FeishuMalformedResponseError("field inspection")
        field_id = item.get("field_id")
        field_name = item.get("field_name")
        field_type = item.get("type")
        if not isinstance(field_id, str) or not field_id.strip():
            raise FeishuMalformedResponseError("field inspection")
        if not isinstance(field_name, str):
            raise FeishuMalformedResponseError("field inspection")
        if isinstance(field_type, bool) or not isinstance(field_type, int):
            raise FeishuMalformedResponseError("field inspection")

        ui_type = item.get("ui_type")
        if ui_type is not None and not isinstance(ui_type, str):
            raise FeishuMalformedResponseError("field inspection")
        is_primary = item.get("is_primary")
        if is_primary is not None and not isinstance(is_primary, bool):
            raise FeishuMalformedResponseError("field inspection")

        option_count, option_names = _extract_options(item.get("property"))
        return FeishuBitableField(
            field_id=field_id.strip(),
            field_name=field_name,
            type=field_type,
            ui_type=ui_type,
            is_primary=is_primary,
            option_count=option_count,
            option_names=option_names,
        )

    @staticmethod
    def _fields_path(*, app_token: str, table_id: str) -> str:
        """Build a path with target identifiers URL-encoded only in the path."""

        return (
            f"{FEISHU_FIELDS_PATH_PREFIX}/"
            f"{quote(app_token, safe='')}/tables/{quote(table_id, safe='')}/fields"
        )

    @staticmethod
    def _validate_target(*, app_token: str, table_id: str, view_id: str | None) -> None:
        """Validate target identifiers before any network request."""

        if not isinstance(app_token, str) or not app_token.strip():
            raise FeishuConfigurationError("Feishu Bitable app_token is not configured")
        if not isinstance(table_id, str) or not table_id.strip():
            raise FeishuConfigurationError("Feishu Bitable table_id is not configured")
        if not table_id.startswith("tbl"):
            raise FeishuConfigurationError("Feishu Bitable table_id must begin with tbl")
        if view_id is not None:
            if not isinstance(view_id, str) or not view_id.strip():
                raise FeishuConfigurationError("Feishu Bitable view_id is invalid")
            if not view_id.startswith("vew"):
                raise FeishuConfigurationError("Feishu Bitable view_id must begin with vew")

    def _require_tenant_access_token(self) -> str:
        """Return the in-memory token or fail before a Bitable request."""

        if self._tenant_access_token is None:
            raise FeishuAuthenticationError(
                "Feishu tenant access token is not available; authenticate first"
            )
        return self._tenant_access_token.get_secret_value()

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


def _extract_options(property_value: object) -> tuple[int, tuple[str, ...]]:
    """Extract option metadata without retaining a complete property object."""

    if not isinstance(property_value, Mapping):
        return 0, ()
    raw_options = property_value.get("options")
    if raw_options is None:
        return 0, ()
    if not isinstance(raw_options, list):
        raise FeishuMalformedResponseError("field inspection")

    names: list[str] = []
    for option in raw_options:
        if not isinstance(option, Mapping):
            continue
        name = option.get("name")
        if isinstance(name, str):
            names.append(name)
    return len(raw_options), tuple(names)


def _duplicate_names(fields: list[FeishuBitableField]) -> tuple[str, ...]:
    """Return duplicate non-empty field names in response order."""

    counts: dict[str, int] = {}
    for field in fields:
        if field.field_name:
            counts[field.field_name] = counts.get(field.field_name, 0) + 1
    return tuple(
        dict.fromkeys(
            field.field_name
            for field in fields
            if field.field_name and counts.get(field.field_name, 0) > 1
        )
    )


@contextmanager
def _suppress_httpx_request_logging() -> Iterator[None]:
    """Prevent HTTPX/httpcore logs from exposing auth bodies or headers."""

    request_loggers = (logging.getLogger("httpx"), logging.getLogger("httpcore"))
    previous_levels = tuple((logger, logger.level) for logger in request_loggers)
    for logger, _ in previous_levels:
        logger.setLevel(logging.WARNING)
    try:
        yield
    finally:
        for logger, previous_level in previous_levels:
            logger.setLevel(previous_level)
