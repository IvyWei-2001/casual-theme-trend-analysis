"""Sensor Tower request, parsing, client, and selection boundaries."""

from .client import SensorTowerClient
from .dto import (
    SensorTowerCustomTags,
    SensorTowerMarketRecord,
    get_most_popular_country_by_revenue,
)
from .errors import (
    NoEligibleMarketRecordsError,
    SensorTowerConfigurationError,
    SensorTowerError,
    SensorTowerHTTPError,
    SensorTowerMalformedResponseError,
    SensorTowerRequestError,
    SensorTowerSelectionConfigurationError,
    SensorTowerTimeoutError,
)
from .parser import (
    load_market_response_file,
    parse_market_response,
    parse_market_response_file,
)
from .request import (
    DEFAULT_SENSOR_TOWER_ALLOWED_GENRES,
    DEFAULT_SENSOR_TOWER_API_LIMIT,
    DEFAULT_SENSOR_TOWER_BASE_URL,
    DEFAULT_SENSOR_TOWER_CATEGORY,
    DEFAULT_SENSOR_TOWER_COUNTRY,
    DEFAULT_SENSOR_TOWER_EXCLUDE_CHINA_REVENUE_MARKET,
    DEFAULT_SENSOR_TOWER_FINAL_TOP_N,
    DEFAULT_SENSOR_TOWER_SCOPE_NAME,
    DEFAULT_SENSOR_TOWER_TIMEOUT_SECONDS,
    SENSOR_TOWER_MARKET_ENDPOINT_PATH,
    SensorTowerCustomFieldFilter,
    SensorTowerCustomFieldsFilter,
    SensorTowerMarketRequest,
    SensorTowerSelectionConfig,
    build_market_request,
    resolve_auth_token,
)
from .selection import fetch_and_select_market_records, select_market_records

__all__ = [
    "SensorTowerCustomTags",
    "SensorTowerMarketRecord",
    "get_most_popular_country_by_revenue",
    "SensorTowerClient",
    "SensorTowerError",
    "SensorTowerConfigurationError",
    "SensorTowerRequestError",
    "SensorTowerHTTPError",
    "SensorTowerTimeoutError",
    "SensorTowerMalformedResponseError",
    "SensorTowerSelectionConfigurationError",
    "NoEligibleMarketRecordsError",
    "SensorTowerCustomFieldFilter",
    "SensorTowerCustomFieldsFilter",
    "SensorTowerMarketRequest",
    "SensorTowerSelectionConfig",
    "build_market_request",
    "resolve_auth_token",
    "select_market_records",
    "fetch_and_select_market_records",
    "DEFAULT_SENSOR_TOWER_BASE_URL",
    "DEFAULT_SENSOR_TOWER_API_LIMIT",
    "DEFAULT_SENSOR_TOWER_FINAL_TOP_N",
    "DEFAULT_SENSOR_TOWER_EXCLUDE_CHINA_REVENUE_MARKET",
    "DEFAULT_SENSOR_TOWER_TIMEOUT_SECONDS",
    "SENSOR_TOWER_MARKET_ENDPOINT_PATH",
    "DEFAULT_SENSOR_TOWER_CATEGORY",
    "DEFAULT_SENSOR_TOWER_COUNTRY",
    "DEFAULT_SENSOR_TOWER_ALLOWED_GENRES",
    "DEFAULT_SENSOR_TOWER_SCOPE_NAME",
    "load_market_response_file",
    "parse_market_response",
    "parse_market_response_file",
]
