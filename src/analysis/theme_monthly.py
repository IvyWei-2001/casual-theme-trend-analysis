"""Deterministic monthly Game Theme aggregation over stored internal rows."""

from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median

from ..storage.models import AppMetadataRow, MarketSnapshotRow, SnapshotPeriodKey
from .errors import AggregationValidationError
from .models import MonthlyMarketTotal, ThemeMonthlyMetric


@dataclass(frozen=True, slots=True)
class MonthlyAggregationResult:
    """Complete replacement payload for the two schema-v2 derived tables."""

    monthly_totals: tuple[MonthlyMarketTotal, ...]
    theme_metrics: tuple[ThemeMonthlyMetric, ...]


def aggregate_monthly_theme_metrics(
    source_periods: Sequence[Sequence[MarketSnapshotRow]],
    metadata_by_id: Mapping[str, AppMetadataRow],
    *,
    previous_periods: Mapping[
        SnapshotPeriodKey,
        Sequence[MarketSnapshotRow] | None,
    ] | None = None,
    calculated_at: datetime,
) -> MonthlyAggregationResult:
    """Aggregate non-empty monthly source periods into typed derived rows.

    ``previous_periods`` is keyed by the natural previous-month period key.  A
    missing key or an explicit empty value means that the previous month is not
    a usable stored baseline.  If a previous month is included in
    ``source_periods``, it is used automatically when no explicit value is
    supplied.  No Sensor Tower DTOs or source requests cross this boundary.
    """

    _validate_metadata_mapping(metadata_by_id)
    current_by_key: dict[SnapshotPeriodKey, tuple[MarketSnapshotRow, ...]] = {}
    for period_rows in source_periods:
        rows = _validate_period_rows(period_rows)
        key = rows[0].period_key
        if key in current_by_key:
            raise AggregationValidationError("duplicate monthly source period")
        current_by_key[key] = rows

    if not current_by_key:
        raise AggregationValidationError("at least one monthly source period is required")
    if previous_periods is not None:
        for key, previous_period_rows in previous_periods.items():
            if not isinstance(key, SnapshotPeriodKey) or key.cadence != "monthly":
                raise AggregationValidationError("previous source period key is invalid")
            if previous_period_rows is not None and previous_period_rows:
                _validate_period_rows(previous_period_rows, expected_key=key)

    totals: list[MonthlyMarketTotal] = []
    metrics: list[ThemeMonthlyMetric] = []
    for key in sorted(current_by_key, key=_period_sort_key):
        rows = current_by_key[key]
        previous_key = _previous_period_key(key)
        previous_rows_value: Sequence[MarketSnapshotRow] | None
        if previous_periods is not None and previous_key in previous_periods:
            previous_rows_value = previous_periods[previous_key]
        else:
            previous_rows_value = current_by_key.get(previous_key)
        previous_rows = _resolve_previous_rows(previous_rows_value, previous_key)
        total, period_metrics = _aggregate_period(
            rows,
            metadata_by_id,
            previous_rows=previous_rows,
            calculated_at=calculated_at,
        )
        totals.append(total)
        metrics.extend(period_metrics)

    return MonthlyAggregationResult(tuple(totals), tuple(metrics))


def aggregate_theme_monthly(
    source_periods: Sequence[Sequence[MarketSnapshotRow]],
    metadata_by_id: Mapping[str, AppMetadataRow],
    *,
    previous_periods: Mapping[
        SnapshotPeriodKey,
        Sequence[MarketSnapshotRow] | None,
    ] | None = None,
    calculated_at: datetime,
) -> MonthlyAggregationResult:
    """Compatibility spelling for callers that lead with the business object."""

    return aggregate_monthly_theme_metrics(
        source_periods,
        metadata_by_id,
        previous_periods=previous_periods,
        calculated_at=calculated_at,
    )


def _aggregate_period(
    rows: tuple[MarketSnapshotRow, ...],
    metadata_by_id: Mapping[str, AppMetadataRow],
    *,
    previous_rows: tuple[MarketSnapshotRow, ...] | None,
    calculated_at: datetime,
) -> tuple[MonthlyMarketTotal, list[ThemeMonthlyMetric]]:
    key = rows[0].period_key
    snapshot_count = len(rows)
    theme_present_count = sum(row.game_theme is not None for row in rows)
    theme_missing_count = snapshot_count - theme_present_count
    metadata_coverage_count = sum(row.unified_app_id in metadata_by_id for row in rows)
    units_values = [row.units_absolute for row in rows if row.units_absolute is not None]
    revenue_values = [row.revenue_absolute for row in rows if row.revenue_absolute is not None]
    units_sum = sum(units_values, 0.0) if units_values else None
    revenue_sum = sum(revenue_values, 0.0) if revenue_values else None
    total = MonthlyMarketTotal(
        scope_name=key.scope_name,
        cadence=key.cadence,
        period_start=key.period_start,
        period_end=key.period_end,
        snapshot_count=snapshot_count,
        theme_present_count=theme_present_count,
        theme_missing_count=theme_missing_count,
        metadata_coverage_count=metadata_coverage_count,
        units_absolute_coverage_count=len(units_values),
        units_absolute_sum=units_sum,
        revenue_absolute_coverage_count=len(revenue_values),
        revenue_absolute_sum=revenue_sum,
        calculated_at=calculated_at,
    )

    rows_by_theme: dict[str, list[MarketSnapshotRow]] = defaultdict(list)
    for row in rows:
        if row.game_theme is not None:
            rows_by_theme[row.game_theme].append(row)
    previous_ids = (
        {row.unified_app_id for row in previous_rows} if previous_rows is not None else set()
    )
    has_previous_month = previous_rows is not None
    period_metrics = [
        _build_theme_metric(
            theme,
            theme_rows,
            total,
            metadata_by_id,
            previous_ids=previous_ids,
            has_previous_month=has_previous_month,
            calculated_at=calculated_at,
        )
        for theme, theme_rows in sorted(rows_by_theme.items())
    ]
    return total, period_metrics


def _build_theme_metric(
    theme: str,
    rows: Sequence[MarketSnapshotRow],
    total: MonthlyMarketTotal,
    metadata_by_id: Mapping[str, AppMetadataRow],
    *,
    previous_ids: set[str],
    has_previous_month: bool,
    calculated_at: datetime,
) -> ThemeMonthlyMetric:
    ranks = [row.rank_position for row in rows]
    units_values = [row.units_absolute for row in rows if row.units_absolute is not None]
    revenue_values = [row.revenue_absolute for row in rows if row.revenue_absolute is not None]
    product_count = len(rows)
    current_ids = {row.unified_app_id for row in rows}
    new_entry_count = len(current_ids - previous_ids) if has_previous_month else None
    returning_product_count = len(current_ids & previous_ids) if has_previous_month else None
    new_entry_share = (
        new_entry_count / product_count
        if has_previous_month and new_entry_count is not None
        else None
    )

    publisher_values = [
        metadata_by_id[row.unified_app_id].publisher_display_name
        for row in rows
        if row.unified_app_id in metadata_by_id
        and metadata_by_id[row.unified_app_id].publisher_display_name is not None
    ]
    publisher_counts = Counter(publisher_values)
    publisher_coverage_count = len(publisher_values)
    publisher_count = len(publisher_counts)
    top_publisher_product_share = (
        max(publisher_counts.values()) / publisher_coverage_count
        if publisher_coverage_count
        else None
    )

    return ThemeMonthlyMetric(
        scope_name=total.scope_name,
        cadence=total.cadence,
        period_start=total.period_start,
        period_end=total.period_end,
        game_theme=theme,
        product_count=product_count,
        product_share=product_count / total.snapshot_count,
        top_100_count=sum(row.rank_position <= 100 for row in rows),
        top_500_count=sum(row.rank_position <= 500 for row in rows),
        average_rank=sum(ranks) / product_count,
        median_rank=float(median(ranks)),
        units_absolute_coverage_count=len(units_values),
        units_absolute_sum=sum(units_values, 0.0) if units_values else None,
        units_absolute_share=_share(units_values, total.units_absolute_sum),
        revenue_absolute_coverage_count=len(revenue_values),
        revenue_absolute_sum=sum(revenue_values, 0.0) if revenue_values else None,
        revenue_absolute_share=_share(revenue_values, total.revenue_absolute_sum),
        has_previous_month=has_previous_month,
        new_entry_count=new_entry_count,
        returning_product_count=returning_product_count,
        new_entry_share=new_entry_share,
        publisher_coverage_count=publisher_coverage_count,
        publisher_count=publisher_count,
        top_publisher_product_share=top_publisher_product_share,
        calculated_at=calculated_at,
    )


def _share(values: Sequence[float], denominator: float | None) -> float | None:
    if not values or denominator is None or denominator == 0:
        return None
    share = sum(values, 0.0) / denominator
    if not _is_finite(share):
        raise AggregationValidationError("calculated share is not finite")
    return share


def _validate_metadata_mapping(metadata_by_id: Mapping[str, AppMetadataRow]) -> None:
    if not isinstance(metadata_by_id, Mapping):
        raise AggregationValidationError("metadata must be a mapping")
    for key, row in metadata_by_id.items():
        if not isinstance(key, str) or not isinstance(row, AppMetadataRow):
            raise AggregationValidationError("publisher metadata violates internal types")
        if key != row.unified_app_id:
            raise AggregationValidationError("publisher metadata violates internal identity")


def _validate_period_rows(
    period_rows: Sequence[MarketSnapshotRow],
    *,
    expected_key: SnapshotPeriodKey | None = None,
) -> tuple[MarketSnapshotRow, ...]:
    rows = tuple(period_rows)
    if not rows:
        raise AggregationValidationError("monthly source period is empty")
    if any(not isinstance(row, MarketSnapshotRow) for row in rows):
        raise AggregationValidationError("monthly source rows violate internal types")
    key = rows[0].period_key
    if expected_key is not None and key != expected_key:
        raise AggregationValidationError("source period identity is mixed or invalid")
    if key.cadence != "monthly" or not _is_natural_month(key.period_start, key.period_end):
        raise AggregationValidationError("source period identity is mixed or invalid")
    if any(row.period_key != key for row in rows[1:]):
        raise AggregationValidationError("source period identity is mixed or invalid")
    if any(row.request_provenance != rows[0].request_provenance for row in rows[1:]):
        raise AggregationValidationError("source period provenance is mixed")
    unified_ids = [row.unified_app_id for row in rows]
    ranks = [row.rank_position for row in rows]
    if len(set(unified_ids)) != len(unified_ids):
        raise AggregationValidationError("source period contains duplicate products")
    if len(set(ranks)) != len(ranks) or any(rank <= 0 for rank in ranks):
        raise AggregationValidationError("source period contains invalid rank positions")
    return rows


def _resolve_previous_rows(
    period_rows: Sequence[MarketSnapshotRow] | None,
    expected_key: SnapshotPeriodKey,
) -> tuple[MarketSnapshotRow, ...] | None:
    if not period_rows:
        return None
    return _validate_period_rows(period_rows, expected_key=expected_key)


def _previous_period_key(key: SnapshotPeriodKey) -> SnapshotPeriodKey:
    previous_start = key.period_start - timedelta(days=1)
    previous_start = previous_start.replace(day=1)
    previous_end = date(
        previous_start.year,
        previous_start.month,
        calendar.monthrange(previous_start.year, previous_start.month)[1],
    )
    return SnapshotPeriodKey(
        scope_name=key.scope_name,
        cadence="monthly",
        period_start=previous_start,
        period_end=previous_end,
    )


def _is_natural_month(period_start: date, period_end: date) -> bool:
    return (
        period_start.day == 1
        and period_end
        == date(
            period_start.year,
            period_start.month,
            calendar.monthrange(period_start.year, period_start.month)[1],
        )
    )


def _period_sort_key(key: SnapshotPeriodKey) -> tuple[str, date, date, str]:
    return (key.scope_name, key.period_start, key.period_end, key.cadence)


def _is_finite(value: float) -> bool:
    return value == value and abs(value) != float("inf")
