"""Pure raw-theme aggregation for the observable-Revenue proxy."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from math import isfinite
from numbers import Real

from .errors import MonetizationValidationError
from .monetization_models import (
    MONETIZATION_POLICY_VERSION,
    MONETIZATION_PROXY_ORDER,
    AppMonetizationProfile,
    MarketSnapshotLike,
    ThemeMonetizationObservabilityMetric,
)


def aggregate_theme_monetization_observability(
    market_snapshots: Sequence[MarketSnapshotLike],
    profiles: Sequence[AppMonetizationProfile],
    *,
    calculated_at: datetime,
) -> list[ThemeMonetizationObservabilityMetric]:
    """Aggregate one row per non-NULL raw Game Theme.

    Downloads are descriptive weighting evidence only. No class-level
    observable-Revenue shares are emitted because the classes are defined
    directly from that same observable value.
    """

    snapshots = tuple(market_snapshots)
    profile_rows = tuple(profiles)
    if not snapshots:
        raise MonetizationValidationError("market snapshots must not be empty")
    if len(snapshots) != len(profile_rows):
        raise MonetizationValidationError(
            "monetization profiles must cover every market snapshot"
        )
    period_key = _period_key(snapshots[0])
    if any(_period_key(snapshot) != period_key for snapshot in snapshots):
        raise MonetizationValidationError("market snapshots must share one period")
    if any(profile.period_key != period_key for profile in profile_rows):
        raise MonetizationValidationError("profiles must share the snapshot period")
    profiles_by_id = {profile.unified_app_id: profile for profile in profile_rows}
    if len(profiles_by_id) != len(profile_rows):
        raise MonetizationValidationError("profiles must have unique unified identities")

    grouped: dict[str, list[tuple[MarketSnapshotLike, AppMonetizationProfile]]] = defaultdict(
        list
    )
    expected_ids: set[str] = set()
    for snapshot in snapshots:
        if snapshot.game_theme is None:
            continue
        profile = profiles_by_id.get(snapshot.unified_app_id)
        if profile is None:
            raise MonetizationValidationError(
                "profiles do not cover the snapshot population"
            )
        if (
            profile.source_app_id != snapshot.source_app_id
            or profile.game_theme != snapshot.game_theme
            or profile.game_product_model != snapshot.game_product_model
            or profile.observable_revenue_usd != _normalized_revenue(snapshot.revenue_absolute)
        ):
            raise MonetizationValidationError("profile source reference mismatch")
        grouped[snapshot.game_theme].append((snapshot, profile))
        expected_ids.add(snapshot.unified_app_id)

    # Validate profiles for NULL-theme products too; they still have to be
    # represented at the app level even though no theme row is produced.
    if set(profiles_by_id) != {snapshot.unified_app_id for snapshot in snapshots}:
        raise MonetizationValidationError("profiles do not exactly cover snapshots")
    for snapshot in snapshots:
        profile = profiles_by_id[snapshot.unified_app_id]
        if profile.observable_revenue_usd != _normalized_revenue(snapshot.revenue_absolute):
            raise MonetizationValidationError("profile revenue does not match snapshot")

    results: list[ThemeMonetizationObservabilityMetric] = []
    for game_theme in sorted(grouped):
        rows = grouped[game_theme]
        product_count = len(rows)
        revenue_values: list[float] = []
        for snapshot, _profile in rows:
            revenue = _normalized_revenue(snapshot.revenue_absolute)
            if revenue is not None:
                revenue_values.append(revenue)
        downloads_values = [
            _normalized_non_negative(snapshot.units_absolute, field_name="units_absolute")
            for snapshot, _profile in rows
            if snapshot.units_absolute is not None
        ]
        proxy_product_counts = {
            proxy: sum(profile.monetization_proxy == proxy for _snapshot, profile in rows)
            for proxy in MONETIZATION_PROXY_ORDER
        }
        product_shares = {
            proxy: proxy_product_counts[proxy] / product_count
            for proxy in MONETIZATION_PROXY_ORDER
        }
        proxy_download_sums = {
            proxy: _optional_sum(
                [
                    float(snapshot.units_absolute)
                    for snapshot, profile in rows
                    if profile.monetization_proxy == proxy
                    and snapshot.units_absolute is not None
                ]
            )
            for proxy in MONETIZATION_PROXY_ORDER
        }
        downloads_sum = _optional_sum(downloads_values)
        downloads_shares = {
            proxy: _share(proxy_download_sums[proxy], downloads_sum)
            for proxy in MONETIZATION_PROXY_ORDER
        }
        results.append(
            ThemeMonetizationObservabilityMetric(
                scope_name=period_key[0],
                cadence=period_key[1],
                period_start=period_key[2],
                period_end=period_key[3],
                game_theme=game_theme,
                monetization_policy_version=MONETIZATION_POLICY_VERSION,
                product_count=product_count,
                observable_revenue_usd_coverage_count=len(revenue_values),
                observable_revenue_usd_coverage_ratio=len(revenue_values) / product_count,
                observable_revenue_usd_sum=_optional_sum(revenue_values),
                iaa_candidate_product_count=proxy_product_counts["iaa_candidate"],
                iaa_candidate_product_share=product_shares["iaa_candidate"],
                iap_or_hybrid_candidate_product_count=proxy_product_counts[
                    "iap_or_hybrid_candidate"
                ],
                iap_or_hybrid_candidate_product_share=product_shares[
                    "iap_or_hybrid_candidate"
                ],
                unknown_product_count=proxy_product_counts["unknown"],
                unknown_product_share=product_shares["unknown"],
                downloads_coverage_count=len(downloads_values),
                downloads_coverage_ratio=len(downloads_values) / product_count,
                downloads_sum=downloads_sum,
                iaa_candidate_downloads_sum=proxy_download_sums["iaa_candidate"],
                iaa_candidate_downloads_share=downloads_shares["iaa_candidate"],
                iap_or_hybrid_candidate_downloads_sum=proxy_download_sums[
                    "iap_or_hybrid_candidate"
                ],
                iap_or_hybrid_candidate_downloads_share=downloads_shares[
                    "iap_or_hybrid_candidate"
                ],
                unknown_downloads_sum=proxy_download_sums["unknown"],
                unknown_downloads_share=downloads_shares["unknown"],
                calculated_at=calculated_at,
            )
        )
    return results


def aggregate_theme_monetization_metrics(
    market_snapshots: Sequence[MarketSnapshotLike],
    profiles: Sequence[AppMonetizationProfile],
    *,
    calculated_at: datetime,
) -> list[ThemeMonetizationObservabilityMetric]:
    """Compatibility-neutral alias for the same pure aggregation."""

    return aggregate_theme_monetization_observability(
        market_snapshots,
        profiles,
        calculated_at=calculated_at,
    )


def _period_key(snapshot: MarketSnapshotLike) -> tuple[str, str, date, date]:
    return (
        snapshot.scope_name,
        snapshot.cadence,
        snapshot.period_start,
        snapshot.period_end,
    )


def _normalized_revenue(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise MonetizationValidationError(
            "observable Revenue must be a finite, non-negative number or NULL"
        )
    normalized = float(value)
    if not isfinite(normalized) or normalized < 0:
        raise MonetizationValidationError(
            "observable Revenue must be a finite, non-negative number or NULL"
        )
    return normalized


def _normalized_non_negative(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise MonetizationValidationError(f"{field_name} must be a number or NULL")
    normalized = float(value)
    if not isfinite(normalized) or normalized < 0:
        raise MonetizationValidationError(f"{field_name} must be finite and non-negative")
    return normalized


def _optional_sum(values: Sequence[float]) -> float | None:
    return sum(values) if values else None


def _share(value: float | None, denominator: float | None) -> float | None:
    if value is None or denominator is None or denominator <= 0:
        return None
    return value / denominator
