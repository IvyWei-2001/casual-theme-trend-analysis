"""Pure MONETIZATION-001 theme aggregation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from math import isfinite

from .errors import MonetizationValidationError
from .monetization_models import (
    MONETIZATION_POLICY_VERSION,
    MONETIZATION_PROXY_ORDER,
    AppMonetizationProfile,
    MarketSnapshotLike,
    MonetizationMixProxy,
    ThemeMonetizationObservabilityMetric,
)


def aggregate_theme_monetization_observability(
    market_snapshots: Sequence[MarketSnapshotLike],
    profiles: Sequence[AppMonetizationProfile],
    *,
    calculated_at: datetime | None = None,
) -> list[ThemeMonetizationObservabilityMetric]:
    """Aggregate one stored month into descriptive, Downloads-weighted themes.

    The stored snapshot population is authoritative.  Profiles are joined by
    ``unified_app_id`` only after their source and theme fields have been
    reconciled against those stored rows.
    """

    snapshots = tuple(market_snapshots)
    profile_rows = tuple(profiles)
    if not snapshots:
        raise MonetizationValidationError("market snapshot population must not be empty")
    if len(profile_rows) != len(snapshots):
        raise MonetizationValidationError("profile rows must match market snapshot rows")

    first_snapshot = snapshots[0]
    period_key = _snapshot_period_key(first_snapshot)
    snapshot_by_unified_id: dict[str, MarketSnapshotLike] = {}
    source_ids: set[str] = set()
    for snapshot in snapshots:
        if _snapshot_period_key(snapshot) != period_key:
            raise MonetizationValidationError("snapshots must share one period")
        if snapshot.source_app_id in source_ids:
            raise MonetizationValidationError("stored source_app_id values must be unique")
        if snapshot.unified_app_id in snapshot_by_unified_id:
            raise MonetizationValidationError("stored unified_app_id values must be unique")
        source_ids.add(snapshot.source_app_id)
        snapshot_by_unified_id[snapshot.unified_app_id] = snapshot

    profile_by_unified_id: dict[str, AppMonetizationProfile] = {}
    for profile in profile_rows:
        if profile.period_key != period_key:
            raise MonetizationValidationError("profiles must share the snapshot period")
        if profile.monetization_policy_version != MONETIZATION_POLICY_VERSION:
            raise MonetizationValidationError("profiles must use one monetization policy")
        if profile.unified_app_id in profile_by_unified_id:
            raise MonetizationValidationError("profiles must have unique unified_app_id values")
        matched_snapshot = snapshot_by_unified_id.get(profile.unified_app_id)
        if matched_snapshot is None:
            raise MonetizationValidationError("profile references an unknown snapshot product")
        if (
            profile.source_app_id != matched_snapshot.source_app_id
            or profile.game_theme != matched_snapshot.game_theme
            or profile.game_product_model != matched_snapshot.game_product_model
        ):
            raise MonetizationValidationError("profile source fields do not match snapshot")
        profile_by_unified_id[profile.unified_app_id] = profile

    if set(profile_by_unified_id) != set(snapshot_by_unified_id):
        raise MonetizationValidationError("profiles must cover every snapshot product")
    timestamp = profile_rows[0].observed_at if calculated_at is None else calculated_at
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise MonetizationValidationError("calculated_at must be timezone-aware")
    if any(profile.observed_at != timestamp for profile in profile_rows):
        raise MonetizationValidationError("profiles must use one observation timestamp")

    grouped: defaultdict[
        str, list[tuple[MarketSnapshotLike, AppMonetizationProfile]]
    ] = defaultdict(list)
    for snapshot in snapshots:
        if snapshot.game_theme is not None:
            grouped[snapshot.game_theme].append(
                (snapshot, profile_by_unified_id[snapshot.unified_app_id])
            )

    metrics: list[ThemeMonetizationObservabilityMetric] = []
    for game_theme in sorted(grouped):
        entries = grouped[game_theme]
        metrics.append(
            _aggregate_theme_group(
                period_key,
                game_theme,
                entries,
                calculated_at=timestamp,
            )
        )
    return metrics


aggregate_theme_monetization_metrics = aggregate_theme_monetization_observability


def _aggregate_theme_group(
    period_key: tuple[str, str, date, date],
    game_theme: str,
    entries: Sequence[tuple[MarketSnapshotLike, AppMonetizationProfile]],
    *,
    calculated_at: datetime,
) -> ThemeMonetizationObservabilityMetric:
    product_count = len(entries)
    proxy_product_counts = {proxy: 0 for proxy in MONETIZATION_PROXY_ORDER}
    downloads_by_proxy: dict[MonetizationMixProxy, list[float]] = {
        proxy: [] for proxy in MONETIZATION_PROXY_ORDER
    }
    revenue_by_proxy: dict[MonetizationMixProxy, list[float]] = {
        proxy: [] for proxy in MONETIZATION_PROXY_ORDER
    }
    downloads_values: list[float] = []
    revenue_values: list[float] = []
    source_match_count = 0
    ads_known_count = 0
    classified_count = 0
    invalid_signal_count = 0

    for snapshot, profile in entries:
        proxy = profile.monetization_mix_proxy
        proxy_product_counts[proxy] += 1
        if profile.source_record_matched:
            source_match_count += 1
        if profile.ads_state in ("true", "false"):
            ads_known_count += 1
        if proxy != "unknown":
            classified_count += 1
        if profile.classification_reason == "invalid_classification_signal":
            invalid_signal_count += 1

        downloads = _optional_non_negative_number(
            snapshot.units_absolute,
            field_name="units_absolute",
        )
        if downloads is not None:
            downloads_values.append(downloads)
            downloads_by_proxy[proxy].append(downloads)
        revenue = _optional_non_negative_number(
            snapshot.revenue_absolute,
            field_name="revenue_absolute",
        )
        if revenue is not None:
            revenue_values.append(revenue)
            revenue_by_proxy[proxy].append(revenue)

    downloads_sum = sum(downloads_values) if downloads_values else None
    revenue_sum = sum(revenue_values) if revenue_values else None
    downloads_proxy_sums = _proxy_sums(downloads_by_proxy, has_coverage=bool(downloads_values))
    revenue_proxy_sums = _proxy_sums(revenue_by_proxy, has_coverage=bool(revenue_values))
    downloads_shares = _proxy_shares(downloads_proxy_sums, downloads_sum)
    revenue_shares = _proxy_shares(revenue_proxy_sums, revenue_sum)
    product_shares = {
        proxy: proxy_product_counts[proxy] / product_count for proxy in MONETIZATION_PROXY_ORDER
    }
    source_match_ratio = source_match_count / product_count
    ads_known_ratio = ads_known_count / product_count
    classified_ratio = classified_count / product_count

    scope_name, cadence, period_start, period_end = period_key
    return ThemeMonetizationObservabilityMetric(
        scope_name=scope_name,
        cadence=cadence,
        period_start=period_start,
        period_end=period_end,
        game_theme=game_theme,
        monetization_policy_version=MONETIZATION_POLICY_VERSION,
        product_count=product_count,
        downloads_coverage_count=len(downloads_values),
        downloads_sum=downloads_sum,
        observable_revenue_usd_coverage_count=len(revenue_values),
        observable_revenue_usd_sum=revenue_sum,
        source_record_match_count=source_match_count,
        source_record_match_ratio=source_match_ratio,
        ads_signal_known_count=ads_known_count,
        ads_signal_known_ratio=ads_known_ratio,
        proxy_classified_count=classified_count,
        proxy_classified_ratio=classified_ratio,
        invalid_signal_count=invalid_signal_count,
        ads_dominant_candidate_product_count=proxy_product_counts["ads_dominant_candidate"],
        ads_dominant_candidate_product_share=product_shares["ads_dominant_candidate"],
        hybrid_candidate_product_count=proxy_product_counts["hybrid_candidate"],
        hybrid_candidate_product_share=product_shares["hybrid_candidate"],
        iap_dominant_candidate_product_count=proxy_product_counts["iap_dominant_candidate"],
        iap_dominant_candidate_product_share=product_shares["iap_dominant_candidate"],
        unknown_product_count=proxy_product_counts["unknown"],
        unknown_product_share=product_shares["unknown"],
        ads_dominant_candidate_downloads_sum=downloads_proxy_sums["ads_dominant_candidate"],
        ads_dominant_candidate_downloads_share=downloads_shares["ads_dominant_candidate"],
        hybrid_candidate_downloads_sum=downloads_proxy_sums["hybrid_candidate"],
        hybrid_candidate_downloads_share=downloads_shares["hybrid_candidate"],
        iap_dominant_candidate_downloads_sum=downloads_proxy_sums["iap_dominant_candidate"],
        iap_dominant_candidate_downloads_share=downloads_shares["iap_dominant_candidate"],
        unknown_downloads_sum=downloads_proxy_sums["unknown"],
        unknown_downloads_share=downloads_shares["unknown"],
        ads_dominant_candidate_observable_revenue_usd_sum=revenue_proxy_sums[
            "ads_dominant_candidate"
        ],
        ads_dominant_candidate_observable_revenue_share=revenue_shares[
            "ads_dominant_candidate"
        ],
        hybrid_candidate_observable_revenue_usd_sum=revenue_proxy_sums["hybrid_candidate"],
        hybrid_candidate_observable_revenue_share=revenue_shares["hybrid_candidate"],
        iap_dominant_candidate_observable_revenue_usd_sum=revenue_proxy_sums[
            "iap_dominant_candidate"
        ],
        iap_dominant_candidate_observable_revenue_share=revenue_shares["iap_dominant_candidate"],
        unknown_observable_revenue_usd_sum=revenue_proxy_sums["unknown"],
        unknown_observable_revenue_share=revenue_shares["unknown"],
        calculated_at=calculated_at,
    )


def _snapshot_period_key(snapshot: MarketSnapshotLike) -> tuple[str, str, date, date]:
    return (snapshot.scope_name, snapshot.cadence, snapshot.period_start, snapshot.period_end)


def _optional_non_negative_number(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MonetizationValidationError(f"{field_name} must be a number or NULL")
    numeric_value = float(value)
    if not isfinite(numeric_value) or numeric_value < 0:
        raise MonetizationValidationError(f"{field_name} must be finite and non-negative")
    return numeric_value


def _proxy_sums(
    values: dict[MonetizationMixProxy, list[float]],
    *,
    has_coverage: bool,
) -> dict[MonetizationMixProxy, float | None]:
    return {
        proxy: (sum(values[proxy]) if has_coverage else None)
        for proxy in MONETIZATION_PROXY_ORDER
    }


def _proxy_shares(
    sums: dict[MonetizationMixProxy, float | None],
    denominator: float | None,
) -> dict[MonetizationMixProxy, float | None]:
    if denominator is None or denominator <= 0:
        return {proxy: None for proxy in MONETIZATION_PROXY_ORDER}
    positive_denominator = denominator
    shares: dict[MonetizationMixProxy, float | None] = {}
    for proxy in MONETIZATION_PROXY_ORDER:
        proxy_sum = sums[proxy]
        shares[proxy] = None if proxy_sum is None else proxy_sum / positive_denominator
    return shares
