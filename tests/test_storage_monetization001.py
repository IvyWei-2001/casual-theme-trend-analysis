"""Synthetic schema-v8, atomic-storage, and Parquet contract tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest

from src.analysis.monetization_models import (
    build_app_monetization_profiles,
)
from src.analysis.monetization_observability import (
    aggregate_theme_monetization_observability,
)
from src.storage import DuckDBRepository, MarketSnapshotRow
from src.storage import schema as schema_module
from src.storage.errors import SchemaInitializationError, StorageValidationError

CALCULATED_AT = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
SCOPE_NAME = "casual_puzzle_tabletop"


def _snapshot(
    month_start: date,
    source_app_id: str,
    rank_position: int,
    *,
    theme: str | None = "Theme",
    units: float | None = 100,
    revenue: float | None = 10,
) -> MarketSnapshotRow:
    next_month = date(
        month_start.year + (month_start.month == 12),
        1 if month_start.month == 12 else month_start.month + 1,
        1,
    )
    period_end = next_month.fromordinal(next_month.toordinal() - 1)
    return MarketSnapshotRow(
        scope_name=SCOPE_NAME,
        cadence="monthly",
        period_start=month_start,
        period_end=period_end,
        rank_position=rank_position,
        source_app_id=source_app_id,
        unified_app_id=f"unified-{source_app_id}",
        scope_country="WW",
        device_type="total",
        category=7012,
        data_model="DM_2025_Q2",
        source_date=datetime(month_start.year, month_start.month, 15, tzinfo=UTC),
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
        game_product_model="context",
        game_art_style=None,
        game_setting=None,
        earliest_release_date=None,
        release_date_ww=None,
        publisher_country=None,
        most_popular_country_by_revenue=None,
        is_unified_source_value=None,
        collected_at=CALCULATED_AT,
    )


def _payload(
    month_start: date = date(2026, 7, 1),
) -> tuple[list[MarketSnapshotRow], list[object], list[object]]:
    snapshots = [
        _snapshot(month_start, "a1", 1, revenue=None),
        _snapshot(month_start, "a2", 2, theme="Other", revenue=0),
        _snapshot(month_start, "a3", 3, theme="Other", units=0, revenue=10),
    ]
    profiles = build_app_monetization_profiles(snapshots, calculated_at=CALCULATED_AT)
    metrics = aggregate_theme_monetization_observability(
        snapshots,
        profiles,
        calculated_at=CALCULATED_AT,
    )
    return snapshots, profiles, metrics


def _create_schema_at_version(path: Path, version: int) -> None:
    connection = duckdb.connect(str(path))
    connection.execute(schema_module._CREATE_SCHEMA_MIGRATIONS_SQL)
    for current_version, apply_version in (
        (1, schema_module._apply_version_one),
        (2, schema_module._apply_version_two),
        (3, schema_module._apply_version_three),
        (4, schema_module._apply_version_four),
        (5, schema_module._apply_version_five),
        (6, schema_module._apply_version_six),
        (7, schema_module._apply_version_seven),
    ):
        if current_version > version:
            break
        apply_version(connection)
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
            [current_version],
        )
    connection.close()


def _insert_legacy_v7_app_row(connection: duckdb.DuckDBPyConnection) -> None:
    values = {
        column: None for column in schema_module.LEGACY_APP_MONETIZATION_PROFILES_COLUMNS
    }
    values.update(
        {
            "scope_name": SCOPE_NAME,
            "cadence": "monthly",
            "period_start": date(2026, 7, 1),
            "period_end": date(2026, 7, 31),
            "source_app_id": "legacy-source",
            "unified_app_id": "legacy-unified",
            "monetization_policy_version": "MONETIZATION001_V1",
            "source_record_matched": True,
            "verified_source_tags_json": "{}",
            "source_tag_present_count": 0,
            "source_tag_invalid_count": 0,
            "ads_state": "unknown",
            "ad_removal_state": "unknown",
            "in_app_purchases_state": "unknown",
            "iap_bundles_state": "unknown",
            "currency_bundles_state": "unknown",
            "season_pass_state": "unknown",
            "starter_pack_state": "unknown",
            "subscription_state": "unknown",
            "in_app_subscription_state": "unknown",
            "loot_box_state": "unknown",
            "live_ops_state": "unknown",
            "meaningful_iap_mechanism_count": 0,
            "meaningful_iap_evidence_state": "unknown",
            "monetization_mix_proxy": "unknown",
            "observable_revenue_applicability": "unknown",
            "classification_reason": "no_meaningful_monetization_signal",
            "observed_at": CALCULATED_AT,
        }
    )
    columns = schema_module.LEGACY_APP_MONETIZATION_PROFILES_COLUMNS
    placeholders = ", ".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO app_monetization_profiles ({', '.join(columns)}) VALUES ({placeholders})",
        [values[column] for column in columns],
    )


def test_fresh_schema_reaches_final_v8_with_compact_active_columns(tmp_path: Path) -> None:
    repository = DuckDBRepository(tmp_path / "fresh.duckdb")
    connection = repository.open()
    repository.initialize_schema()

    assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (8,)
    assert [row[1] for row in connection.execute(
        "PRAGMA table_info('app_monetization_profiles')"
    ).fetchall()] == list(schema_module.APP_MONETIZATION_PROFILES_COLUMNS)
    assert [row[1] for row in connection.execute(
        "PRAGMA table_info('theme_monetization_observability_metrics')"
    ).fetchall()] == list(schema_module.THEME_MONETIZATION_OBSERVABILITY_METRICS_COLUMNS)
    assert not {
        "ads_state",
        "meaningful_iap_evidence_state",
        "source_record_matched",
        "observable_revenue_applicability",
        "ads_dominant_candidate_product_count",
    } & set(schema_module.APP_MONETIZATION_PROFILES_COLUMNS)
    repository.close()


def test_v6_migrates_to_final_v8_and_preserves_protected_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "v6.duckdb"
    _create_schema_at_version(database_path, 6)
    connection = duckdb.connect(str(database_path))
    snapshot = _snapshot(date(2026, 7, 1), "protected", 1)
    columns = schema_module.MARKET_SNAPSHOT_COLUMNS
    placeholders = ", ".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO market_snapshots ({', '.join(columns)}) VALUES ({placeholders})",
        [getattr(snapshot, column) for column in columns],
    )
    connection.close()

    repository = DuckDBRepository(database_path)
    repository.open()
    repository.initialize_schema()
    assert repository._connection is not None
    assert repository._connection.execute(
        "SELECT max(version) FROM schema_migrations"
    ).fetchone() == (8,)
    assert repository.get_market_snapshot_period(snapshot.period_key) == [snapshot]
    repository.close()


def test_interim_empty_v7_migrates_to_v8_without_reinterpreting_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "v7-empty.duckdb"
    _create_schema_at_version(database_path, 7)
    repository = DuckDBRepository(database_path)
    repository.open()
    repository.initialize_schema()
    assert repository._connection is not None
    assert repository._connection.execute(
        "SELECT max(version) FROM schema_migrations"
    ).fetchone() == (8,)
    assert repository._connection.execute(
        "SELECT count(*) FROM app_monetization_profiles"
    ).fetchone() == (0,)
    assert repository._connection.execute(
        "SELECT count(*) FROM theme_monetization_observability_metrics"
    ).fetchone() == (0,)
    repository.close()


def test_non_empty_legacy_v7_fails_before_destructive_change(tmp_path: Path) -> None:
    database_path = tmp_path / "v7-nonempty.duckdb"
    _create_schema_at_version(database_path, 7)
    connection = duckdb.connect(str(database_path))
    _insert_legacy_v7_app_row(connection)
    connection.close()

    repository = DuckDBRepository(database_path)
    repository.open()
    with pytest.raises(
        SchemaInitializationError,
        match="must both be empty",
    ):
        repository.initialize_schema()
    assert repository._connection is not None
    assert repository._connection.execute(
        "SELECT max(version) FROM schema_migrations"
    ).fetchone() == (7,)
    assert [row[1] for row in repository._connection.execute(
        "PRAGMA table_info('app_monetization_profiles')"
    ).fetchall()] == list(schema_module.LEGACY_APP_MONETIZATION_PROFILES_COLUMNS)
    assert repository._connection.execute(
        "SELECT count(*) FROM app_monetization_profiles"
    ).fetchone() == (1,)
    repository.close()


def test_range_round_trip_filters_and_parquet_schema(tmp_path: Path) -> None:
    snapshots, profiles, metrics = _payload()
    repository = DuckDBRepository(tmp_path / "round-trip.duckdb")
    repository.open()
    repository.initialize_schema()
    repository.replace_market_snapshot_and_monetization_period(snapshots, profiles, metrics)

    assert repository.get_app_monetization_profiles(
        scope_name=SCOPE_NAME,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        monetization_proxy="iaa_candidate",
    )[0].source_app_id == "a2"
    assert repository.get_app_monetization_profiles(
        observable_revenue_state="unavailable"
    )[0].source_app_id == "a1"
    assert repository.get_theme_monetization_observability_metrics(
        game_theme="Other"
    )[0].game_theme == "Other"

    app_path = tmp_path / "exports" / "app.parquet"
    theme_path = tmp_path / "exports" / "theme.parquet"
    repository.export_app_monetization_profiles_to_parquet(app_path)
    repository.export_theme_monetization_observability_metrics_to_parquet(theme_path)
    repository.close()

    reader = duckdb.connect()
    assert reader.execute(
        "SELECT unified_app_id FROM read_parquet(?) ORDER BY unified_app_id", [str(app_path)]
    ).fetchall() == [("unified-a1",), ("unified-a2",), ("unified-a3",)]
    assert [row[0] for row in reader.execute(
        "DESCRIBE SELECT * FROM read_parquet(?)", [str(app_path)]
    ).fetchall()] == list(schema_module.APP_MONETIZATION_PROFILES_COLUMNS)
    assert reader.execute(
        "SELECT compression FROM parquet_metadata(?) LIMIT 1", [str(app_path)]
    ).fetchone() == ("ZSTD",)
    reader.close()


def test_range_replacement_is_atomic_and_preserves_outside_period(tmp_path: Path) -> None:
    first_snapshots, first_profiles, first_metrics = _payload(date(2026, 5, 1))
    second_snapshots, second_profiles, second_metrics = _payload(date(2026, 6, 1))
    outside_snapshots, outside_profiles, outside_metrics = _payload(date(2026, 7, 1))
    repository = DuckDBRepository(tmp_path / "range.duckdb")
    repository.open()
    repository.initialize_schema()
    for snapshots, profiles, metrics in (
        (first_snapshots, first_profiles, first_metrics),
        (second_snapshots, second_profiles, second_metrics),
        (outside_snapshots, outside_profiles, outside_metrics),
    ):
        repository.replace_market_snapshot_and_monetization_period(
            snapshots,
            profiles,
            metrics,
        )
    before_outside = repository.get_app_monetization_profiles(
        period_start=date(2026, 7, 1), period_end=date(2026, 7, 31)
    )
    bad_second = list(second_profiles)
    bad_second[0] = bad_second[0].__class__(
        **{
            **{
                field: getattr(bad_second[0], field)
                for field in bad_second[0].__dataclass_fields__
            },
            "source_app_id": "different-source",
        }
    )
    with pytest.raises(StorageValidationError, match="source reference mismatch"):
        repository.replace_monetization_range(
            list(first_profiles) + bad_second,
            list(first_metrics) + list(second_metrics),
        )
    assert repository.get_app_monetization_profiles(
        period_start=date(2026, 5, 1), period_end=date(2026, 5, 31)
    ) == first_profiles
    assert repository.get_app_monetization_profiles(
        period_start=date(2026, 6, 1), period_end=date(2026, 6, 30)
    ) == second_profiles
    assert repository.get_app_monetization_profiles(
        period_start=date(2026, 7, 1), period_end=date(2026, 7, 31)
    ) == before_outside
    repository.close()
