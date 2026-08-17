"""Pure observable-Revenue monetization proxy models.

MONETIZATION-001 is deliberately an observable-Revenue candidate heuristic.
The value is third-party-platform observable Revenue (USD), not complete
commercial revenue and not an observed monetization type.
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isclose, isfinite
from numbers import Real
from typing import Final, Literal, Protocol

from ..identifiers import normalize_required_opaque_id
from .errors import MonetizationValidationError

MONETIZATION_POLICY_VERSION: Final = "MONETIZATION001_OBSERVABLE_REVENUE_PROXY_V1"

type ObservableRevenueState = Literal["unavailable", "zero", "positive"]
type MonetizationProxy = Literal[
    "iaa_candidate",
    "iap_or_hybrid_candidate",
    "unknown",
]
type ClassificationReason = Literal[
    "observable_revenue_unavailable",
    "observable_revenue_zero",
    "observable_revenue_positive",
]

OBSERVABLE_REVENUE_STATES: Final[tuple[ObservableRevenueState, ...]] = (
    "unavailable",
    "zero",
    "positive",
)
MONETIZATION_PROXIES: Final[tuple[MonetizationProxy, ...]] = (
    "iaa_candidate",
    "iap_or_hybrid_candidate",
    "unknown",
)
MONETIZATION_PROXY_ORDER: Final[tuple[MonetizationProxy, ...]] = MONETIZATION_PROXIES
CLASSIFICATION_REASONS: Final[tuple[ClassificationReason, ...]] = (
    "observable_revenue_unavailable",
    "observable_revenue_zero",
    "observable_revenue_positive",
)


class MarketSnapshotLike(Protocol):
    """Structural input contract for stored market snapshot rows."""

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


def classify_observable_revenue(
    revenue_absolute: object,
) -> tuple[ObservableRevenueState, MonetizationProxy, ClassificationReason]:
    """Classify one stored observable-Revenue value using the exact proxy map.

    ``None`` means the third-party observable value is unavailable. Numeric
    zero and positive values produce candidates only; they do not prove the
    product's actual monetization type. Negative and non-finite values are
    invalid source data and are rejected before persistence.
    """

    if revenue_absolute is None:
        return (
            "unavailable",
            "unknown",
            "observable_revenue_unavailable",
        )
    if isinstance(revenue_absolute, bool) or not isinstance(revenue_absolute, Real):
        raise MonetizationValidationError(
            "observable Revenue must be a finite, non-negative number or NULL"
        )
    numeric_value = float(revenue_absolute)
    if not isfinite(numeric_value) or numeric_value < 0:
        raise MonetizationValidationError(
            "observable Revenue must be a finite, non-negative number or NULL"
        )
    if numeric_value == 0:
        return "zero", "iaa_candidate", "observable_revenue_zero"
    return "positive", "iap_or_hybrid_candidate", "observable_revenue_positive"


def classify_observable_revenue_proxy(
    revenue_absolute: object,
) -> tuple[ObservableRevenueState, MonetizationProxy, ClassificationReason]:
    """Named alias for callers that emphasize the candidate-proxy contract."""

    return classify_observable_revenue(revenue_absolute)


def classify_monetization_proxy(
    revenue_absolute: object,
) -> tuple[ObservableRevenueState, MonetizationProxy, ClassificationReason]:
    """Short name for the observable-Revenue classifier."""

    return classify_observable_revenue(revenue_absolute)


@dataclass(frozen=True, slots=True)
class AppMonetizationProfile:
    """One stored market snapshot's observable-Revenue proxy profile."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    source_app_id: str
    unified_app_id: str
    game_theme: str | None
    game_product_model: str | None
    monetization_policy_version: str
    observable_revenue_usd: float | None
    observable_revenue_state: ObservableRevenueState
    monetization_proxy: MonetizationProxy
    classification_reason: ClassificationReason
    calculated_at: datetime

    @property
    def period_key(self) -> tuple[str, str, date, date]:
        """Return the stored market-period identity."""

        return (self.scope_name, self.cadence, self.period_start, self.period_end)

    def __post_init__(self) -> None:
        _require_text(self.scope_name, field_name="scope_name")
        if self.cadence != "monthly":
            raise MonetizationValidationError("cadence must equal monthly")
        _require_natural_month(self.period_start, self.period_end)
        for field_name in ("source_app_id", "unified_app_id"):
            object.__setattr__(
                self,
                field_name,
                _normalize_id(getattr(self, field_name), field_name=field_name),
            )
        for field_name in ("game_theme", "game_product_model"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise MonetizationValidationError(
                    f"{field_name} must be a string or NULL"
                )
        if self.monetization_policy_version != MONETIZATION_POLICY_VERSION:
            raise MonetizationValidationError(
                "monetization_policy_version is not supported"
            )
        normalized_revenue = _normalize_observable_revenue(self.observable_revenue_usd)
        object.__setattr__(self, "observable_revenue_usd", normalized_revenue)
        if self.observable_revenue_state not in OBSERVABLE_REVENUE_STATES:
            raise MonetizationValidationError(
                "observable_revenue_state is not supported"
            )
        if self.monetization_proxy not in MONETIZATION_PROXIES:
            raise MonetizationValidationError("monetization_proxy is not supported")
        if self.classification_reason not in CLASSIFICATION_REASONS:
            raise MonetizationValidationError("classification_reason is not supported")
        expected = classify_observable_revenue(normalized_revenue)
        if (
            self.observable_revenue_state,
            self.monetization_proxy,
            self.classification_reason,
        ) != expected:
            raise MonetizationValidationError(
                "observable-Revenue classification is inconsistent"
            )
        _require_timestamp(self.calculated_at, field_name="calculated_at")


@dataclass(frozen=True, slots=True)
class ThemeMonetizationObservabilityMetric:
    """Raw-theme product and Downloads evidence for one stored month."""

    scope_name: str
    cadence: str
    period_start: date
    period_end: date
    game_theme: str
    monetization_policy_version: str
    product_count: int
    observable_revenue_usd_coverage_count: int
    observable_revenue_usd_coverage_ratio: float
    observable_revenue_usd_sum: float | None
    iaa_candidate_product_count: int
    iaa_candidate_product_share: float
    iap_or_hybrid_candidate_product_count: int
    iap_or_hybrid_candidate_product_share: float
    unknown_product_count: int
    unknown_product_share: float
    downloads_coverage_count: int
    downloads_coverage_ratio: float
    downloads_sum: float | None
    iaa_candidate_downloads_sum: float | None
    iaa_candidate_downloads_share: float | None
    iap_or_hybrid_candidate_downloads_sum: float | None
    iap_or_hybrid_candidate_downloads_share: float | None
    unknown_downloads_sum: float | None
    unknown_downloads_share: float | None
    calculated_at: datetime

    @property
    def period_key(self) -> tuple[str, str, date, date]:
        """Return the stored market-period identity."""

        return (self.scope_name, self.cadence, self.period_start, self.period_end)

    @property
    def observable_revenue_coverage_count(self) -> int:
        """Short alias for the USD-qualified coverage field."""

        return self.observable_revenue_usd_coverage_count

    @property
    def observable_revenue_coverage_ratio(self) -> float:
        """Short alias for the USD-qualified coverage field."""

        return self.observable_revenue_usd_coverage_ratio

    @property
    def observable_revenue_sum(self) -> float | None:
        """Short alias for the total observable-Revenue sum."""

        return self.observable_revenue_usd_sum

    def __post_init__(self) -> None:
        _require_text(self.scope_name, field_name="scope_name")
        if self.cadence != "monthly":
            raise MonetizationValidationError("cadence must equal monthly")
        _require_natural_month(self.period_start, self.period_end)
        if not isinstance(self.game_theme, str):
            raise MonetizationValidationError("game_theme must be a string")
        if self.monetization_policy_version != MONETIZATION_POLICY_VERSION:
            raise MonetizationValidationError(
                "monetization_policy_version is not supported"
            )
        _require_timestamp(self.calculated_at, field_name="calculated_at")

        product_count = _require_count(self.product_count, field_name="product_count")
        if product_count == 0:
            raise MonetizationValidationError("product_count must be positive")
        for field_name in (
            "observable_revenue_usd_coverage_count",
            "downloads_coverage_count",
            "iaa_candidate_product_count",
            "iap_or_hybrid_candidate_product_count",
            "unknown_product_count",
        ):
            count_value = _require_count(getattr(self, field_name), field_name=field_name)
            if count_value > product_count:
                raise MonetizationValidationError(
                    f"{field_name} must not exceed product_count"
                )

        if (
            self.iaa_candidate_product_count
            + self.iap_or_hybrid_candidate_product_count
            + self.unknown_product_count
            != product_count
        ):
            raise MonetizationValidationError(
                "monetization product counts must reconcile to product_count"
            )
        _require_ratio(
            self.observable_revenue_usd_coverage_ratio,
            field_name="observable_revenue_usd_coverage_ratio",
        )
        _require_ratio(
            self.downloads_coverage_ratio,
            field_name="downloads_coverage_ratio",
        )
        if not isclose(
            self.observable_revenue_usd_coverage_ratio,
            self.observable_revenue_usd_coverage_count / product_count,
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise MonetizationValidationError(
                "observable revenue coverage ratio is inconsistent"
            )
        if not isclose(
            self.downloads_coverage_ratio,
            self.downloads_coverage_count / product_count,
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise MonetizationValidationError("downloads coverage ratio is inconsistent")

        _validate_sum_coverage(
            self.observable_revenue_usd_coverage_count,
            self.observable_revenue_usd_sum,
            metric_name="observable_revenue_usd",
        )
        _validate_sum_coverage(
            self.downloads_coverage_count,
            self.downloads_sum,
            metric_name="downloads",
        )
        for field_name in (
            "iaa_candidate_downloads_sum",
            "iap_or_hybrid_candidate_downloads_sum",
            "unknown_downloads_sum",
        ):
            _normalize_non_negative_optional(
                getattr(self, field_name), field_name=field_name
            )

        for proxy, count in (
            ("iaa_candidate", self.iaa_candidate_product_count),
            ("iap_or_hybrid_candidate", self.iap_or_hybrid_candidate_product_count),
            ("unknown", self.unknown_product_count),
        ):
            share_name = f"{proxy}_product_share"
            share = getattr(self, share_name)
            _require_ratio(share, field_name=share_name)
            if not isclose(share, count / product_count, rel_tol=0, abs_tol=1e-12):
                raise MonetizationValidationError(f"{share_name} is inconsistent")

        denominator = self.downloads_sum
        download_sums = (
            self.iaa_candidate_downloads_sum,
            self.iap_or_hybrid_candidate_downloads_sum,
            self.unknown_downloads_sum,
        )
        download_shares = (
            self.iaa_candidate_downloads_share,
            self.iap_or_hybrid_candidate_downloads_share,
            self.unknown_downloads_share,
        )
        if denominator is None or denominator <= 0:
            if any(share is not None for share in download_shares):
                raise MonetizationValidationError(
                    "Downloads shares require a positive observed denominator"
                )
        else:
            for value, share in zip(download_sums, download_shares, strict=True):
                if share is not None:
                    _require_ratio(share, field_name="downloads class share")
                    if value is None:
                        raise MonetizationValidationError(
                            "Downloads share requires an observed class sum"
                        )
                    if not isclose(share, value / denominator, rel_tol=0, abs_tol=1e-12):
                        raise MonetizationValidationError(
                            "Downloads class share is inconsistent"
                        )


def build_app_monetization_profiles(
    market_snapshots: Sequence[MarketSnapshotLike],
    *,
    calculated_at: datetime,
) -> list[AppMonetizationProfile]:
    """Build exactly one observable-Revenue profile per stored snapshot."""

    snapshots = tuple(market_snapshots)
    if not snapshots:
        raise MonetizationValidationError("market snapshots must not be empty")
    _validate_snapshot_population(snapshots)
    profiles: list[AppMonetizationProfile] = []
    for snapshot in snapshots:
        normalized_revenue = _normalize_observable_revenue(snapshot.revenue_absolute)
        state, proxy, reason = classify_observable_revenue(normalized_revenue)
        profiles.append(
            AppMonetizationProfile(
                scope_name=snapshot.scope_name,
                cadence=snapshot.cadence,
                period_start=snapshot.period_start,
                period_end=snapshot.period_end,
                source_app_id=snapshot.source_app_id,
                unified_app_id=snapshot.unified_app_id,
                game_theme=snapshot.game_theme,
                game_product_model=snapshot.game_product_model,
                monetization_policy_version=MONETIZATION_POLICY_VERSION,
                observable_revenue_usd=normalized_revenue,
                observable_revenue_state=state,
                monetization_proxy=proxy,
                classification_reason=reason,
                calculated_at=calculated_at,
            )
        )
    return profiles


def _validate_snapshot_population(snapshots: Sequence[MarketSnapshotLike]) -> None:
    first = snapshots[0]
    first_key = _snapshot_period_key(first)
    if first.cadence != "monthly":
        raise MonetizationValidationError("cadence must equal monthly")
    for snapshot in snapshots:
        if _snapshot_period_key(snapshot) != first_key:
            raise MonetizationValidationError(
                "market snapshots must share one period identity"
            )
        if not isinstance(snapshot.game_theme, (str, type(None))):
            raise MonetizationValidationError("game_theme must be a string or NULL")
        if not isinstance(snapshot.game_product_model, (str, type(None))):
            raise MonetizationValidationError(
                "game_product_model must be a string or NULL"
            )
        _normalize_observable_revenue(snapshot.revenue_absolute)
    unified_ids = [
        _normalize_id(snapshot.unified_app_id, field_name="unified_app_id")
        for snapshot in snapshots
    ]
    if len(set(unified_ids)) != len(unified_ids):
        raise MonetizationValidationError("market snapshots have duplicate unified identities")
    source_ids = [
        _normalize_id(snapshot.source_app_id, field_name="source_app_id")
        for snapshot in snapshots
    ]
    if len(set(source_ids)) != len(source_ids):
        raise MonetizationValidationError("market snapshots have duplicate source identities")


def _snapshot_period_key(snapshot: MarketSnapshotLike) -> tuple[str, str, date, date]:
    return (
        snapshot.scope_name,
        snapshot.cadence,
        snapshot.period_start,
        snapshot.period_end,
    )


def _normalize_observable_revenue(value: object) -> float | None:
    if value is None:
        return None
    state, _proxy, _reason = classify_observable_revenue(value)
    if state == "unavailable":
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise MonetizationValidationError(
            "observable Revenue must be a finite, non-negative number or NULL"
        )
    return float(value)


def _normalize_non_negative_optional(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise MonetizationValidationError(f"{field_name} must be a number or NULL")
    normalized = float(value)
    if not isfinite(normalized) or normalized < 0:
        raise MonetizationValidationError(f"{field_name} must be finite and non-negative")
    return normalized


def _validate_sum_coverage(
    coverage_count: int,
    value: float | None,
    *,
    metric_name: str,
) -> None:
    normalized = _normalize_non_negative_optional(value, field_name=f"{metric_name}_sum")
    if coverage_count == 0 and normalized is not None:
        raise MonetizationValidationError(
            f"{metric_name}_sum must be NULL without coverage"
        )
    if coverage_count > 0 and normalized is None:
        raise MonetizationValidationError(
            f"{metric_name}_sum is required with coverage"
        )


def _require_ratio(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise MonetizationValidationError(f"{field_name} must be a finite ratio")
    normalized = float(value)
    if not isfinite(normalized) or not 0 <= normalized <= 1:
        raise MonetizationValidationError(f"{field_name} must be a finite ratio")
    return normalized


def _require_count(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MonetizationValidationError(f"{field_name} must be a non-negative integer")
    return value


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MonetizationValidationError(f"{field_name} must be a non-empty string")
    return value


def _normalize_id(value: object, *, field_name: str) -> str:
    try:
        return normalize_required_opaque_id(value, field_name=field_name)
    except ValueError as error:
        raise MonetizationValidationError(str(error)) from error


def _require_natural_month(period_start: object, period_end: object) -> None:
    if not isinstance(period_start, date) or not isinstance(period_end, date):
        raise MonetizationValidationError("period boundaries must be dates")
    if period_start.day != 1:
        raise MonetizationValidationError("period_start must be the first day of a month")
    if period_end != date(
        period_start.year,
        period_start.month,
        calendar.monthrange(period_start.year, period_start.month)[1],
    ):
        raise MonetizationValidationError("period_end must be the last day of the month")


def _require_timestamp(value: object, *, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MonetizationValidationError(f"{field_name} must be timezone-aware")
