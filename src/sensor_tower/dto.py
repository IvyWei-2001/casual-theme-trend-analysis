"""Typed DTOs for the verified Sensor Tower market-response variants.

The DTO deliberately preserves Sensor Tower's source field names.  The meaning
of the unit and revenue values is not resolved here; later adapters must map
them into internal models only after the source contract is confirmed.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel, ConfigDict, field_validator

from ..identifiers import normalize_required_opaque_id

type NumericValue = int | float | None

GAME_THEME_TAG: Final = "Game Theme"
GAME_GENRE_TAG: Final = "Game Genre"
GAME_SUBGENRE_TAG: Final = "Game Sub-genre"
GAME_PRODUCT_MODEL_TAG: Final = "Game Product Model"
GAME_ART_STYLE_TAG: Final = "Game Art Style"
GAME_SETTING_TAG: Final = "Game Setting"
EARLIEST_RELEASE_DATE_TAG: Final = "Earliest Release Date"
RELEASE_DATE_WW_TAG: Final = "Release Date (WW)"
PUBLISHER_COUNTRY_TAG: Final = "Publisher Country"
IS_UNIFIED_TAG: Final = "Is Unified"
MOST_POPULAR_COUNTRY_BY_REVENUE_TAG: Final = "Most Popular Country by Revenue"

# MONETIZATION-001 uses only these verified Custom Field names.  They are kept
# at the Sensor Tower DTO boundary so the source spelling is defined once, but
# the monetization policy itself remains in the pure analysis layer.
MONETIZATION_ADS_TAG: Final = "Monetization: Ads"
MONETIZATION_AD_REMOVAL_TAG: Final = "Monetization: Ad Removal"
IN_APP_PURCHASES_TAG: Final = "In-App Purchases"
MONETIZATION_LIVE_OPS_TAG: Final = "Monetization: Live Ops"
GAME_IQ_IAP_BUNDLES_TAG: Final = "Game IQ - IAP Bundles"
MONETIZATION_CURRENCY_BUNDLES_TAG: Final = "Monetization: Currency Bundles"
MONETIZATION_SEASON_PASS_TAG: Final = "Monetization: Season Pass"
MONETIZATION_STARTER_PACK_TAG: Final = "Monetization: Starter Pack"
MONETIZATION_SUBSCRIPTION_TAG: Final = "Monetization: Subscription"
IN_APP_SUBSCRIPTION_TAG: Final = "In-App Subscription"
MONETIZATION_LOOT_BOX_TAG: Final = "Monetization: Loot Box"

VERIFIED_CUSTOM_TAG_KEYS: Final[tuple[str, ...]] = (
    GAME_THEME_TAG,
    GAME_GENRE_TAG,
    GAME_SUBGENRE_TAG,
    GAME_PRODUCT_MODEL_TAG,
    GAME_ART_STYLE_TAG,
    GAME_SETTING_TAG,
    EARLIEST_RELEASE_DATE_TAG,
    RELEASE_DATE_WW_TAG,
    PUBLISHER_COUNTRY_TAG,
    IS_UNIFIED_TAG,
    MOST_POPULAR_COUNTRY_BY_REVENUE_TAG,
)

MONETIZATION_VERIFIED_CUSTOM_TAG_KEYS: Final[tuple[str, ...]] = (
    MONETIZATION_ADS_TAG,
    MONETIZATION_AD_REMOVAL_TAG,
    IN_APP_PURCHASES_TAG,
    MONETIZATION_LIVE_OPS_TAG,
    GAME_IQ_IAP_BUNDLES_TAG,
    MONETIZATION_CURRENCY_BUNDLES_TAG,
    MONETIZATION_SEASON_PASS_TAG,
    MONETIZATION_STARTER_PACK_TAG,
    MONETIZATION_SUBSCRIPTION_TAG,
    IN_APP_SUBSCRIPTION_TAG,
    MONETIZATION_LOOT_BOX_TAG,
)
MONETIZATION_MEANINGFUL_IAP_TAG_KEYS: Final[tuple[str, ...]] = (
    GAME_IQ_IAP_BUNDLES_TAG,
    MONETIZATION_CURRENCY_BUNDLES_TAG,
    MONETIZATION_SEASON_PASS_TAG,
    MONETIZATION_STARTER_PACK_TAG,
    MONETIZATION_SUBSCRIPTION_TAG,
    IN_APP_SUBSCRIPTION_TAG,
    MONETIZATION_LOOT_BOX_TAG,
)
MONETIZATION_CONTEXTUAL_TAG_KEYS: Final[tuple[str, ...]] = (
    MONETIZATION_AD_REMOVAL_TAG,
    IN_APP_PURCHASES_TAG,
    MONETIZATION_LIVE_OPS_TAG,
)

_OPTIONAL_DATE_TAGS: Final[tuple[str, ...]] = (
    EARLIEST_RELEASE_DATE_TAG,
    RELEASE_DATE_WW_TAG,
)


@dataclass(frozen=True)
class SensorTowerCustomTags(Mapping[str, object]):
    """Key/value custom tags with typed accessors for verified labels.

    The complete source mapping is retained, including tags that are not yet
    part of this contract.  Known string tags return their raw source value;
    optional release-date helpers parse the observed ``YYYY/MM/DD`` values.
    """

    tag_values: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "tag_values", MappingProxyType(dict(self.tag_values)))

    def __getitem__(self, key: str) -> object:
        return self.tag_values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.tag_values)

    def __len__(self) -> int:
        return len(self.tag_values)

    def _string_value(self, key: str) -> str | None:
        value = self.tag_values.get(key)
        return value if isinstance(value, str) else None

    @staticmethod
    def _parse_optional_date(value: object) -> date | None:
        if not isinstance(value, str) or not value:
            return None

        for format_string in ("%Y/%m/%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, format_string).date()
            except ValueError:
                continue
        return None

    def _date_value(self, key: str) -> date | None:
        return self._parse_optional_date(self.tag_values.get(key))

    @property
    def game_theme(self) -> str | None:
        """Return the raw ``Game Theme`` tag, when present as a string."""

        return self._string_value(GAME_THEME_TAG)

    @property
    def game_genre(self) -> str | None:
        """Return the raw ``Game Genre`` tag, when present as a string."""

        return self._string_value(GAME_GENRE_TAG)

    @property
    def game_subgenre(self) -> str | None:
        """Return the raw ``Game Sub-genre`` tag, when present as a string."""

        return self._string_value(GAME_SUBGENRE_TAG)

    @property
    def game_product_model(self) -> str | None:
        """Return the raw ``Game Product Model`` tag, when present as a string."""

        return self._string_value(GAME_PRODUCT_MODEL_TAG)

    @property
    def game_art_style(self) -> str | None:
        """Return the raw ``Game Art Style`` tag, when present as a string."""

        return self._string_value(GAME_ART_STYLE_TAG)

    @property
    def game_setting(self) -> str | None:
        """Return the raw ``Game Setting`` tag, when present as a string."""

        return self._string_value(GAME_SETTING_TAG)

    @property
    def earliest_release_date(self) -> date | None:
        """Parse ``Earliest Release Date`` when the optional tag is valid."""

        return self._date_value(EARLIEST_RELEASE_DATE_TAG)

    @property
    def release_date_ww(self) -> date | None:
        """Parse ``Release Date (WW)`` when the optional tag is valid."""

        return self._date_value(RELEASE_DATE_WW_TAG)

    @property
    def publisher_country(self) -> str | None:
        """Return the raw ``Publisher Country`` tag, when present as a string."""

        return self._string_value(PUBLISHER_COUNTRY_TAG)

    @property
    def most_popular_country_by_revenue(self) -> str | None:
        """Return the revenue-market tag without assigning publisher semantics."""

        return self._string_value(MOST_POPULAR_COUNTRY_BY_REVENUE_TAG)

    @property
    def is_unified(self) -> str | None:
        """Return the raw ``Is Unified`` value without coercing its semantics."""

        return self._string_value(IS_UNIFIED_TAG)

    def _monetization_value(self, key: str) -> object | None:
        """Return one approved monetization tag without normalizing its value."""

        return self.tag_values.get(key)

    @property
    def monetization_ads(self) -> object | None:
        return self._monetization_value(MONETIZATION_ADS_TAG)

    @property
    def monetization_ad_removal(self) -> object | None:
        return self._monetization_value(MONETIZATION_AD_REMOVAL_TAG)

    @property
    def in_app_purchases(self) -> object | None:
        return self._monetization_value(IN_APP_PURCHASES_TAG)

    @property
    def monetization_live_ops(self) -> object | None:
        return self._monetization_value(MONETIZATION_LIVE_OPS_TAG)

    @property
    def game_iq_iap_bundles(self) -> object | None:
        return self._monetization_value(GAME_IQ_IAP_BUNDLES_TAG)

    @property
    def monetization_currency_bundles(self) -> object | None:
        return self._monetization_value(MONETIZATION_CURRENCY_BUNDLES_TAG)

    @property
    def monetization_season_pass(self) -> object | None:
        return self._monetization_value(MONETIZATION_SEASON_PASS_TAG)

    @property
    def monetization_starter_pack(self) -> object | None:
        return self._monetization_value(MONETIZATION_STARTER_PACK_TAG)

    @property
    def monetization_subscription(self) -> object | None:
        return self._monetization_value(MONETIZATION_SUBSCRIPTION_TAG)

    @property
    def in_app_subscription(self) -> object | None:
        return self._monetization_value(IN_APP_SUBSCRIPTION_TAG)

    @property
    def monetization_loot_box(self) -> object | None:
        return self._monetization_value(MONETIZATION_LOOT_BOX_TAG)

    @property
    def optional_date_validation_errors(self) -> tuple[str, ...]:
        """Describe invalid optional date tags while keeping parsing non-fatal."""

        errors: list[str] = []
        for key in _OPTIONAL_DATE_TAGS:
            value = self.tag_values.get(key)
            if value is not None and self._parse_optional_date(value) is None:
                errors.append(f"{key} must be a valid date in YYYY/MM/DD format")
        return tuple(errors)


class SensorTowerMarketRecord(BaseModel):
    """One verified Sensor Tower market response row.

    Additional top-level fields are accepted and retained by Pydantic so the
    earlier sample and current live response can share one DTO. Optional
    source metrics remain unavailable when a response variant omits them. No
    internal ``downloads`` or ``revenue`` fields are defined because the source
    metric semantics remain unverified.
    """

    model_config = ConfigDict(
        extra="allow",
        arbitrary_types_allowed=True,
        hide_input_in_errors=True,
    )

    app_id: str
    country: str | None = None
    date: datetime
    current_units_value: NumericValue = None
    units_absolute: NumericValue = None
    comparison_units_value: NumericValue = None
    units_delta: NumericValue = None
    units_transformed_delta: NumericValue = None
    current_revenue_value: NumericValue = None
    revenue_absolute: NumericValue = None
    comparison_revenue_value: NumericValue = None
    revenue_delta: NumericValue = None
    revenue_transformed_delta: NumericValue = None
    absolute: NumericValue = None
    delta: NumericValue = None
    transformed_delta: NumericValue = None
    custom_tags: SensorTowerCustomTags

    @field_validator("app_id", mode="before")
    @classmethod
    def _normalize_app_id(cls, value: object) -> str:
        return normalize_required_opaque_id(value, field_name="app_id")

    @field_validator("custom_tags", mode="before")
    @classmethod
    def _validate_custom_tags(cls, value: object) -> SensorTowerCustomTags:
        if isinstance(value, SensorTowerCustomTags):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("custom_tags must be a key/value mapping")

        values: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("custom_tags keys must be strings")
            values[key] = item
        return SensorTowerCustomTags(values)

    @field_validator("date")
    @classmethod
    def _require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("date must be timezone-aware")
        return value

    @property
    def game_theme(self) -> str | None:
        """Return the optional raw Game Theme tag."""

        return self.custom_tags.game_theme

    @property
    def game_genre(self) -> str | None:
        """Return the optional raw Game Genre tag."""

        return self.custom_tags.game_genre

    @property
    def most_popular_country_by_revenue(self) -> str | None:
        """Return the optional revenue-market tag from normalized custom tags."""

        return self.custom_tags.most_popular_country_by_revenue


def get_most_popular_country_by_revenue(record: SensorTowerMarketRecord) -> str | None:
    """Return the revenue-market tag, never treating it as publisher country."""

    return record.most_popular_country_by_revenue
