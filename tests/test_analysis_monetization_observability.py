"""Synthetic MONETIZATION-001 policy and aggregation tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from src.analysis.monetization_models import (
    MONETIZATION_MEANINGFUL_IAP_TAG_KEYS,
    MONETIZATION_VERIFIED_CUSTOM_TAG_KEYS,
    build_app_monetization_profiles,
    classify_product_monetization_proxy,
    normalize_source_boolean_state,
)
from src.analysis.monetization_observability import (
    aggregate_theme_monetization_observability,
)
from src.sensor_tower import (
    GAME_IQ_IAP_BUNDLES_TAG,
    IN_APP_PURCHASES_TAG,
    MONETIZATION_AD_REMOVAL_TAG,
    MONETIZATION_ADS_TAG,
    MONETIZATION_LIVE_OPS_TAG,
)

OBSERVED_AT = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
PERIOD_START = date(2026, 7, 1)
PERIOD_END = date(2026, 7, 31)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "true"),
        (False, "false"),
        ("True", "true"),
        (" TRUE ", "true"),
        ("true", "true"),
        ("False", "false"),
        ("FALSE", "false"),
        (" false ", "false"),
        (None, "unknown"),
        (1, "invalid"),
        (0, "invalid"),
        ("yes", "invalid"),
        ("no", "invalid"),
        ([], "invalid"),
        ({}, "invalid"),
    ],
)
def test_source_boolean_normalization_is_strict(value: object, expected: str) -> None:
    assert normalize_source_boolean_state(value) == expected


def test_absent_source_value_is_unknown() -> None:
    assert normalize_source_boolean_state() == "unknown"


@pytest.mark.parametrize(
    ("ads_state", "iap_states", "expected"),
    [
        ("true", ("false",) * 7, ("ads_dominant_candidate", "low")),
        ("true", ("true",) + ("false",) * 6, ("hybrid_candidate", "partial")),
        ("true", ("true", "true") + ("false",) * 5, ("hybrid_candidate", "partial")),
        ("false", ("true",) + ("false",) * 6, ("iap_dominant_candidate", "higher")),
        ("false", ("false",) * 7, ("unknown", "unknown")),
        ("unknown", ("true",) + ("false",) * 6, ("unknown", "unknown")),
        ("invalid", ("false",) * 7, ("unknown", "unknown")),
        ("false", ("invalid",) + ("false",) * 6, ("unknown", "unknown")),
    ],
)
def test_product_proxy_covers_policy_branches(
    ads_state: str,
    iap_states: tuple[str, ...],
    expected: tuple[str, str],
) -> None:
    proxy, applicability, _ = classify_product_monetization_proxy(  # type: ignore[arg-type]
        ads_state,  # type: ignore[arg-type]
        iap_states,  # type: ignore[arg-type]
    )
    assert (proxy, applicability) == expected


def test_unmatched_source_is_unknown_before_signal_validation() -> None:
    result = classify_product_monetization_proxy(
        "invalid",  # type: ignore[arg-type]
        ("invalid",) * 7,  # type: ignore[arg-type]
        source_record_matched=False,
    )
    assert result == ("unknown", "unknown", "source_record_unmatched")


def _snapshot(
    source_app_id: str,
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
        source_app_id=source_app_id,
        unified_app_id=f"unified-{source_app_id}",
        game_theme=theme,
        game_product_model=product_model,
        units_absolute=units,
        revenue_absolute=revenue,
    )


def _source_record(source_app_id: str, tags: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(app_id=source_app_id, custom_tags=tags)


def _profile_rows(
    snapshots: list[SimpleNamespace],
    tags_by_app_id: dict[str, dict[str, object]],
) -> list[object]:
    return build_app_monetization_profiles(
        snapshots,
        [_source_record(app_id, tags) for app_id, tags in tags_by_app_id.items()],
        observed_at=OBSERVED_AT,
    )


def test_contextual_fields_do_not_create_meaningful_iap() -> None:
    snapshot = _snapshot("contextual", theme="Theme", units=1, revenue=100)
    tags = {
        MONETIZATION_AD_REMOVAL_TAG: True,
        IN_APP_PURCHASES_TAG: True,
        MONETIZATION_LIVE_OPS_TAG: True,
    }
    profile = _profile_rows([snapshot], {"contextual": tags})[0]
    assert profile.meaningful_iap_mechanism_count == 0
    assert profile.monetization_mix_proxy == "unknown"
    assert profile.ads_state == "unknown"


def test_raw_audit_is_canonical_and_preserves_source_values() -> None:
    snapshot = _snapshot("audit", theme="Theme", units=1, revenue=0)
    tags = {
        GAME_IQ_IAP_BUNDLES_TAG: " TrUe ",
        MONETIZATION_ADS_TAG: {"unexpected": object()},
        "unsupported-tag": "ignored",
    }
    profile = _profile_rows([snapshot], {"audit": tags})[0]
    assert profile.verified_source_tags_json == (
        '{"Game IQ - IAP Bundles":" TrUe ",'
        '"Monetization: Ads":{"unexpected":"<unsupported>"}}'
    )
    assert profile.source_tag_present_count == 2
    assert profile.source_tag_invalid_count == 1
    assert profile.ads_state == "invalid"
    assert profile.monetization_mix_proxy == "unknown"


def test_product_classification_does_not_use_model_downloads_or_revenue() -> None:
    first = _snapshot("same", theme="Theme", units=1, revenue=0, product_model="A")
    second = _snapshot("other", theme="Theme", units=999999, revenue=999999, product_model="B")
    tags = {
        MONETIZATION_ADS_TAG: True,
        GAME_IQ_IAP_BUNDLES_TAG: True,
    }
    profiles = _profile_rows([first, second], {"same": tags, "other": tags})
    assert [profile.monetization_mix_proxy for profile in profiles] == [
        "hybrid_candidate",
        "hybrid_candidate",
    ]


def test_theme_downloads_majority_controls_applicability_and_revenue_is_supporting() -> None:
    snapshots = [
        _snapshot("ads", theme="Theme", units=80, revenue=10),
        _snapshot("iap-1", theme="Theme", units=10, revenue=20),
        _snapshot("iap-2", theme="Theme", units=10, revenue=0),
    ]
    tags = {
        "ads": {MONETIZATION_ADS_TAG: True},
        "iap-1": {MONETIZATION_ADS_TAG: False, GAME_IQ_IAP_BUNDLES_TAG: True},
        "iap-2": {MONETIZATION_ADS_TAG: False, GAME_IQ_IAP_BUNDLES_TAG: True},
    }
    metric = aggregate_theme_monetization_observability(
        snapshots,
        _profile_rows(snapshots, tags),
        calculated_at=OBSERVED_AT,
    )[0]
    assert metric.ads_dominant_candidate_product_share == pytest.approx(1 / 3)
    assert metric.iap_dominant_candidate_product_share == pytest.approx(2 / 3)
    assert metric.ads_dominant_candidate_downloads_share == pytest.approx(0.8)
    assert metric.iap_dominant_candidate_downloads_share == pytest.approx(0.2)
    assert metric.dominant_monetization_mix_proxy_by_downloads == "ads_dominant_candidate"
    assert metric.observable_revenue_applicability == "low"
    assert metric.observable_revenue_usd_sum == 30
    assert metric.iap_dominant_candidate_observable_revenue_share == pytest.approx(2 / 3)


def test_unknown_threshold_precedes_ads_at_exact_half() -> None:
    snapshots = [
        _snapshot("unknown", theme="Theme", units=50, revenue=None),
        _snapshot("ads", theme="Theme", units=50, revenue=0),
    ]
    tags = {"unknown": {}, "ads": {MONETIZATION_ADS_TAG: True}}
    metric = aggregate_theme_monetization_observability(
        snapshots,
        _profile_rows(snapshots, tags),
        calculated_at=OBSERVED_AT,
    )[0]
    assert metric.observable_revenue_applicability == "unknown"
    assert metric.applicability_reason == "unknown_proxy_dominates_downloads"


def test_zero_and_null_denominators_remain_distinct() -> None:
    zero_snapshots = [_snapshot("zero", theme="Zero", units=0, revenue=0)]
    zero_metric = aggregate_theme_monetization_observability(
        zero_snapshots,
        _profile_rows(zero_snapshots, {"zero": {MONETIZATION_ADS_TAG: True}}),
        calculated_at=OBSERVED_AT,
    )[0]
    assert zero_metric.downloads_sum == 0
    assert zero_metric.ads_dominant_candidate_downloads_sum == 0
    assert zero_metric.ads_dominant_candidate_downloads_share is None
    assert zero_metric.applicability_reason == "no_positive_downloads_denominator"

    null_snapshots = [_snapshot("null", theme="Null", units=None, revenue=None)]
    null_metric = aggregate_theme_monetization_observability(
        null_snapshots,
        _profile_rows(null_snapshots, {"null": {MONETIZATION_ADS_TAG: True}}),
        calculated_at=OBSERVED_AT,
    )[0]
    assert null_metric.downloads_sum is None
    assert null_metric.observable_revenue_usd_sum is None
    assert null_metric.applicability_reason == "no_positive_downloads_denominator"


def test_source_match_threshold_and_raw_theme_behavior() -> None:
    snapshots = [
        _snapshot("a", theme="", units=10, revenue=None),
        _snapshot("b", theme="Unknown", units=10, revenue=None),
        _snapshot("c", theme="N/A", units=10, revenue=None),
        _snapshot("d", theme=None, units=10, revenue=None),
        _snapshot("e", theme="Unknown", units=10, revenue=None),
    ]
    tags = {
        "a": {MONETIZATION_ADS_TAG: True},
        "b": {MONETIZATION_ADS_TAG: True},
        "c": {MONETIZATION_ADS_TAG: True},
    }
    profiles = _profile_rows(snapshots, tags)
    metrics = aggregate_theme_monetization_observability(
        snapshots,
        profiles,
        calculated_at=OBSERVED_AT,
    )
    assert [metric.game_theme for metric in metrics] == ["", "N/A", "Unknown"]
    unknown_metric = next(metric for metric in metrics if metric.game_theme == "Unknown")
    assert unknown_metric.product_count == 2
    assert unknown_metric.source_record_match_ratio == 0.5
    assert unknown_metric.applicability_reason == "insufficient_source_match_coverage"


def test_all_approved_tag_keys_are_exactly_partitioned() -> None:
    assert len(MONETIZATION_VERIFIED_CUSTOM_TAG_KEYS) == 11
    assert len(MONETIZATION_MEANINGFUL_IAP_TAG_KEYS) == 7
    assert len(set(MONETIZATION_VERIFIED_CUSTOM_TAG_KEYS)) == 11
