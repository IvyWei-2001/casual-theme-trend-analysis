"""Pure MONETIZATION-001 models and product-level classification policy.

This module accepts already parsed Custom Field mappings and stored snapshot-like
rows.  It deliberately has no configuration, network, DuckDB, Feishu, or
external-service dependency.
"""

from __future__ import annotations

import calendar
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isclose, isfinite
from typing import Final, Literal, Protocol

from ..identifiers import normalize_required_opaque_id
from ..sensor_tower.dto import (
    GAME_IQ_IAP_BUNDLES_TAG,
    IN_APP_PURCHASES_TAG,
    IN_APP_SUBSCRIPTION_TAG,
    MONETIZATION_AD_REMOVAL_TAG,
    MONETIZATION_ADS_TAG,
    MONETIZATION_CURRENCY_BUNDLES_TAG,
    MONETIZATION_LIVE_OPS_TAG,
    MONETIZATION_LOOT_BOX_TAG,
    MONETIZATION_MEANINGFUL_IAP_TAG_KEYS,
    MONETIZATION_SEASON_PASS_TAG,
    MONETIZATION_STARTER_PACK_TAG,
    MONETIZATION_SUBSCRIPTION_TAG,
    MONETIZATION_VERIFIED_CUSTOM_TAG_KEYS,
)
from .errors import MonetizationValidationError

MONETIZATION_POLICY_VERSION: Final = "MONETIZATION001_V1"

type BooleanState = Literal["true", "false", "unknown", "invalid"]
type Cadence = Literal["monthly", "weekly"]
type MeaningfulIapEvidenceState = Literal["present", "absent", "unknown", "invalid"]
type MonetizationMixProxy = Literal[
    "ads_dominant_candidate",
    "hybrid_candidate",
    "iap_dominant_candidate",
    "unknown",
]
type ObservableRevenueApplicability = Literal["low", "partial", "higher", "unknown"]
type ClassificationReason = Literal[
    "source_record_unmatched",
    "invalid_classification_signal",
    "ads_without_meaningful_iap",
    "ads_with_meaningful_iap",
    "no_ads_with_meaningful_iap",
    "ads_state_unknown",
    "no_meaningful_monetization_signal",
    "classification_signal_inconclusive",
]

BOOLEAN_STATES: Final[frozenset[str]] = frozenset(
    {"true", "false", "unknown", "invalid"}
)
MONETIZATION_MIX_PROXIES: Final[tuple[MonetizationMixProxy, ...]] = (
    "ads_dominant_candidate",
    "hybrid_candidate",
    "iap_dominant_candidate",
    "unknown",
)
OBSERVABLE_REVENUE_APPLICABILITIES: Final[
    tuple[ObservableRevenueApplicability, ...]
] = ("low", "partial", "higher", "unknown")
MEANINGFUL_IAP_EVIDENCE_STATES: Final[
    tuple[MeaningfulIapEvidenceState, ...]
] = ("present", "absent", "unknown", "invalid")
CLASSIFICATION_REASONS: Final[tuple[ClassificationReason, ...]] = (
    "source_record_unmatched",
    "invalid_classification_signal",
    "ads_without_meaningful_iap",
    "ads_with_meaningful_iap",
    "no_ads_with_meaningful_iap",
    "ads_state_unknown",
    "no_meaningful_monetization_signal",
    "classification_signal_inconclusive",
)
MONETIZATION_PROXY_ORDER: Final[tuple[MonetizationMixProxy, ...]] = (
    "ads_dominant_candidate",
    "hybrid_candidate",
    "iap_dominant_candidate",
    "unknown",
)

_MISSING_SOURCE_VALUE: Final[object] = object()
_PROFILE_STATE_FIELDS: Final[tuple[str, ...]] = (
    "ads_state",
    "ad_removal_state",
    "in_app_purchases_state",
    "iap_bundles_state",
    "currency_bundles_state",
    "season_pass_state",
    "starter_pack_state",
    "subscription_state",
    "in_app_subscription_state",
    "loot_box_state",
    "live_ops_state",
)


class MarketSnapshotLike(Protocol):
    """Structural input contract used by the pure profile builder."""

    @property
    def scope_name(self) -> str: ...

    @property
    def cadence(self) -> str: ...

    @property
    def period_start(self) -> date: ...

    @property
    def period_end(self) -> date: ...

    @property
    def source_app_id(self) -> str: ...

    @property
    def unified_app_id(self) -> str: ...

    @property
    def game_theme(self) -> str | None: ...

    @property
    def game_product_model(self) -> str | None: ...

    @property
    def units_absolute(self) -> float | None: ...

    @property
    def revenue_absolute(self) -> float | None: ...


def normalize_source_boolean_state(value: object = _MISSING_SOURCE_VALUE) -> BooleanState:
    """Normalize one verified Boolean-like Custom Field without coercion.

    Missing and ``None`` are deliberately distinct from false in the source
    contract, while values such as integers, lists, and arbitrary strings are
    retained as invalid signals.
    """

    if value is _MISSING_SOURCE_VALUE or value is None:
        return "unknown"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str:
        normalized = value.strip().casefold()
        if normalized == "true":
            return "true"
        if normalized == "false":
            return "false"
    return "invalid"


def count_meaningful_iap_mechanisms(
    states: Mapping[str, BooleanState],
) -> int:
    """Count only the seven approved meaningful IAP mechanisms."""

    return sum(states.get(key) == "true" for key in MONETIZATION_MEANINGFUL_IAP_TAG_KEYS)


def classify_meaningful_iap_evidence(
    meaningful_iap_states: Sequence[BooleanState],
) -> MeaningfulIapEvidenceState:
    """Classify seven meaningful-IAP signals without treating missing as false."""

    states = _validate_meaningful_iap_states(meaningful_iap_states)
    if "invalid" in states:
        return "invalid"
    if "true" in states:
        return "present"
    if all(state == "false" for state in states):
        return "absent"
    return "unknown"


def classify_product_monetization_proxy(
    ads_state: BooleanState,
    meaningful_iap_states: Sequence[BooleanState],
    *,
    source_record_matched: bool = True,
) -> tuple[MonetizationMixProxy, ObservableRevenueApplicability, ClassificationReason]:
    """Apply the MONETIZATION001_V1 product policy in its specified order."""

    if type(source_record_matched) is not bool:
        raise MonetizationValidationError("source_record_matched must be a Boolean")
    if not isinstance(ads_state, str) or ads_state not in BOOLEAN_STATES:
        raise MonetizationValidationError("classification states are not supported")
    evidence_state = classify_meaningful_iap_evidence(meaningful_iap_states)

    if not source_record_matched:
        return "unknown", "unknown", "source_record_unmatched"

    if ads_state == "invalid" or evidence_state == "invalid":
        return "unknown", "unknown", "invalid_classification_signal"

    if ads_state == "true" and evidence_state == "present":
        return "hybrid_candidate", "partial", "ads_with_meaningful_iap"
    if ads_state == "true" and evidence_state == "absent":
        return "ads_dominant_candidate", "low", "ads_without_meaningful_iap"
    if ads_state == "false" and evidence_state == "present":
        return "iap_dominant_candidate", "higher", "no_ads_with_meaningful_iap"
    if ads_state == "unknown":
        return "unknown", "unknown", "ads_state_unknown"
    if evidence_state == "absent":
        return "unknown", "unknown", "no_meaningful_monetization_signal"
    return "unknown", "unknown", "classification_signal_inconclusive"


# Short aliases make the pure policy convenient to use from focused callers.
classify_monetization_proxy = classify_product_monetization_proxy


@dataclass(frozen=True, slots=True)
class AppMonetizationProfile:
    """One prospective product-level monetization evidence profile."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    source_app_id: str
    unified_app_id: str
    game_theme: str | None
    game_product_model: str | None
    monetization_policy_version: str
    source_record_matched: bool
    verified_source_tags_json: str
    source_tag_present_count: int
    source_tag_invalid_count: int
    ads_state: BooleanState
    ad_removal_state: BooleanState
    in_app_purchases_state: BooleanState
    iap_bundles_state: BooleanState
    currency_bundles_state: BooleanState
    season_pass_state: BooleanState
    starter_pack_state: BooleanState
    subscription_state: BooleanState
    in_app_subscription_state: BooleanState
    loot_box_state: BooleanState
    live_ops_state: BooleanState
    meaningful_iap_mechanism_count: int
    meaningful_iap_evidence_state: MeaningfulIapEvidenceState
    monetization_mix_proxy: MonetizationMixProxy
    observable_revenue_applicability: ObservableRevenueApplicability
    classification_reason: ClassificationReason
    observed_at: datetime

    @property
    def period_key(self) -> tuple[str, str, date, date]:
        """Return the stored market-period identity."""

        return (self.scope_name, self.cadence, self.period_start, self.period_end)

    @property
    def meaningful_iap_states(self) -> tuple[BooleanState, ...]:
        """Return the seven meaningful-IAP states in source-contract order."""

        return (
            self.iap_bundles_state,
            self.currency_bundles_state,
            self.season_pass_state,
            self.starter_pack_state,
            self.subscription_state,
            self.in_app_subscription_state,
            self.loot_box_state,
        )

    def __post_init__(self) -> None:
        _require_text(self.scope_name, field_name="scope_name")
        if self.cadence != "monthly":
            raise MonetizationValidationError("cadence must equal monthly")
        _require_natural_month(self.period_start, self.period_end)
        for field_name in ("source_app_id", "unified_app_id"):
            _normalize_id(getattr(self, field_name), field_name=field_name)
        if self.game_theme is not None and not isinstance(self.game_theme, str):
            raise MonetizationValidationError("game_theme must be a string or NULL")
        if self.game_product_model is not None and not isinstance(self.game_product_model, str):
            raise MonetizationValidationError("game_product_model must be a string or NULL")
        if self.monetization_policy_version != MONETIZATION_POLICY_VERSION:
            raise MonetizationValidationError("monetization_policy_version is not supported")
        if type(self.source_record_matched) is not bool:
            raise MonetizationValidationError("source_record_matched must be a Boolean")
        _require_timestamp(self.observed_at, field_name="observed_at")

        try:
            raw_tags = json.loads(self.verified_source_tags_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise MonetizationValidationError(
                "verified_source_tags_json must be canonical JSON"
            ) from error
        if not isinstance(raw_tags, dict):
            raise MonetizationValidationError("verified_source_tags_json must contain an object")
        if any(key not in MONETIZATION_VERIFIED_CUSTOM_TAG_KEYS for key in raw_tags):
            raise MonetizationValidationError(
                "verified_source_tags_json contains an unapproved tag"
            )
        if _canonical_json(raw_tags) != self.verified_source_tags_json:
            raise MonetizationValidationError("verified_source_tags_json must be canonical JSON")

        present_count = _require_count(
            self.source_tag_present_count,
            field_name="source_tag_present_count",
        )
        invalid_count = _require_count(
            self.source_tag_invalid_count,
            field_name="source_tag_invalid_count",
        )
        if present_count != len(raw_tags):
            raise MonetizationValidationError("source_tag_present_count does not match raw tags")
        if invalid_count > present_count:
            raise MonetizationValidationError("source_tag_invalid_count exceeds present tags")
        if present_count > len(MONETIZATION_VERIFIED_CUSTOM_TAG_KEYS):
            raise MonetizationValidationError("source_tag_present_count exceeds approved tags")
        expected_invalid_count = sum(
            normalize_source_boolean_state(raw_tags[key]) == "invalid" for key in raw_tags
        )
        if invalid_count != expected_invalid_count:
            raise MonetizationValidationError("source_tag_invalid_count is inconsistent")

        for field_name in _PROFILE_STATE_FIELDS:
            state = getattr(self, field_name)
            if not isinstance(state, str) or state not in BOOLEAN_STATES:
                raise MonetizationValidationError(f"{field_name} is not a supported state")
        meaningful_count = _require_count(
            self.meaningful_iap_mechanism_count,
            field_name="meaningful_iap_mechanism_count",
        )
        if meaningful_count > len(MONETIZATION_MEANINGFUL_IAP_TAG_KEYS):
            raise MonetizationValidationError("meaningful_iap_mechanism_count exceeds seven")
        if meaningful_count != count_meaningful_iap_mechanisms(
            dict(zip(MONETIZATION_MEANINGFUL_IAP_TAG_KEYS, self.meaningful_iap_states, strict=True))
        ):
            raise MonetizationValidationError("meaningful_iap_mechanism_count is inconsistent")
        if (
            not isinstance(self.meaningful_iap_evidence_state, str)
            or self.meaningful_iap_evidence_state not in MEANINGFUL_IAP_EVIDENCE_STATES
        ):
            raise MonetizationValidationError("meaningful_iap_evidence_state is not supported")
        if self.meaningful_iap_evidence_state != classify_meaningful_iap_evidence(
            self.meaningful_iap_states
        ):
            raise MonetizationValidationError(
                "meaningful_iap_evidence_state is inconsistent"
            )
        if (
            not isinstance(self.monetization_mix_proxy, str)
            or self.monetization_mix_proxy not in MONETIZATION_MIX_PROXIES
        ):
            raise MonetizationValidationError("monetization_mix_proxy is not supported")
        if (
            not isinstance(self.observable_revenue_applicability, str)
            or self.observable_revenue_applicability not in OBSERVABLE_REVENUE_APPLICABILITIES
        ):
            raise MonetizationValidationError("observable_revenue_applicability is not supported")
        if (
            not isinstance(self.classification_reason, str)
            or self.classification_reason not in CLASSIFICATION_REASONS
        ):
            raise MonetizationValidationError("classification_reason is not supported")

        expected_proxy, expected_applicability, expected_reason = (
            classify_product_monetization_proxy(
                self.ads_state,
                self.meaningful_iap_states,
                source_record_matched=self.source_record_matched,
            )
        )
        if (
            self.monetization_mix_proxy,
            self.observable_revenue_applicability,
            self.classification_reason,
        ) != (expected_proxy, expected_applicability, expected_reason):
            raise MonetizationValidationError("product monetization evidence is inconsistent")
        if not self.source_record_matched:
            if (
                self.verified_source_tags_json != "{}"
                or self.source_tag_present_count != 0
                or self.source_tag_invalid_count != 0
                or any(
                    getattr(self, field_name) != "unknown"
                    for field_name in _PROFILE_STATE_FIELDS
                )
            ):
                raise MonetizationValidationError("unmatched profiles must contain unknown states")


@dataclass(frozen=True, slots=True)
class ThemeMonetizationObservabilityMetric:
    """Downloads-weighted observable-Revenue evidence for one raw theme."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    monetization_policy_version: str
    product_count: int
    downloads_coverage_count: int
    downloads_sum: float | None
    observable_revenue_usd_coverage_count: int
    observable_revenue_usd_sum: float | None
    source_record_match_count: int
    source_record_match_ratio: float
    ads_signal_known_count: int
    ads_signal_known_ratio: float
    proxy_classified_count: int
    proxy_classified_ratio: float
    invalid_signal_count: int
    ads_dominant_candidate_product_count: int
    ads_dominant_candidate_product_share: float
    hybrid_candidate_product_count: int
    hybrid_candidate_product_share: float
    iap_dominant_candidate_product_count: int
    iap_dominant_candidate_product_share: float
    unknown_product_count: int
    unknown_product_share: float
    ads_dominant_candidate_downloads_sum: float | None
    ads_dominant_candidate_downloads_share: float | None
    hybrid_candidate_downloads_sum: float | None
    hybrid_candidate_downloads_share: float | None
    iap_dominant_candidate_downloads_sum: float | None
    iap_dominant_candidate_downloads_share: float | None
    unknown_downloads_sum: float | None
    unknown_downloads_share: float | None
    ads_dominant_candidate_observable_revenue_usd_sum: float | None
    ads_dominant_candidate_observable_revenue_share: float | None
    hybrid_candidate_observable_revenue_usd_sum: float | None
    hybrid_candidate_observable_revenue_share: float | None
    iap_dominant_candidate_observable_revenue_usd_sum: float | None
    iap_dominant_candidate_observable_revenue_share: float | None
    unknown_observable_revenue_usd_sum: float | None
    unknown_observable_revenue_share: float | None
    calculated_at: datetime

    @property
    def period_key(self) -> tuple[str, str, date, date]:
        return (self.scope_name, self.cadence, self.period_start, self.period_end)

    def __post_init__(self) -> None:
        _require_text(self.scope_name, field_name="scope_name")
        if self.cadence != "monthly":
            raise MonetizationValidationError("cadence must equal monthly")
        _require_natural_month(self.period_start, self.period_end)
        if not isinstance(self.game_theme, str):
            raise MonetizationValidationError("game_theme must be a string")
        if self.monetization_policy_version != MONETIZATION_POLICY_VERSION:
            raise MonetizationValidationError("monetization_policy_version is not supported")
        _require_timestamp(self.calculated_at, field_name="calculated_at")

        product_count = _require_count(self.product_count, field_name="product_count", minimum=1)
        for field_name in (
            "downloads_coverage_count",
            "observable_revenue_usd_coverage_count",
            "source_record_match_count",
            "ads_signal_known_count",
            "proxy_classified_count",
            "invalid_signal_count",
        ):
            value = _require_count(getattr(self, field_name), field_name=field_name)
            if value > product_count:
                raise MonetizationValidationError(f"{field_name} exceeds product_count")
        _validate_sum_coverage(
            self.downloads_coverage_count,
            self.downloads_sum,
            metric_name="downloads",
        )
        _validate_sum_coverage(
            self.observable_revenue_usd_coverage_count,
            self.observable_revenue_usd_sum,
            metric_name="observable_revenue_usd",
        )

        for field_name in (
            "source_record_match_ratio",
            "ads_signal_known_ratio",
            "proxy_classified_ratio",
            "ads_dominant_candidate_product_share",
            "hybrid_candidate_product_share",
            "iap_dominant_candidate_product_share",
            "unknown_product_share",
        ):
            _require_ratio(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "ads_dominant_candidate_downloads_share",
            "hybrid_candidate_downloads_share",
            "iap_dominant_candidate_downloads_share",
            "unknown_downloads_share",
            "ads_dominant_candidate_observable_revenue_share",
            "hybrid_candidate_observable_revenue_share",
            "iap_dominant_candidate_observable_revenue_share",
            "unknown_observable_revenue_share",
        ):
            _require_optional_ratio(getattr(self, field_name), field_name=field_name)

        product_counts = (
            self.ads_dominant_candidate_product_count,
            self.hybrid_candidate_product_count,
            self.iap_dominant_candidate_product_count,
            self.unknown_product_count,
        )
        if (
            sum(_require_count(value, field_name="proxy product count") for value in product_counts)
            != product_count
        ):
            raise MonetizationValidationError("proxy product counts do not reconcile")
        product_shares = (
            self.ads_dominant_candidate_product_share,
            self.hybrid_candidate_product_share,
            self.iap_dominant_candidate_product_share,
            self.unknown_product_share,
        )
        if not isclose(sum(product_shares), 1.0, rel_tol=1e-9, abs_tol=1e-9):
            raise MonetizationValidationError("proxy product shares do not reconcile")
        for count, share in zip(product_counts, product_shares, strict=True):
            if not isclose(share, count / product_count, rel_tol=1e-9, abs_tol=1e-9):
                raise MonetizationValidationError("proxy product share is inconsistent")

        expected_match_ratio = self.source_record_match_count / product_count
        expected_ads_ratio = self.ads_signal_known_count / product_count
        expected_proxy_ratio = self.proxy_classified_count / product_count
        if not isclose(
            self.source_record_match_ratio,
            expected_match_ratio,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise MonetizationValidationError("source_record_match_ratio is inconsistent")
        if not isclose(
            self.ads_signal_known_ratio,
            expected_ads_ratio,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise MonetizationValidationError("ads_signal_known_ratio is inconsistent")
        if not isclose(
            self.proxy_classified_ratio,
            expected_proxy_ratio,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise MonetizationValidationError("proxy_classified_ratio is inconsistent")

        if self.downloads_sum is not None and self.downloads_sum > 0:
            downloads_shares = (
                self.ads_dominant_candidate_downloads_share,
                self.hybrid_candidate_downloads_share,
                self.iap_dominant_candidate_downloads_share,
                self.unknown_downloads_share,
            )
            if any(value is None for value in downloads_shares) or not isclose(
                sum(value for value in downloads_shares if value is not None),
                1.0,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise MonetizationValidationError("Downloads proxy shares do not reconcile")
        if self.observable_revenue_usd_sum is not None and self.observable_revenue_usd_sum > 0:
            revenue_shares = (
                self.ads_dominant_candidate_observable_revenue_share,
                self.hybrid_candidate_observable_revenue_share,
                self.iap_dominant_candidate_observable_revenue_share,
                self.unknown_observable_revenue_share,
            )
            if any(value is None for value in revenue_shares) or not isclose(
                sum(value for value in revenue_shares if value is not None),
                1.0,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise MonetizationValidationError(
                    "observable-Revenue proxy shares do not reconcile"
                )
def build_app_monetization_profiles(
    market_snapshots: Sequence[MarketSnapshotLike],
    source_tags_by_app_id: Mapping[object, object] | Sequence[object],
    *,
    observed_at: datetime,
) -> list[AppMonetizationProfile]:
    """Build exactly one profile for every stored market-snapshot row.

    ``source_tags_by_app_id`` may be a normalized mapping or a sequence of
    Sensor Tower-like records exposing ``app_id`` and ``custom_tags``.  The
    latter convenience is limited to reading already fetched records; this
    function never performs I/O or selection.
    """

    _require_timestamp(observed_at, field_name="observed_at")
    snapshots = tuple(market_snapshots)
    if not snapshots:
        raise MonetizationValidationError("market snapshot population must not be empty")
    source_tags = _normalize_source_tag_records(source_tags_by_app_id)
    seen_source_ids: set[str] = set()
    seen_unified_ids: set[str] = set()
    profiles: list[AppMonetizationProfile] = []
    for snapshot in snapshots:
        source_app_id = _normalize_id(snapshot.source_app_id, field_name="source_app_id")
        unified_app_id = _normalize_id(snapshot.unified_app_id, field_name="unified_app_id")
        if source_app_id in seen_source_ids:
            raise MonetizationValidationError("stored source_app_id values must be unique")
        if unified_app_id in seen_unified_ids:
            raise MonetizationValidationError("stored unified_app_id values must be unique")
        seen_source_ids.add(source_app_id)
        seen_unified_ids.add(unified_app_id)

        matched = source_app_id in source_tags
        tags = source_tags[source_app_id] if matched else {}
        states = _normalized_tag_states(tags)
        meaningful_states = tuple(
            states[key] for key in MONETIZATION_MEANINGFUL_IAP_TAG_KEYS
        )
        meaningful_evidence_state = classify_meaningful_iap_evidence(meaningful_states)
        proxy, applicability, reason = classify_product_monetization_proxy(
            states[MONETIZATION_ADS_TAG],
            meaningful_states,
            source_record_matched=matched,
        )
        present_tags = (
            {key: tags[key] for key in MONETIZATION_VERIFIED_CUSTOM_TAG_KEYS if key in tags}
            if matched
            else {}
        )
        raw_json = _canonical_json(present_tags)
        profiles.append(
            AppMonetizationProfile(
                scope_name=snapshot.scope_name,
                cadence=snapshot.cadence,
                period_start=snapshot.period_start,
                period_end=snapshot.period_end,
                source_app_id=source_app_id,
                unified_app_id=unified_app_id,
                game_theme=snapshot.game_theme,
                game_product_model=snapshot.game_product_model,
                monetization_policy_version=MONETIZATION_POLICY_VERSION,
                source_record_matched=matched,
                verified_source_tags_json=raw_json,
                source_tag_present_count=len(present_tags),
                source_tag_invalid_count=sum(
                    state == "invalid" for state in states.values()
                ),
                ads_state=states[MONETIZATION_ADS_TAG],
                ad_removal_state=states[MONETIZATION_AD_REMOVAL_TAG],
                in_app_purchases_state=states[IN_APP_PURCHASES_TAG],
                iap_bundles_state=states[GAME_IQ_IAP_BUNDLES_TAG],
                currency_bundles_state=states[MONETIZATION_CURRENCY_BUNDLES_TAG],
                season_pass_state=states[MONETIZATION_SEASON_PASS_TAG],
                starter_pack_state=states[MONETIZATION_STARTER_PACK_TAG],
                subscription_state=states[MONETIZATION_SUBSCRIPTION_TAG],
                in_app_subscription_state=states[IN_APP_SUBSCRIPTION_TAG],
                loot_box_state=states[MONETIZATION_LOOT_BOX_TAG],
                live_ops_state=states[MONETIZATION_LIVE_OPS_TAG],
                meaningful_iap_mechanism_count=sum(state == "true" for state in meaningful_states),
                meaningful_iap_evidence_state=meaningful_evidence_state,
                monetization_mix_proxy=proxy,
                observable_revenue_applicability=applicability,
                classification_reason=reason,
                observed_at=observed_at,
            )
        )
    return profiles


def _validate_meaningful_iap_states(
    meaningful_iap_states: Sequence[BooleanState],
) -> tuple[BooleanState, ...]:
    if len(meaningful_iap_states) != len(MONETIZATION_MEANINGFUL_IAP_TAG_KEYS):
        raise MonetizationValidationError("exactly seven meaningful-IAP states are required")
    if any(
        not isinstance(state, str) or state not in BOOLEAN_STATES
        for state in meaningful_iap_states
    ):
        raise MonetizationValidationError("classification states are not supported")
    return tuple(meaningful_iap_states)


def _normalize_source_tag_records(
    source_records: Mapping[object, object] | Sequence[object],
) -> dict[str, Mapping[str, object]]:
    if isinstance(source_records, Mapping):
        items = tuple(source_records.items())
    elif isinstance(source_records, Sequence) and not isinstance(source_records, (str, bytes)):
        sequence_items: list[tuple[object, object]] = []
        for record in source_records:
            if isinstance(record, Mapping):
                app_id = record.get("app_id")
                tags = record.get("custom_tags")
            else:
                app_id = getattr(record, "app_id", None)
                tags = getattr(record, "custom_tags", None)
            if app_id is None:
                raise MonetizationValidationError("fetched source record has no app_id")
            sequence_items.append((app_id, tags))
        items = tuple(sequence_items)
    else:
        raise MonetizationValidationError("source tags must be a mapping or record sequence")

    normalized: dict[str, Mapping[str, object]] = {}
    for raw_app_id, raw_tags in items:
        app_id = _normalize_id(raw_app_id, field_name="source_app_id")
        if app_id in normalized:
            raise MonetizationValidationError("fetched source_app_id values must be unique")
        normalized[app_id] = _coerce_tag_mapping(raw_tags)
    return normalized


def _coerce_tag_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise MonetizationValidationError("fetched source Custom Tags must be a mapping")
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise MonetizationValidationError("source Custom Tag keys must be strings")
        normalized[key] = item
    return normalized


def _normalized_tag_states(tags: Mapping[str, object]) -> dict[str, BooleanState]:
    return {
        key: normalize_source_boolean_state(tags[key] if key in tags else _MISSING_SOURCE_VALUE)
        for key in MONETIZATION_VERIFIED_CUSTOM_TAG_KEYS
    }


def _canonical_json(value: object) -> str:
    return json.dumps(
        _json_safe_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _json_safe_value(value: object) -> object:
    if value is None or type(value) is bool or type(value) is str or type(value) is int:
        return value
    if type(value) is float:
        return value if isfinite(value) else "<unsupported>"
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            return "<unsupported>"
        return {key: _json_safe_value(item) for key, item in value.items()}
    return "<unsupported>"


def _normalize_id(value: object, *, field_name: str) -> str:
    try:
        return normalize_required_opaque_id(value, field_name=field_name)
    except ValueError as error:
        raise MonetizationValidationError(str(error)) from None


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MonetizationValidationError(f"{field_name} must be a non-empty string")
    return value


def _require_date(value: object, *, field_name: str) -> date:
    if type(value) is not date:
        raise MonetizationValidationError(f"{field_name} must be a date")
    return value


def _require_natural_month(period_start: object, period_end: object) -> tuple[date, date]:
    start = _require_date(period_start, field_name="period_start")
    end = _require_date(period_end, field_name="period_end")
    if start.day != 1 or end != date(
        start.year,
        start.month,
        calendar.monthrange(start.year, start.month)[1],
    ):
        raise MonetizationValidationError("period must be one natural calendar month")
    return start, end


def _require_timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MonetizationValidationError(f"{field_name} must be timezone-aware")
    return value


def _require_count(value: object, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MonetizationValidationError(
            f"{field_name} must be an integer greater than or equal to {minimum}"
        )
    return value


def _require_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MonetizationValidationError(f"{field_name} must be a number")
    numeric_value = float(value)
    if not isfinite(numeric_value):
        raise MonetizationValidationError(f"{field_name} must be finite")
    return numeric_value


def _require_ratio(value: object, *, field_name: str) -> float:
    numeric_value = _require_number(value, field_name=field_name)
    if not 0 <= numeric_value <= 1:
        raise MonetizationValidationError(f"{field_name} must be between 0 and 1")
    return numeric_value


def _require_optional_ratio(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    return _require_ratio(value, field_name=field_name)


def _validate_sum_coverage(
    coverage_count: int,
    value: object,
    *,
    metric_name: str,
) -> None:
    if coverage_count == 0 and value is not None:
        raise MonetizationValidationError(f"{metric_name}_sum must be NULL when coverage is zero")
    if coverage_count > 0 and value is None:
        raise MonetizationValidationError(
            f"{metric_name}_sum must be present when coverage is non-zero"
        )
    if value is not None:
        _require_number(value, field_name=f"{metric_name}_sum")
