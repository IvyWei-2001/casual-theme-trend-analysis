"""Pure AGG-002 opportunity-evidence aggregation over stored internal rows."""

from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from math import isclose, isfinite
from statistics import median

from ..storage.models import AppMetadataRow, MarketSnapshotRow, SnapshotPeriodKey
from .errors import AggregationValidationError
from .opportunity_models import (
    DEFAULT_REPRESENTATIVE_GAME_LIMIT,
    OpportunityAggregationResult,
    ThemeDimensionMonthlyMetric,
    ThemeGrowthSourceMetric,
    ThemeMarketStructureMetric,
    ThemeRepresentativeGame,
)
from .theme_monthly import aggregate_monthly_theme_metrics

_DIMENSION_FIELDS: tuple[tuple[str, str], ...] = (
    ("game_subgenre", "game_subgenre"),
    ("game_product_model", "game_product_model"),
    ("game_art_style", "game_art_style"),
    ("game_setting", "game_setting"),
)


def aggregate_theme_opportunity_metrics(
    source_periods: Sequence[Sequence[MarketSnapshotRow]],
    metadata_by_id: Mapping[str, AppMetadataRow],
    *,
    previous_periods: Mapping[
        SnapshotPeriodKey,
        Sequence[MarketSnapshotRow] | None,
    ]
    | None = None,
    calculated_at: datetime,
) -> OpportunityAggregationResult:
    """Build legacy and V2 aggregates without network or external DTO access.

    The source boundary is deliberately the same normalized snapshot and
    metadata rows used by AGG-001.  The immediately preceding stored month is
    used when supplied or when it is also present in ``source_periods``;
    absence is represented as ``NULL``-compatible evidence rather than an
    invented empty market.
    """

    legacy_result = aggregate_monthly_theme_metrics(
        source_periods,
        metadata_by_id,
        previous_periods=previous_periods,
        calculated_at=calculated_at,
    )
    current_by_key = _current_period_mapping(source_periods)
    previous_by_current_key = {
        key: _previous_rows_for_key(
            key,
            current_by_key=current_by_key,
            previous_periods=previous_periods,
        )
        for key in current_by_key
    }
    totals_by_key = {_period_key_from_total(total): total for total in legacy_result.monthly_totals}
    metrics_by_key_theme = {
        (_period_key_from_metric(metric), metric.game_theme): metric
        for metric in legacy_result.theme_metrics
    }

    structures: list[ThemeMarketStructureMetric] = []
    growth_sources: list[ThemeGrowthSourceMetric] = []
    dimensions: list[ThemeDimensionMonthlyMetric] = []
    representative_games: list[ThemeRepresentativeGame] = []

    for key in sorted(current_by_key, key=_period_sort_key):
        current_rows = current_by_key[key]
        previous_rows = previous_by_current_key[key]
        total = totals_by_key[key]
        rows_by_theme = _rows_by_theme(current_rows)
        previous_rows_by_theme = _rows_by_theme(previous_rows or ())
        current_market_ids = {row.unified_app_id for row in current_rows}
        previous_market_ids = (
            {row.unified_app_id for row in previous_rows} if previous_rows is not None else None
        )

        for theme in sorted(rows_by_theme):
            theme_rows = tuple(rows_by_theme[theme])
            previous_theme_rows = tuple(previous_rows_by_theme.get(theme, ()))
            legacy_metric = metrics_by_key_theme[(key, theme)]
            structures.append(
                _build_market_structure(
                    total,
                    theme_rows,
                    metadata_by_id,
                    calculated_at=calculated_at,
                )
            )
            growth_sources.append(
                _build_growth_source(
                    key,
                    theme,
                    theme_rows,
                    previous_theme_rows,
                    current_market_ids=current_market_ids,
                    previous_market_ids=previous_market_ids,
                    previous_rows=previous_rows,
                    calculated_at=calculated_at,
                )
            )
            dimensions.extend(
                _build_dimensions(
                    total,
                    legacy_metric,
                    theme_rows,
                    metadata_by_id,
                    previous_rows=previous_rows,
                    previous_market_ids=previous_market_ids,
                    calculated_at=calculated_at,
                )
            )
            representative_games.extend(
                _build_representative_games(
                    key,
                    theme,
                    theme_rows,
                    previous_theme_rows,
                    previous_rows=previous_rows,
                    previous_market_ids=previous_market_ids,
                    metadata_by_id=metadata_by_id,
                    calculated_at=calculated_at,
                )
            )

    return OpportunityAggregationResult(
        monthly_totals=legacy_result.monthly_totals,
        theme_metrics=legacy_result.theme_metrics,
        theme_market_structure_metrics=tuple(structures),
        theme_growth_source_metrics=tuple(growth_sources),
        theme_dimension_monthly_metrics=tuple(dimensions),
        theme_representative_games=tuple(representative_games),
    )


def _current_period_mapping(
    source_periods: Sequence[Sequence[MarketSnapshotRow]],
) -> dict[SnapshotPeriodKey, tuple[MarketSnapshotRow, ...]]:
    result: dict[SnapshotPeriodKey, tuple[MarketSnapshotRow, ...]] = {}
    for period_rows in source_periods:
        rows = tuple(period_rows)
        if not rows:
            raise AggregationValidationError("monthly source period is empty")
        key = rows[0].period_key
        if key in result:
            raise AggregationValidationError("duplicate monthly source period")
        result[key] = rows
    return result


def _previous_rows_for_key(
    key: SnapshotPeriodKey,
    *,
    current_by_key: Mapping[SnapshotPeriodKey, tuple[MarketSnapshotRow, ...]],
    previous_periods: Mapping[
        SnapshotPeriodKey,
        Sequence[MarketSnapshotRow] | None,
    ]
    | None,
) -> tuple[MarketSnapshotRow, ...] | None:
    previous_key = _previous_period_key(key)
    if previous_periods is not None and previous_key in previous_periods:
        rows = previous_periods[previous_key]
        return tuple(rows) if rows else None
    rows = current_by_key.get(previous_key)
    return rows if rows else None


def _rows_by_theme(
    rows: Sequence[MarketSnapshotRow],
) -> dict[str, list[MarketSnapshotRow]]:
    grouped: dict[str, list[MarketSnapshotRow]] = defaultdict(list)
    for row in rows:
        if row.game_theme is not None:
            grouped[row.game_theme].append(row)
    return grouped


def _build_market_structure(
    total: object,
    rows: Sequence[MarketSnapshotRow],
    metadata_by_id: Mapping[str, AppMetadataRow],
    *,
    calculated_at: datetime,
) -> ThemeMarketStructureMetric:
    # The legacy model is intentionally used as the typed source for the
    # month-wide denominator; no business formula is duplicated here.
    from .models import MonthlyMarketTotal

    if not isinstance(total, MonthlyMarketTotal):
        raise AggregationValidationError("monthly total violates the internal type boundary")
    product_count = len(rows)
    publisher_values: list[str] = []
    publisher_covered_rows: list[MarketSnapshotRow] = []
    for row in rows:
        metadata = metadata_by_id.get(row.unified_app_id)
        if metadata is None or metadata.publisher_display_name is None:
            continue
        publisher_values.append(metadata.publisher_display_name)
        publisher_covered_rows.append(row)
    publisher_counts = Counter(publisher_values)
    downloads_publisher_rows = [
        row for row in publisher_covered_rows if row.units_absolute is not None
    ]
    revenue_publisher_rows = [
        row for row in publisher_covered_rows if row.revenue_absolute is not None
    ]
    download_values = _metric_values(rows, "units_absolute")
    revenue_values = _metric_values(rows, "revenue_absolute")
    download_stats = _metric_stats(
        download_values,
    )
    revenue_stats = _metric_stats(
        revenue_values,
    )
    download_publisher_stats = _publisher_metric_stats(
        downloads_publisher_rows,
        metadata_by_id=metadata_by_id,
        metric_name="units_absolute",
    )
    revenue_publisher_stats = _publisher_metric_stats(
        revenue_publisher_rows,
        metadata_by_id=metadata_by_id,
        metric_name="revenue_absolute",
    )
    release_dates = [row.release_date_ww for row in rows if row.release_date_ww is not None]
    valid_ages = [
        (total.period_end - release_date).days
        for release_date in release_dates
        if release_date <= total.period_end
    ]
    future_count = sum(release_date > total.period_end for release_date in release_dates)
    top_download_rows = _top_metric_rows(rows, "units_absolute", limit=10)
    top_revenue_rows = _top_metric_rows(rows, "revenue_absolute", limit=10)

    return ThemeMarketStructureMetric(
        scope_name=total.scope_name,
        cadence=total.cadence,
        period_start=total.period_start,
        period_end=total.period_end,
        game_theme=_require_theme(rows),
        product_count=product_count,
        product_share=product_count / total.snapshot_count,
        top_100_count=sum(row.rank_position <= 100 for row in rows),
        top_500_count=sum(row.rank_position <= 500 for row in rows),
        average_rank=sum(row.rank_position for row in rows) / product_count,
        median_rank=float(median(row.rank_position for row in rows)),
        downloads_coverage_count=len(download_values),
        downloads_coverage_ratio=len(download_values) / product_count,
        downloads_sum=download_stats[0],
        downloads_share=_positive_market_share(download_stats[0], total.units_absolute_sum),
        downloads_mean_per_covered_product=download_stats[1],
        downloads_median_per_covered_product=download_stats[2],
        downloads_top_1_product_share=download_stats[3],
        downloads_top_3_product_share=download_stats[4],
        downloads_top_10_product_share=download_stats[5],
        downloads_product_hhi=download_stats[6],
        revenue_usd_coverage_count=len(revenue_values),
        revenue_usd_coverage_ratio=len(revenue_values) / product_count,
        revenue_usd_sum=revenue_stats[0],
        revenue_usd_share=_positive_market_share(revenue_stats[0], total.revenue_absolute_sum),
        revenue_usd_mean_per_covered_product=revenue_stats[1],
        revenue_usd_median_per_covered_product=revenue_stats[2],
        revenue_usd_top_1_product_share=revenue_stats[3],
        revenue_usd_top_3_product_share=revenue_stats[4],
        revenue_usd_top_10_product_share=revenue_stats[5],
        revenue_usd_product_hhi=revenue_stats[6],
        publisher_coverage_count=len(publisher_covered_rows),
        publisher_coverage_ratio=len(publisher_covered_rows) / product_count,
        publisher_count=len(publisher_counts),
        top_1_publisher_product_share=_publisher_top_share(
            publisher_counts,
            denominator=len(publisher_covered_rows),
            limit=1,
        ),
        top_3_publisher_product_share=_publisher_top_share(
            publisher_counts,
            denominator=len(publisher_covered_rows),
            limit=3,
        ),
        publisher_product_hhi=_publisher_hhi(
            list(publisher_counts.values()),
            denominator=len(publisher_covered_rows),
        ),
        publisher_downloads_coverage_count=len(downloads_publisher_rows),
        publisher_downloads_coverage_ratio=len(downloads_publisher_rows) / product_count,
        top_1_publisher_downloads_share=download_publisher_stats[0],
        top_3_publisher_downloads_share=download_publisher_stats[1],
        publisher_downloads_hhi=download_publisher_stats[2],
        publisher_revenue_usd_coverage_count=len(revenue_publisher_rows),
        publisher_revenue_usd_coverage_ratio=len(revenue_publisher_rows) / product_count,
        top_1_publisher_revenue_usd_share=revenue_publisher_stats[0],
        top_3_publisher_revenue_usd_share=revenue_publisher_stats[1],
        publisher_revenue_usd_hhi=revenue_publisher_stats[2],
        release_date_ww_coverage_count=len(release_dates),
        release_date_ww_coverage_ratio=len(release_dates) / product_count,
        release_date_ww_valid_age_count=len(valid_ages),
        release_date_ww_future_count=future_count,
        median_product_age_days=float(median(valid_ages)) if valid_ages else None,
        downloads_top_10_median_product_age_days=_top_age_median(
            top_download_rows,
            period_end=total.period_end,
        ),
        revenue_usd_top_10_median_product_age_days=_top_age_median(
            top_revenue_rows,
            period_end=total.period_end,
        ),
        calculated_at=calculated_at,
    )


def _build_growth_source(
    key: SnapshotPeriodKey,
    theme: str,
    current_rows: Sequence[MarketSnapshotRow],
    previous_theme_rows: Sequence[MarketSnapshotRow],
    *,
    current_market_ids: set[str],
    previous_market_ids: set[str] | None,
    previous_rows: Sequence[MarketSnapshotRow] | None,
    calculated_at: datetime,
) -> ThemeGrowthSourceMetric:
    has_previous = previous_rows is not None
    current_ids = {row.unified_app_id for row in current_rows}
    previous_theme_ids = {row.unified_app_id for row in previous_theme_rows}
    market_new_ids = (
        current_market_ids - previous_market_ids if previous_market_ids is not None else set()
    )
    theme_entry_ids = current_ids - previous_theme_ids
    continuing_ids = current_ids & previous_theme_ids
    theme_exit_ids = previous_theme_ids - current_ids

    top100_current, top100_previous, top100_entry, top100_exit, top100_retained = _turnover(
        current_rows,
        previous_theme_rows,
        threshold=100,
        has_previous=has_previous,
    )
    top500_current, top500_previous, top500_entry, top500_exit, top500_retained = _turnover(
        current_rows,
        previous_theme_rows,
        threshold=500,
        has_previous=has_previous,
    )
    current_download_top10 = _top_metric_rows(current_rows, "units_absolute", limit=10)
    previous_download_top10 = _top_metric_rows(previous_theme_rows, "units_absolute", limit=10)
    current_revenue_top10 = _top_metric_rows(current_rows, "revenue_absolute", limit=10)
    previous_revenue_top10 = _top_metric_rows(previous_theme_rows, "revenue_absolute", limit=10)

    downloads = _growth_metric(
        current_rows,
        previous_theme_rows,
        attr="units_absolute",
        market_new_ids=market_new_ids,
        theme_entry_ids=theme_entry_ids,
        continuing_ids=continuing_ids,
        theme_exit_ids=theme_exit_ids,
        has_previous=has_previous,
    )
    revenue = _growth_metric(
        current_rows,
        previous_theme_rows,
        attr="revenue_absolute",
        market_new_ids=market_new_ids,
        theme_entry_ids=theme_entry_ids,
        continuing_ids=continuing_ids,
        theme_exit_ids=theme_exit_ids,
        has_previous=has_previous,
    )

    return ThemeGrowthSourceMetric(
        scope_name=key.scope_name,
        cadence=key.cadence,
        period_start=key.period_start,
        period_end=key.period_end,
        game_theme=theme,
        has_previous_month=has_previous,
        previous_product_count=len(previous_theme_rows) if has_previous else None,
        current_product_count=len(current_rows),
        product_count_change=(len(current_rows) - len(previous_theme_rows))
        if has_previous
        else None,
        market_new_entry_count=(
            len([row for row in current_rows if row.unified_app_id in market_new_ids])
            if has_previous
            else None
        ),
        market_returning_product_count=(
            len(current_rows)
            - len([row for row in current_rows if row.unified_app_id in market_new_ids])
            if has_previous
            else None
        ),
        theme_entry_count=len(theme_entry_ids) if has_previous else None,
        theme_exit_count=len(theme_exit_ids) if has_previous else None,
        continuing_theme_product_count=len(continuing_ids) if has_previous else None,
        market_new_entry_share=(
            len([row for row in current_rows if row.unified_app_id in market_new_ids])
            / len(current_rows)
            if has_previous
            else None
        ),
        theme_entry_share=len(theme_entry_ids) / len(current_rows) if has_previous else None,
        market_new_entry_top_100_count=(
            sum(
                row.rank_position <= 100
                for row in current_rows
                if row.unified_app_id in market_new_ids
            )
            if has_previous
            else None
        ),
        market_new_entry_top_100_rate=(
            _ratio(
                sum(
                    row.rank_position <= 100
                    for row in current_rows
                    if row.unified_app_id in market_new_ids
                ),
                len([row for row in current_rows if row.unified_app_id in market_new_ids]),
            )
            if has_previous
            else None
        ),
        market_new_entry_top_500_count=(
            sum(
                row.rank_position <= 500
                for row in current_rows
                if row.unified_app_id in market_new_ids
            )
            if has_previous
            else None
        ),
        market_new_entry_top_500_rate=(
            _ratio(
                sum(
                    row.rank_position <= 500
                    for row in current_rows
                    if row.unified_app_id in market_new_ids
                ),
                len([row for row in current_rows if row.unified_app_id in market_new_ids]),
            )
            if has_previous
            else None
        ),
        top_100_current_count=top100_current,
        top_100_previous_count=top100_previous,
        top_100_entry_count=top100_entry,
        top_100_exit_count=top100_exit,
        top_100_retained_count=top100_retained,
        top_100_turnover_rate=_ratio(top100_entry, top100_current),
        top_500_current_count=top500_current,
        top_500_previous_count=top500_previous,
        top_500_entry_count=top500_entry,
        top_500_exit_count=top500_exit,
        top_500_retained_count=top500_retained,
        top_500_turnover_rate=_ratio(top500_entry, top500_current),
        downloads_top_10_current_count=len(current_download_top10),
        downloads_top_10_retained_count=(
            len(
                {row.unified_app_id for row in current_download_top10}
                & {row.unified_app_id for row in previous_download_top10}
            )
            if has_previous
            else None
        ),
        downloads_top_10_retention_rate=(
            _ratio(
                len(
                    {row.unified_app_id for row in current_download_top10}
                    & {row.unified_app_id for row in previous_download_top10}
                ),
                len(current_download_top10),
            )
            if has_previous
            else None
        ),
        revenue_usd_top_10_current_count=len(current_revenue_top10),
        revenue_usd_top_10_retained_count=(
            len(
                {row.unified_app_id for row in current_revenue_top10}
                & {row.unified_app_id for row in previous_revenue_top10}
            )
            if has_previous
            else None
        ),
        revenue_usd_top_10_retention_rate=(
            _ratio(
                len(
                    {row.unified_app_id for row in current_revenue_top10}
                    & {row.unified_app_id for row in previous_revenue_top10}
                ),
                len(current_revenue_top10),
            )
            if has_previous
            else None
        ),
        downloads_current_coverage_count=downloads[0],
        downloads_previous_coverage_count=downloads[1],
        downloads_decomposition_complete=downloads[2],
        downloads_current_sum=downloads[3],
        downloads_previous_sum=downloads[4],
        downloads_mom_change=downloads[5],
        downloads_mom_growth_rate=downloads[6],
        downloads_market_new_entry_sum=downloads[7],
        downloads_market_new_entry_share_of_current=downloads[8],
        downloads_theme_entry_contribution=downloads[9],
        downloads_continuing_contribution=downloads[10],
        downloads_theme_exit_contribution=downloads[11],
        downloads_positive_contribution_sum=downloads[12],
        downloads_negative_contribution_sum=downloads[13],
        downloads_positive_contributor_count=downloads[14],
        downloads_negative_contributor_count=downloads[15],
        downloads_unchanged_contributor_count=downloads[16],
        downloads_market_new_entry_positive_contribution_share=downloads[17],
        downloads_continuing_positive_contribution_share=downloads[18],
        downloads_top_1_positive_contribution_share=downloads[19],
        downloads_top_3_positive_contribution_share=downloads[20],
        downloads_top_10_positive_contribution_share=downloads[21],
        revenue_usd_current_coverage_count=revenue[0],
        revenue_usd_previous_coverage_count=revenue[1],
        revenue_usd_decomposition_complete=revenue[2],
        revenue_usd_current_sum=revenue[3],
        revenue_usd_previous_sum=revenue[4],
        revenue_usd_mom_change=revenue[5],
        revenue_usd_mom_growth_rate=revenue[6],
        revenue_usd_market_new_entry_sum=revenue[7],
        revenue_usd_market_new_entry_share_of_current=revenue[8],
        revenue_usd_theme_entry_contribution=revenue[9],
        revenue_usd_continuing_contribution=revenue[10],
        revenue_usd_theme_exit_contribution=revenue[11],
        revenue_usd_positive_contribution_sum=revenue[12],
        revenue_usd_negative_contribution_sum=revenue[13],
        revenue_usd_positive_contributor_count=revenue[14],
        revenue_usd_negative_contributor_count=revenue[15],
        revenue_usd_unchanged_contributor_count=revenue[16],
        revenue_usd_market_new_entry_positive_contribution_share=revenue[17],
        revenue_usd_continuing_positive_contribution_share=revenue[18],
        revenue_usd_top_1_positive_contribution_share=revenue[19],
        revenue_usd_top_3_positive_contribution_share=revenue[20],
        revenue_usd_top_10_positive_contribution_share=revenue[21],
        calculated_at=calculated_at,
    )


def _build_dimensions(
    total: object,
    legacy_metric: object,
    theme_rows: Sequence[MarketSnapshotRow],
    metadata_by_id: Mapping[str, AppMetadataRow],
    *,
    previous_rows: Sequence[MarketSnapshotRow] | None,
    previous_market_ids: set[str] | None,
    calculated_at: datetime,
) -> list[ThemeDimensionMonthlyMetric]:
    from .models import MonthlyMarketTotal, ThemeMonthlyMetric

    if not isinstance(total, MonthlyMarketTotal) or not isinstance(
        legacy_metric, ThemeMonthlyMetric
    ):
        raise AggregationValidationError("dimension source rows violate the internal type boundary")
    current_market_ids = {row.unified_app_id for row in theme_rows}
    market_new_ids = (
        current_market_ids - previous_market_ids if previous_market_ids is not None else set()
    )
    result: list[ThemeDimensionMonthlyMetric] = []
    for dimension_type, field_name in _DIMENSION_FIELDS:
        grouped: dict[str, list[MarketSnapshotRow]] = defaultdict(list)
        for row in theme_rows:
            value = getattr(row, field_name)
            if value is not None:
                grouped[value].append(row)
        for dimension_value in sorted(grouped):
            rows = tuple(grouped[dimension_value])
            product_count = len(rows)
            downloads = _metric_values(rows, "units_absolute")
            revenue = _metric_values(rows, "revenue_absolute")
            downloads_sum = _sum_or_none(downloads)
            revenue_sum = _sum_or_none(revenue)
            publisher_rows = [
                row
                for row in rows
                if row.unified_app_id in metadata_by_id
                and metadata_by_id[row.unified_app_id].publisher_display_name is not None
            ]
            publisher_names: list[str] = []
            for row in publisher_rows:
                publisher = metadata_by_id[row.unified_app_id].publisher_display_name
                if publisher is not None:
                    publisher_names.append(publisher)
            publisher_counts = Counter(publisher_names)
            dimension_new_ids = {
                row.unified_app_id for row in rows if row.unified_app_id in market_new_ids
            }
            result.append(
                ThemeDimensionMonthlyMetric(
                    scope_name=total.scope_name,
                    cadence=total.cadence,
                    period_start=total.period_start,
                    period_end=total.period_end,
                    game_theme=legacy_metric.game_theme,
                    dimension_type=dimension_type,  # type: ignore[arg-type]
                    dimension_value=dimension_value,
                    product_count=product_count,
                    product_share_within_theme=product_count / legacy_metric.product_count,
                    product_share_within_market=product_count / total.snapshot_count,
                    top_100_count=sum(row.rank_position <= 100 for row in rows),
                    top_500_count=sum(row.rank_position <= 500 for row in rows),
                    average_rank=sum(row.rank_position for row in rows) / product_count,
                    median_rank=float(median(row.rank_position for row in rows)),
                    downloads_coverage_count=len(downloads),
                    downloads_sum=downloads_sum,
                    downloads_share_within_theme=_ratio(
                        downloads_sum, legacy_metric.units_absolute_sum
                    ),
                    downloads_share_within_market=_ratio(downloads_sum, total.units_absolute_sum),
                    downloads_mean_per_covered_product=(
                        downloads_sum / len(downloads)
                        if downloads and downloads_sum is not None
                        else None
                    ),
                    downloads_median_per_covered_product=float(median(downloads))
                    if downloads
                    else None,
                    downloads_top_1_product_share=_top_product_share(downloads),
                    revenue_usd_coverage_count=len(revenue),
                    revenue_usd_sum=revenue_sum,
                    revenue_usd_share_within_theme=_ratio(
                        revenue_sum, legacy_metric.revenue_absolute_sum
                    ),
                    revenue_usd_share_within_market=_ratio(revenue_sum, total.revenue_absolute_sum),
                    revenue_usd_mean_per_covered_product=(
                        revenue_sum / len(revenue) if revenue and revenue_sum is not None else None
                    ),
                    revenue_usd_median_per_covered_product=float(median(revenue))
                    if revenue
                    else None,
                    revenue_usd_top_1_product_share=_top_product_share(revenue),
                    has_previous_month=previous_rows is not None,
                    market_new_entry_count=(
                        len(dimension_new_ids) if previous_rows is not None else None
                    ),
                    market_new_entry_share=(
                        len(dimension_new_ids) / product_count
                        if previous_rows is not None
                        else None
                    ),
                    market_new_entry_top_100_count=(
                        sum(
                            row.rank_position <= 100
                            for row in rows
                            if row.unified_app_id in dimension_new_ids
                        )
                        if previous_rows is not None
                        else None
                    ),
                    market_new_entry_top_100_rate=(
                        _ratio(
                            sum(
                                row.rank_position <= 100
                                for row in rows
                                if row.unified_app_id in dimension_new_ids
                            ),
                            len(dimension_new_ids),
                        )
                        if previous_rows is not None
                        else None
                    ),
                    market_new_entry_top_500_count=(
                        sum(
                            row.rank_position <= 500
                            for row in rows
                            if row.unified_app_id in dimension_new_ids
                        )
                        if previous_rows is not None
                        else None
                    ),
                    market_new_entry_top_500_rate=(
                        _ratio(
                            sum(
                                row.rank_position <= 500
                                for row in rows
                                if row.unified_app_id in dimension_new_ids
                            ),
                            len(dimension_new_ids),
                        )
                        if previous_rows is not None
                        else None
                    ),
                    publisher_coverage_count=len(publisher_rows),
                    publisher_count=len(publisher_counts),
                    top_1_publisher_product_share=_publisher_top_share(
                        publisher_counts,
                        denominator=len(publisher_rows),
                        limit=1,
                    ),
                    calculated_at=calculated_at,
                )
            )
    return result


def _build_representative_games(
    key: SnapshotPeriodKey,
    theme: str,
    current_theme_rows: Sequence[MarketSnapshotRow],
    previous_theme_rows: Sequence[MarketSnapshotRow],
    *,
    previous_rows: Sequence[MarketSnapshotRow] | None,
    previous_market_ids: set[str] | None,
    metadata_by_id: Mapping[str, AppMetadataRow],
    calculated_at: datetime,
) -> list[ThemeRepresentativeGame]:
    previous_market_by_id = {row.unified_app_id: row for row in previous_rows or ()}
    market_new_ids = (
        {row.unified_app_id for row in current_theme_rows} - previous_market_ids
        if previous_market_ids is not None
        else set()
    )
    theme_ids = {row.unified_app_id for row in previous_theme_rows}
    evidence_rows: list[ThemeRepresentativeGame] = []
    selections: tuple[tuple[str, Sequence[MarketSnapshotRow]], ...] = (
        (
            "downloads_leader",
            _top_metric_rows(
                current_theme_rows, "units_absolute", limit=DEFAULT_REPRESENTATIVE_GAME_LIMIT
            ),
        ),
        (
            "revenue_leader",
            _top_metric_rows(
                current_theme_rows, "revenue_absolute", limit=DEFAULT_REPRESENTATIVE_GAME_LIMIT
            ),
        ),
        (
            "market_new_entry_downloads_leader",
            _top_metric_rows(
                [row for row in current_theme_rows if row.unified_app_id in market_new_ids],
                "units_absolute",
                limit=DEFAULT_REPRESENTATIVE_GAME_LIMIT,
            )
            if previous_rows is not None
            else (),
        ),
        (
            "market_new_entry_revenue_leader",
            _top_metric_rows(
                [row for row in current_theme_rows if row.unified_app_id in market_new_ids],
                "revenue_absolute",
                limit=DEFAULT_REPRESENTATIVE_GAME_LIMIT,
            )
            if previous_rows is not None
            else (),
        ),
    )
    for evidence_type, rows in selections:
        for evidence_rank, row in enumerate(rows, start=1):
            evidence_rows.append(
                _representative_row(
                    key,
                    theme,
                    evidence_type,
                    evidence_rank,
                    row,
                    previous_market_by_id=previous_market_by_id,
                    metadata_by_id=metadata_by_id,
                    has_previous=previous_rows is not None,
                    market_new_ids=market_new_ids,
                    theme_ids=theme_ids,
                    calculated_at=calculated_at,
                )
            )

    for evidence_type, attr in (
        ("downloads_growth_leader", "units_absolute"),
        ("revenue_growth_leader", "revenue_absolute"),
    ):
        growth_candidates = []
        if previous_rows is not None:
            for row in current_theme_rows:
                current_value = getattr(row, attr)
                if current_value is None:
                    continue
                previous_row = previous_market_by_id.get(row.unified_app_id)
                previous_value = getattr(previous_row, attr) if previous_row is not None else 0.0
                if previous_row is not None and previous_value is None:
                    continue
                change = current_value - previous_value
                if change > 0:
                    growth_candidates.append((change, row))
        growth_candidates.sort(
            key=lambda item: (-item[0], item[1].rank_position, item[1].unified_app_id)
        )
        for evidence_rank, (_change, row) in enumerate(
            growth_candidates[:DEFAULT_REPRESENTATIVE_GAME_LIMIT],
            start=1,
        ):
            evidence_rows.append(
                _representative_row(
                    key,
                    theme,
                    evidence_type,
                    evidence_rank,
                    row,
                    previous_market_by_id=previous_market_by_id,
                    metadata_by_id=metadata_by_id,
                    has_previous=True,
                    market_new_ids=market_new_ids,
                    theme_ids=theme_ids,
                    calculated_at=calculated_at,
                )
            )
    return evidence_rows


def _representative_row(
    key: SnapshotPeriodKey,
    theme: str,
    evidence_type: str,
    evidence_rank: int,
    row: MarketSnapshotRow,
    *,
    previous_market_by_id: Mapping[str, MarketSnapshotRow],
    metadata_by_id: Mapping[str, AppMetadataRow],
    has_previous: bool,
    market_new_ids: set[str],
    theme_ids: set[str],
    calculated_at: datetime,
) -> ThemeRepresentativeGame:
    previous_row = previous_market_by_id.get(row.unified_app_id)
    previous_downloads = (
        previous_row.units_absolute if previous_row is not None else (0.0 if has_previous else None)
    )
    previous_revenue = (
        previous_row.revenue_absolute
        if previous_row is not None
        else (0.0 if has_previous else None)
    )
    downloads_change = (
        row.units_absolute - previous_downloads
        if row.units_absolute is not None and previous_downloads is not None
        else None
    )
    revenue_change = (
        row.revenue_absolute - previous_revenue
        if row.revenue_absolute is not None and previous_revenue is not None
        else None
    )
    metadata = metadata_by_id.get(row.unified_app_id)
    return ThemeRepresentativeGame(
        scope_name=key.scope_name,
        cadence=key.cadence,
        period_start=key.period_start,
        period_end=key.period_end,
        game_theme=theme,
        evidence_type=evidence_type,  # type: ignore[arg-type]
        evidence_rank=evidence_rank,
        source_app_id=row.source_app_id,
        unified_app_id=row.unified_app_id,
        game_name=metadata.name if metadata is not None else None,
        publisher_display_name=metadata.publisher_display_name if metadata is not None else None,
        game_subgenre=row.game_subgenre,
        game_product_model=row.game_product_model,
        game_art_style=row.game_art_style,
        game_setting=row.game_setting,
        release_date_ww=row.release_date_ww,
        rank_position=row.rank_position,
        previous_rank_position=previous_row.rank_position if previous_row is not None else None,
        downloads=row.units_absolute,
        previous_downloads=previous_downloads,
        downloads_change=downloads_change,
        revenue_usd=row.revenue_absolute,
        previous_revenue_usd=previous_revenue,
        revenue_usd_change=revenue_change,
        is_market_new_entry=(row.unified_app_id in market_new_ids if has_previous else None),
        is_theme_entry=(row.unified_app_id not in theme_ids if has_previous else None),
        calculated_at=calculated_at,
    )


def _growth_metric(
    current_rows: Sequence[MarketSnapshotRow],
    previous_rows: Sequence[MarketSnapshotRow],
    *,
    attr: str,
    market_new_ids: set[str],
    theme_entry_ids: set[str],
    continuing_ids: set[str],
    theme_exit_ids: set[str],
    has_previous: bool,
) -> tuple[
    int,
    int | None,
    bool | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    int | None,
    int | None,
    int | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
]:
    current_by_id = {row.unified_app_id: row for row in current_rows}
    previous_by_id = {row.unified_app_id: row for row in previous_rows}
    current_values = _metric_values(current_rows, attr)
    previous_values = _metric_values(previous_rows, attr)
    current_sum = _sum_or_none(current_values)
    previous_sum = _sum_or_none(previous_values)
    current_coverage = len(current_values)
    previous_coverage = len(previous_values) if has_previous else None
    if not has_previous:
        return (
            current_coverage,
            None,
            None,
            current_sum,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )

    # A product present in a same-theme group but missing its metric makes the
    # decomposition incomplete.  A completely absent previous theme is an
    # empty baseline and therefore contributes zero without being treated as a
    # missing source metric.
    complete = all(getattr(row, attr) is not None for row in (*current_rows, *previous_rows))
    if not complete:
        return (
            current_coverage,
            previous_coverage,
            False,
            current_sum,
            previous_sum,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )

    union_ids = set(current_by_id) | set(previous_by_id)
    deltas: dict[str, float] = {}
    for unified_app_id in union_ids:
        current_value = (
            getattr(current_by_id[unified_app_id], attr, 0.0)
            if unified_app_id in current_by_id
            else 0.0
        )
        previous_value = (
            getattr(previous_by_id[unified_app_id], attr, 0.0)
            if unified_app_id in previous_by_id
            else 0.0
        )
        if current_value is None or previous_value is None:
            raise AggregationValidationError(
                "complete growth decomposition contains an unavailable metric"
            )
        deltas[unified_app_id] = current_value - previous_value
    mom_change = sum(deltas.values(), 0.0)
    expected_change = (current_sum or 0.0) - (previous_sum or 0.0)
    if not isclose(mom_change, expected_change, rel_tol=1e-9, abs_tol=1e-9):
        raise AggregationValidationError(
            "growth decomposition does not reconcile to month-over-month change"
        )
    positive_values = [value for value in deltas.values() if value > 0]
    negative_values = [value for value in deltas.values() if value < 0]
    positive_sum = sum(positive_values, 0.0)
    negative_sum = sum(negative_values, 0.0)
    positive_sorted = sorted(positive_values, reverse=True)
    market_new_sum = sum(
        deltas[unified_app_id]
        for unified_app_id in current_by_id
        if unified_app_id in market_new_ids
    )
    theme_entry_sum = sum(
        deltas[unified_app_id]
        for unified_app_id in current_by_id
        if unified_app_id in theme_entry_ids
    )
    continuing_sum = sum(
        deltas[unified_app_id]
        for unified_app_id in current_by_id
        if unified_app_id in continuing_ids
    )
    theme_exit_sum = sum(
        deltas[unified_app_id]
        for unified_app_id in previous_by_id
        if unified_app_id in theme_exit_ids
    )
    return (
        current_coverage,
        previous_coverage,
        True,
        current_sum,
        previous_sum,
        mom_change,
        _ratio(mom_change, previous_sum, require_positive_denominator=True),
        market_new_sum,
        _ratio(market_new_sum, current_sum, require_positive_denominator=True),
        theme_entry_sum,
        continuing_sum,
        theme_exit_sum,
        positive_sum,
        negative_sum,
        len(positive_values),
        len(negative_values),
        len(deltas) - len(positive_values) - len(negative_values),
        _ratio(
            sum(
                max(deltas[unified_app_id], 0.0)
                for unified_app_id in current_by_id
                if unified_app_id in market_new_ids
            ),
            positive_sum,
            require_positive_denominator=True,
        ),
        _ratio(
            sum(
                max(deltas[unified_app_id], 0.0)
                for unified_app_id in current_by_id
                if unified_app_id in continuing_ids
            ),
            positive_sum,
            require_positive_denominator=True,
        ),
        _ratio(sum(positive_sorted[:1]), positive_sum, require_positive_denominator=True),
        _ratio(sum(positive_sorted[:3]), positive_sum, require_positive_denominator=True),
        _ratio(sum(positive_sorted[:10]), positive_sum, require_positive_denominator=True),
    )


def _metric_values(rows: Sequence[MarketSnapshotRow], attr: str) -> list[float]:
    return [value for row in rows if (value := getattr(row, attr)) is not None]


def _sum_or_none(values: Sequence[float]) -> float | None:
    return sum(values, 0.0) if values else None


def _metric_stats(
    values: Sequence[float],
) -> tuple[
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
]:
    total = _sum_or_none(values)
    mean = total / len(values) if values and total is not None else None
    value_median = float(median(values)) if values else None
    top1 = _top_product_share(values)
    top3 = _top_product_share(values, limit=3)
    top10 = _top_product_share(values, limit=10)
    hhi = _hhi(values)
    return total, mean, value_median, top1, top3, top10, hhi


def _publisher_metric_stats(
    rows: Sequence[MarketSnapshotRow],
    *,
    metadata_by_id: Mapping[str, AppMetadataRow],
    metric_name: str,
) -> tuple[float | None, float | None, float | None]:
    values_by_publisher: defaultdict[str, float] = defaultdict(float)
    for row in rows:
        value = getattr(row, metric_name)
        if value is not None:
            publisher = metadata_by_id[row.unified_app_id].publisher_display_name
            if publisher is not None:
                values_by_publisher[publisher] += value
    return (
        _top_product_share(list(values_by_publisher.values()), limit=1),
        _top_product_share(list(values_by_publisher.values()), limit=3),
        _hhi(list(values_by_publisher.values())),
    )


def _top_product_share(values: Sequence[float], *, limit: int = 1) -> float | None:
    total = _sum_or_none(values)
    if total is None or total <= 0:
        return None
    return sum(sorted(values, reverse=True)[:limit], 0.0) / total


def _hhi(values: Sequence[float]) -> float | None:
    total = _sum_or_none(values)
    if total is None or total <= 0:
        return None
    return sum((value / total) ** 2 for value in values)


def _positive_market_share(value: float | None, denominator: float | None) -> float | None:
    if value is None or denominator is None or denominator <= 0:
        return None
    share = value / denominator
    if not isfinite(share):
        raise AggregationValidationError("calculated market share is not finite")
    return share


def _ratio(
    numerator: float | int | None,
    denominator: float | int | None,
    *,
    require_positive_denominator: bool = False,
) -> float | None:
    if numerator is None or denominator is None:
        return None
    if require_positive_denominator:
        if denominator <= 0:
            return None
    elif denominator == 0:
        return None
    value = float(numerator) / float(denominator)
    if not isfinite(value):
        raise AggregationValidationError("calculated ratio is not finite")
    return value


def _publisher_top_share(
    counts: Mapping[str, int],
    *,
    denominator: int,
    limit: int,
) -> float | None:
    if denominator <= 0 or not counts:
        return None
    return sum(sorted(counts.values(), reverse=True)[:limit]) / denominator


def _publisher_hhi(values: Sequence[int], *, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return sum((value / denominator) ** 2 for value in values)


def _top_metric_rows(
    rows: Sequence[MarketSnapshotRow],
    attr: str,
    *,
    limit: int,
) -> tuple[MarketSnapshotRow, ...]:
    candidates = [row for row in rows if getattr(row, attr) is not None]
    candidates.sort(key=lambda row: (-getattr(row, attr), row.rank_position, row.unified_app_id))
    return tuple(candidates[:limit])


def _top_age_median(
    rows: Sequence[MarketSnapshotRow],
    *,
    period_end: date,
) -> float | None:
    ages = [
        (period_end - row.release_date_ww).days
        for row in rows
        if row.release_date_ww is not None and row.release_date_ww <= period_end
    ]
    return float(median(ages)) if ages else None


def _require_theme(rows: Sequence[MarketSnapshotRow]) -> str:
    if not rows or rows[0].game_theme is None:
        raise AggregationValidationError("theme group must contain a raw Game Theme value")
    theme = rows[0].game_theme
    if any(row.game_theme != theme for row in rows):
        raise AggregationValidationError("theme group contains mixed raw labels")
    return theme


def _turnover(
    current_rows: Sequence[MarketSnapshotRow],
    previous_rows: Sequence[MarketSnapshotRow],
    *,
    threshold: int,
    has_previous: bool,
) -> tuple[int, int | None, int | None, int | None, int | None]:
    current_set = {row.unified_app_id for row in current_rows if row.rank_position <= threshold}
    if not has_previous:
        return len(current_set), None, None, None, None
    previous_set = {row.unified_app_id for row in previous_rows if row.rank_position <= threshold}
    return (
        len(current_set),
        len(previous_set),
        len(current_set - previous_set),
        len(previous_set - current_set),
        len(current_set & previous_set),
    )


def _period_key_from_total(total: object) -> SnapshotPeriodKey:
    from .models import MonthlyMarketTotal

    if not isinstance(total, MonthlyMarketTotal):
        raise AggregationValidationError("monthly total violates the internal type boundary")
    return SnapshotPeriodKey(
        scope_name=total.scope_name,
        cadence="monthly",
        period_start=total.period_start,
        period_end=total.period_end,
    )


def _period_key_from_metric(metric: object) -> SnapshotPeriodKey:
    from .models import ThemeMonthlyMetric

    if not isinstance(metric, ThemeMonthlyMetric):
        raise AggregationValidationError("theme metric violates the internal type boundary")
    return SnapshotPeriodKey(
        scope_name=metric.scope_name,
        cadence="monthly",
        period_start=metric.period_start,
        period_end=metric.period_end,
    )


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


def _period_sort_key(key: SnapshotPeriodKey) -> tuple[str, date, date, str]:
    return key.scope_name, key.period_start, key.period_end, key.cadence


__all__ = [
    "DEFAULT_REPRESENTATIVE_GAME_LIMIT",
    "OpportunityAggregationResult",
    "aggregate_theme_opportunity_metrics",
]
