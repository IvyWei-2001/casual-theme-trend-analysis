"""Synthetic schema, atomic-storage, reader, and Parquet tests."""

from __future__ import annotations

from dataclasses import astuple, replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from src.analysis.monetization_models import (
    MONETIZATION_MEANINGFUL_IAP_TAG_KEYS,
    build_app_monetization_profiles,
)
from src.analysis.monetization_observability import (
    aggregate_theme_monetization_observability,
)
from src.sensor_tower import GAME_IQ_IAP_BUNDLES_TAG, MONETIZATION_ADS_TAG
from src.storage import DuckDBRepository, MarketSnapshotRow
from src.storage import schema as schema_module
from src.storage.errors import StorageValidationError

OBSERVED_AT = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
PERIOD_START = date(2026, 7, 1)
PERIOD_END = date(2026, 7, 31)
SCOPE_NAME = "casual_puzzle_tabletop"


def _snapshot(
    source_app_id: str,
    rank_position: int,
    *,
    theme: str | None = "Theme",
    units: float | None = 100,
    revenue: float | None = 10,
) -> MarketSnapshotRow:
    return MarketSnapshotRow(
        scope_name=SCOPE_NAME,
        cadence="monthly",
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        rank_position=rank_position,
        source_app_id=source_app_id,
        unified_app_id=f"unified-{source_app_id}",
        scope_country="WW",
        device_type="total",
        category=7012,
        data_model="DM_2025_Q2",
        source_date=datetime(2026, 7, 15, tzinfo=UTC),
        source_country=None,
        current_units_value=None,
        units_absolute=units,
        comparison_units_value=None,
        units_delta=None,
        units_transformed_delta=None,
        current_revenue_value=None,
        revenue_absolute=revenue,
        comparison_revenue_value=None,
        revenue_delta=None,
        revenue_transformed_delta=None,
        absolute=None,
        delta=None,
        transformed_delta=None,
        game_theme=theme,
        game_genre="Puzzle",
        game_subgenre=None,
        game_product_model=None,
        game_art_style=None,
        game_setting=None,
        earliest_release_date=None,
        release_date_ww=None,
        publisher_country=None,
        most_popular_country_by_revenue=None,
        is_unified_source_value=None,
        collected_at=OBSERVED_AT,
    )


def _payload() -> tuple[list[MarketSnapshotRow], list[object], list[object]]:
    snapshots = [_snapshot("a1", 1), _snapshot("a2", 2, theme="Other")]
    source_records = [
        SimpleNamespace(
            app_id="a1",
            custom_tags={
                MONETIZATION_ADS_TAG: True,
                **{key: False for key in MONETIZATION_MEANINGFUL_IAP_TAG_KEYS},
            },
        ),
        SimpleNamespace(
            app_id="a2",
            custom_tags={MONETIZATION_ADS_TAG: False, GAME_IQ_IAP_BUNDLES_TAG: True},
        ),
    ]
    profiles = build_app_monetization_profiles(
        snapshots,
        source_records,
        observed_at=OBSERVED_AT,
    )
    metrics = aggregate_theme_monetization_observability(
        snapshots,
        profiles,
        calculated_at=OBSERVED_AT,
    )
    return snapshots, profiles, metrics


def _create_v6_database(path: Path, *, preserved_row: MarketSnapshotRow | None = None) -> None:
    connection = duckdb.connect(str(path))
    connection.execute(schema_module._CREATE_SCHEMA_MIGRATIONS_SQL)
    for version, apply_version in (
        (1, schema_module._apply_version_one),
        (2, schema_module._apply_version_two),
        (3, schema_module._apply_version_three),
        (4, schema_module._apply_version_four),
        (5, schema_module._apply_version_five),
        (6, schema_module._apply_version_six),
    ):
        apply_version(connection)
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) "
            "VALUES (?, CURRENT_TIMESTAMP)",
            [version],
        )
    if preserved_row is not None:
        columns = schema_module.MARKET_SNAPSHOT_COLUMNS
        parameters = [getattr(preserved_row, column) for column in columns]
        placeholders = ", ".join("?" for _ in columns)
        connection.execute(
            f"INSERT INTO market_snapshots ({', '.join(columns)}) VALUES ({placeholders})",
            parameters,
        )
    connection.close()


def test_fresh_schema_reaches_v7_with_exactly_two_new_tables(tmp_path: Path) -> None:
    repository = DuckDBRepository(tmp_path / "fresh.duckdb")
    connection = repository.open()
    repository.initialize_schema()

    migration_versions = connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert migration_versions == [
        (1,),
        (2,),
        (3,),
        (4,),
        (5,),
        (6,),
        (7,),
    ]
    actual_tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    v6_tables = {table_name for table_name, _, _ in schema_module._TABLE_DEFINITIONS[:-2]}
    assert actual_tables == v6_tables | {
        "app_monetization_profiles",
        "theme_monetization_observability_metrics",
    }
    assert [
        row[1] for row in connection.execute(
            "PRAGMA table_info('app_monetization_profiles')"
        ).fetchall()
    ] == list(schema_module.APP_MONETIZATION_PROFILES_COLUMNS)
    assert [
        row[1] for row in connection.execute(
            "PRAGMA table_info('theme_monetization_observability_metrics')"
        ).fetchall()
    ] == list(schema_module.THEME_MONETIZATION_OBSERVABILITY_METRICS_COLUMNS)
    assert "meaningful_iap_evidence_state" in schema_module.APP_MONETIZATION_PROFILES_COLUMNS
    assert not {
        "dominant_monetization_mix_proxy_by_downloads",
        "dominant_monetization_mix_proxy_downloads_share",
        "observable_revenue_applicability",
        "applicability_reason",
    } & set(schema_module.THEME_MONETIZATION_OBSERVABILITY_METRICS_COLUMNS)
    repository.close()


def test_v6_migrates_to_v7_without_rewriting_source_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "v6.duckdb"
    preserved_row = _snapshot("preserved", 1)
    _create_v6_database(database_path, preserved_row=preserved_row)

    repository = DuckDBRepository(database_path)
    repository.open()
    repository.initialize_schema()
    assert repository._connection is not None
    assert repository._connection.execute(
        "SELECT max(version) FROM schema_migrations"
    ).fetchone() == (7,)
    assert repository.get_market_snapshot_period(preserved_row.period_key) == [preserved_row]
    repository.close()


def test_valid_v6_read_only_inspection_does_not_create_v7(tmp_path: Path) -> None:
    database_path = tmp_path / "v6-read-only.duckdb"
    _create_v6_database(database_path)

    repository = DuckDBRepository(database_path)
    connection = repository.open_read_only()
    repository.verify_read_only_schema()

    assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (6,)
    assert connection.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE table_name IN "
        "('app_monetization_profiles', 'theme_monetization_observability_metrics')"
    ).fetchone() == (0,)
    repository.close()


def test_atomic_round_trip_filters_and_zstd_exports(tmp_path: Path) -> None:
    snapshots, profiles, metrics = _payload()
    database_path = tmp_path / "round-trip.duckdb"
    repository = DuckDBRepository(database_path)
    repository.open()
    repository.initialize_schema()
    repository.replace_market_snapshot_and_monetization_period(
        snapshots,
        profiles,
        metrics,
    )
    assert profiles[0].meaningful_iap_evidence_state == "absent"
    assert profiles[1].meaningful_iap_evidence_state == "present"

    assert repository.get_app_monetization_profiles(
        scope_name=SCOPE_NAME,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        monetization_mix_proxy="ads_dominant_candidate",
    ) == [profiles[0]]
    other_metric = next(metric for metric in metrics if metric.game_theme == "Other")
    assert repository.get_theme_monetization_observability_metrics(
        scope_name=SCOPE_NAME,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        game_theme="Other",
    ) == [other_metric]

    app_path = tmp_path / "app_monetization_profiles.parquet"
    theme_path = tmp_path / "theme_monetization_observability_metrics.parquet"
    repository.export_app_monetization_profiles_to_parquet(app_path)
    repository.export_theme_monetization_observability_metrics_to_parquet(theme_path)
    repository.close()

    reader = duckdb.connect()
    assert reader.execute(
        "SELECT unified_app_id FROM read_parquet(?) ORDER BY unified_app_id",
        [str(app_path)],
    ).fetchall() == [("unified-a1",), ("unified-a2",)]
    assert reader.execute(
        "SELECT compression FROM parquet_metadata(?) LIMIT 1",
        [str(app_path)],
    ).fetchone() == ("ZSTD",)
    assert reader.execute(
        "SELECT game_theme FROM read_parquet(?) ORDER BY game_theme",
        [str(theme_path)],
    ).fetchall() == [("Other",), ("Theme",)]
    reader.close()


def test_mismatch_is_rejected_without_replacing_existing_rows(tmp_path: Path) -> None:
    snapshots, profiles, metrics = _payload()
    repository = DuckDBRepository(tmp_path / "mismatch.duckdb")
    repository.open()
    repository.initialize_schema()
    repository.replace_market_snapshot_and_monetization_period(
        snapshots,
        profiles,
        metrics,
    )
    bad_profile = replace(profiles[0], source_app_id="different-source")

    with pytest.raises(StorageValidationError, match="source reference mismatch"):
        repository.replace_monetization_period(
            [bad_profile, profiles[1]],
            metrics,
        )
    assert repository.get_app_monetization_profiles(
        scope_name=SCOPE_NAME,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
    ) == profiles
    repository.close()


def test_snapshot_payload_columns_follow_schema_order() -> None:
    row = _snapshot("order", 1)
    assert len(astuple(row)) == len(schema_module.MARKET_SNAPSHOT_COLUMNS)
