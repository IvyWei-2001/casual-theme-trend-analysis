"""Pure mapping from verified Sensor Tower DTOs to internal storage rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

from src.sensor_tower.enrichment import EnrichedMarketRecord, selected_record_unified_app_id
from src.sensor_tower.metadata_parser import SensorTowerMetadataFetchResult

from .errors import StorageValidationError
from .models import AppMetadataRow, MarketSnapshotRow, SnapshotPeriodKey, normalize_positive_id


def build_market_snapshot_rows(
    enriched_records: Sequence[EnrichedMarketRecord],
    *,
    scope_name: str,
    cadence: str,
    period_start: date,
    period_end: date,
    scope_country: str,
    device_type: str,
    category: int,
    data_model: str,
    collected_at: datetime,
) -> list[MarketSnapshotRow]:
    """Map final selected/enriched records into ordered internal storage rows.

    The function is deliberately pure: it preserves the supplied selected
    order, does not fetch anything, does not mutate source DTOs, and uses only
    the caller-provided collection timestamp.
    """

    period_key = SnapshotPeriodKey(
        scope_name=scope_name,
        cadence=cadence,  # type: ignore[arg-type]
        period_start=period_start,
        period_end=period_end,
    )
    rows: list[MarketSnapshotRow] = []
    for rank_position, enriched_record in enumerate(enriched_records, start=1):
        market_record = enriched_record.market_record
        source_app_id = normalize_positive_id(
            market_record.app_id,
            field_name="market record app_id",
        )
        unified_app_id = _resolve_unified_app_id(enriched_record)

        rows.append(
            MarketSnapshotRow(
                scope_name=period_key.scope_name,
                cadence=period_key.cadence,
                period_start=period_key.period_start,
                period_end=period_key.period_end,
                rank_position=rank_position,
                source_app_id=source_app_id,
                unified_app_id=unified_app_id,
                scope_country=scope_country,
                device_type=device_type,
                category=category,
                data_model=data_model,
                source_date=market_record.date,
                source_country=market_record.country,
                current_units_value=market_record.current_units_value,
                units_absolute=market_record.units_absolute,
                comparison_units_value=market_record.comparison_units_value,
                units_delta=market_record.units_delta,
                units_transformed_delta=market_record.units_transformed_delta,
                current_revenue_value=market_record.current_revenue_value,
                revenue_absolute=market_record.revenue_absolute,
                comparison_revenue_value=market_record.comparison_revenue_value,
                revenue_delta=market_record.revenue_delta,
                revenue_transformed_delta=market_record.revenue_transformed_delta,
                absolute=market_record.absolute,
                delta=market_record.delta,
                transformed_delta=market_record.transformed_delta,
                game_theme=market_record.custom_tags.game_theme,
                game_genre=market_record.custom_tags.game_genre,
                game_subgenre=market_record.custom_tags.game_subgenre,
                game_product_model=market_record.custom_tags.game_product_model,
                game_art_style=market_record.custom_tags.game_art_style,
                game_setting=market_record.custom_tags.game_setting,
                earliest_release_date=market_record.custom_tags.earliest_release_date,
                release_date_ww=market_record.custom_tags.release_date_ww,
                publisher_country=market_record.custom_tags.publisher_country,
                most_popular_country_by_revenue=(
                    market_record.custom_tags.most_popular_country_by_revenue
                ),
                is_unified_source_value=market_record.custom_tags.is_unified,
                collected_at=collected_at,
            )
        )
    return rows


def build_app_metadata_rows(
    metadata_result: SensorTowerMetadataFetchResult,
    *,
    fetched_at: datetime,
) -> list[AppMetadataRow]:
    """Map only returned normalized metadata into cache rows.

    The metadata fetch result separately records requested IDs that were
    missing.  Those IDs intentionally do not become placeholder cache rows.
    """

    metadata_by_id = metadata_result.metadata_by_unified_app_id
    if not isinstance(metadata_by_id, Mapping):
        raise StorageValidationError("metadata_result must contain a metadata mapping")

    rows: list[AppMetadataRow] = []
    for metadata in metadata_by_id.values():
        rows.append(
            AppMetadataRow(
                unified_app_id=metadata.unified_app_id,
                name=metadata.name,
                publisher_display_name=metadata.publisher_display_name,
                publisher_resolution_source=metadata.publisher_resolution_source,
                android_app_id=metadata.android_app_id,
                ios_app_id=metadata.ios_app_id,
                fetched_at=fetched_at,
            )
        )
    return rows


def _resolve_unified_app_id(enriched_record: EnrichedMarketRecord) -> str:
    if enriched_record.metadata is not None:
        return normalize_positive_id(
            enriched_record.metadata.unified_app_id,
            field_name="metadata unified_app_id",
        )

    resolved_id = selected_record_unified_app_id(enriched_record.market_record)
    if resolved_id is None:
        raise StorageValidationError(
            "selected market record has no valid unified_app_id fallback"
        )
    return normalize_positive_id(resolved_id, field_name="market record unified_app_id")
