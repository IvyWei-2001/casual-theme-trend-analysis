"""Synthetic tests for the observable-Revenue MONETIZATION-001 proxy."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from src.analysis.errors import MonetizationValidationError
from src.analysis.monetization_models import (
    MONETIZATION_POLICY_VERSION,
    build_app_monetization_profiles,
    classify_observable_revenue,
)
from src.analysis.monetization_observability import (
    aggregate_theme_monetization_observability,
)

CALCULATED_AT = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
PERIOD_START = date(2026, 7, 1)
PERIOD_END = date(2026, 7, 31)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ("unavailable", "unknown", "observable_revenue_unavailable")),
        (0, ("zero", "iaa_candidate", "observable_revenue_zero")),
        (0.0, ("zero", "iaa_candidate", "observable_revenue_zero")),
        (12.5, ("positive", "iap_or_hybrid_candidate", "observable_revenue_positive")),
    ],
)
def test_observable_revenue_proxy_has_exact_boundaries(
    value: object,
    expected: tuple[str, ...],
) -> None:
    assert classify_observable_revenue(value) == expected


@pytest.mark.parametrize("value", [-1, -0.01, float("nan"), float("inf"), float("-inf")])
def test_negative_and_non_finite_observable_revenue_is_rejected(value: float) -> None:
    with pytest.raises(MonetizationValidationError, match="finite, non-negative"):
        classify_observable_revenue(value)


def _snapshot(
    app_id: str,
    rank: int,
    *,
    theme: str | None,
    units: float | None,
    revenue: float | None,
    product_model: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        scope_name="casual_puzzle_tabletop",
        cadence="monthly",
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        source_app_id=app_id,
        unified_app_id=f"unified-{app_id}",
        game_theme=theme,
        game_product_model=product_model,
        units_absolute=units,
        revenue_absolute=revenue,
        rank_position=rank,
    )


def test_profiles_cover_null_theme_and_preserve_context_only_product_model() -> None:
    snapshots = [
        _snapshot("null-theme", 1, theme=None, units=0, revenue=None, product_model="A"),
        _snapshot("zero", 2, theme="", units=10, revenue=0, product_model="B"),
        _snapshot("positive", 3, theme="Unknown", units=None, revenue=25, product_model="C"),
    ]
    profiles = build_app_monetization_profiles(snapshots, calculated_at=CALCULATED_AT)

    assert len(profiles) == 3
    assert [profile.observable_revenue_state for profile in profiles] == [
        "unavailable",
        "zero",
        "positive",
    ]
    assert [profile.monetization_proxy for profile in profiles] == [
        "unknown",
        "iaa_candidate",
        "iap_or_hybrid_candidate",
    ]
    assert profiles[0].game_theme is None
    assert profiles[0].game_product_model == "A"
    assert all(
        profile.monetization_policy_version == MONETIZATION_POLICY_VERSION
        for profile in profiles
    )


def test_theme_metrics_preserve_raw_labels_and_reconcile_downloads() -> None:
    snapshots = [
        _snapshot("empty", 1, theme="", units=80, revenue=None),
        _snapshot("unknown-1", 2, theme="Unknown", units=10, revenue=0),
        _snapshot("unknown-2", 3, theme="Unknown", units=10, revenue=None),
        _snapshot("na", 4, theme="N/A", units=None, revenue=25),
        _snapshot("null", 5, theme=None, units=100, revenue=5),
    ]
    profiles = build_app_monetization_profiles(snapshots, calculated_at=CALCULATED_AT)
    metrics = aggregate_theme_monetization_observability(
        snapshots,
        profiles,
        calculated_at=CALCULATED_AT,
    )

    assert [metric.game_theme for metric in metrics] == ["", "N/A", "Unknown"]
    unknown = next(metric for metric in metrics if metric.game_theme == "Unknown")
    assert unknown.product_count == 2
    assert unknown.observable_revenue_usd_coverage_count == 1
    assert unknown.observable_revenue_usd_coverage_ratio == pytest.approx(0.5)
    assert unknown.observable_revenue_usd_sum == 0
    assert unknown.iaa_candidate_product_count == 1
    assert unknown.unknown_product_count == 1
    assert unknown.iaa_candidate_product_share == pytest.approx(0.5)
    assert unknown.unknown_downloads_sum == 10
    assert unknown.unknown_downloads_share == pytest.approx(0.5)
    assert unknown.downloads_sum == 20
    assert not hasattr(unknown, "iaa_candidate_observable_revenue_share")


def test_zero_download_denominator_keeps_class_shares_null() -> None:
    snapshots = [
        _snapshot("zero", 1, theme="Theme", units=0, revenue=0),
        _snapshot("missing", 2, theme="Theme", units=None, revenue=None),
    ]
    profiles = build_app_monetization_profiles(snapshots, calculated_at=CALCULATED_AT)
    metric = aggregate_theme_monetization_observability(
        snapshots,
        profiles,
        calculated_at=CALCULATED_AT,
    )[0]

    assert metric.downloads_coverage_count == 1
    assert metric.downloads_sum == 0
    assert metric.iaa_candidate_downloads_sum == 0
    assert metric.iaa_candidate_downloads_share is None
    assert metric.unknown_downloads_sum is None


def test_duplicate_app_identity_and_invalid_revenue_fail_before_profiles() -> None:
    duplicate = [
        _snapshot("same", 1, theme="Theme", units=1, revenue=1),
        _snapshot("same", 2, theme="Other", units=1, revenue=2),
    ]
    with pytest.raises(MonetizationValidationError, match="duplicate"):
        build_app_monetization_profiles(duplicate, calculated_at=CALCULATED_AT)
    invalid = [_snapshot("invalid", 1, theme="Theme", units=1, revenue=-1)]
    with pytest.raises(MonetizationValidationError):
        build_app_monetization_profiles(invalid, calculated_at=CALCULATED_AT)
