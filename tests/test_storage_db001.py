"""Synthetic integration tests for DB-001 DuckDB storage."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from src.sensor_tower import EnrichedMarketRecord, SensorTowerNormalizedMetadata
from src.sensor_tower.dto import SensorTowerMarketRecord
from src.sensor_tower.metadata_parser import parse_metadata_response
from src.storage import (
    AppMetadataRow,
    DuckDBRepository,
    MarketSnapshotRow,
    RepositoryNotOpenError,
    StorageValidationError,
    UnsupportedSchemaVersionError,
    build_app_metadata_rows,
    build_market_snapshot_rows,
)

AS_OF = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _market_record(
    app_id: int | str,
    *,
    include_tags: bool = True,
    current_units_value: int = 10,
    tag_overrides: dict[str, object] | None = None,
) -> SensorTowerMarketRecord:
    tags: dict[str, object] = {}
    if include_tags:
        tags = {
            "Game Theme": "Decoration",
            "Game Genre": "Puzzle",
            "Game Sub-genre": "Match 3",
            "Game Product Model": "Free-to-play",
            "Game Art Style": "Illustration",
            "Game Setting": "Garden",
            "Earliest Release Date": "2024/01/02",
            "Release Date (WW)": "2024-02-03",
            "Publisher Country": "US",
            "Most Popular Country by Revenue": "US",
            "Is Unified": "true",
        }
    if tag_overrides:
        tags.update(tag_overrides)
    return SensorTowerMarketRecord.model_validate(
        {
            "app_id": app_id,
            "country": "WW",
            "date": "2026-08-07T00:00:00Z",
            "current_units_value": current_units_value,
            "units_absolute": 9,
            "comparison_units_value": 8,
            "units_delta": 1,
            "units_transformed_delta": 0.5,
            "current_revenue_value": 20,
            "revenue_absolute": 19,
            "comparison_revenue_value": 18,
            "revenue_delta": 2,
            "revenue_transformed_delta": 1.5,
            "absolute": 7,
            "delta": 6,
            "transformed_delta": 5,
            "custom_tags": tags,
        }
    )


def _enriched(
    app_id: int | str,
    *,
    metadata: SensorTowerNormalizedMetadata | None = None,
    include_tags: bool = True,
    tag_overrides: dict[str, object] | None = None,
) -> EnrichedMarketRecord:
    return EnrichedMarketRecord(
        market_record=_market_record(
            app_id,
            include_tags=include_tags,
            tag_overrides=tag_overrides,
        ),
        metadata=metadata,
    )


def _snapshot_rows(
    app_ids: tuple[int, ...] = (101, 102),
    *,
    scope_name: str = "global",
    period_start: date = date(2026, 8, 1),
    period_end: date = date(2026, 8, 31),
    scope_country: str = "WW",
    device_type: str = "total",
    category: int = 7012,
    data_model: str = "DM_2025_Q2",
) -> list[MarketSnapshotRow]:
    return build_market_snapshot_rows(
        [_enriched(app_id, include_tags=index == 0) for index, app_id in enumerate(app_ids)],
        scope_name=scope_name,
        cadence="monthly",
        period_start=period_start,
        period_end=period_end,
        scope_country=scope_country,
        device_type=device_type,
        category=category,
        data_model=data_model,
        collected_at=AS_OF,
    )


def _metadata_row(
    app_id: str,
    *,
    fetched_at: datetime = AS_OF,
    name: str | None = "Example App",
    publisher: str | None = "Example Publisher",
    source: str = "publisher_name",
) -> AppMetadataRow:
    return AppMetadataRow(
        unified_app_id=app_id,
        name=name,
        publisher_display_name=publisher,
        publisher_resolution_source=source,  # type: ignore[arg-type]
        android_app_id="com.example.app",
        ios_app_id="123456",
        fetched_at=fetched_at,
    )


def _initialized_repository(tmp_path: Path) -> DuckDBRepository:
    repository = DuckDBRepository(tmp_path / "nested" / "storage.duckdb")
    repository.open()
    repository.initialize_schema()
    return repository


def test_schema_initialization_is_idempotent_and_has_no_credential_columns(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "schema" / "storage.duckdb"
    repository = DuckDBRepository(database_path)
    connection = repository.open()

    assert connection.execute("SHOW TABLES").fetchall() == []
    repository.initialize_schema()
    repository.initialize_schema()

    tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    assert tables == {"schema_migrations", "app_metadata", "market_snapshots"}
    assert connection.execute("SELECT version FROM schema_migrations").fetchall() == [(1,)]

    forbidden_fragments = ("credential", "token", "password", "secret", "url")
    for table_name in tables:
        columns = connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        column_names = {str(row[1]).lower() for row in columns}
        assert not any(
            any(fragment in column_name for fragment in forbidden_fragments)
            for column_name in column_names
        )
    repository.close()


def test_newer_schema_version_fails_without_rebuilding_database(tmp_path: Path) -> None:
    database_path = tmp_path / "newer.duckdb"
    repository = DuckDBRepository(database_path)
    connection = repository.open()
    connection.execute(
        "CREATE TABLE schema_migrations ("
        "version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL)"
    )
    connection.execute(
        "INSERT INTO schema_migrations VALUES (?, ?)",
        [99, AS_OF],
    )

    with pytest.raises(UnsupportedSchemaVersionError, match="newer"):
        repository.initialize_schema()

    assert connection.execute("SELECT version FROM schema_migrations").fetchall() == [(99,)]
    repository.close()


def test_market_mapper_preserves_order_prefers_metadata_id_and_maps_source_fields() -> None:
    metadata = SensorTowerNormalizedMetadata(
        unified_app_id="9001",
        name="Mapped App",
        publisher_display_name="Publisher",
        publisher_resolution_source="publisher_name",
        android_app_id="com.example.9001",
        ios_app_id="9001",
    )
    records = [
        _enriched(101, metadata=metadata),
        _enriched(102, include_tags=False),
    ]
    before = [record.market_record.model_dump() for record in records]

    rows = build_market_snapshot_rows(
        records,
        scope_name="global",
        cadence="monthly",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        scope_country="WW",
        device_type="total",
        category=7012,
        data_model="DM_2025_Q2",
        collected_at=AS_OF,
    )

    assert [row.rank_position for row in rows] == [1, 2]
    assert [row.source_app_id for row in rows] == ["101", "102"]
    assert [row.unified_app_id for row in rows] == ["9001", "102"]
    assert rows[0].current_units_value == 10.0
    assert rows[0].current_revenue_value == 20.0
    assert rows[0].absolute == 7.0
    assert rows[0].game_theme == "Decoration"
    assert rows[0].game_genre == "Puzzle"
    assert rows[0].earliest_release_date == date(2024, 1, 2)
    assert rows[0].release_date_ww == date(2024, 2, 3)
    assert rows[1].game_theme is None
    assert [record.market_record.model_dump() for record in records] == before


@pytest.mark.parametrize(
    ("tag_name", "field_name", "value"),
    [
        ("Game Setting", "game_setting", "N/A"),
        ("Game Setting", "game_setting", "Unknown"),
        ("Game Theme", "game_theme", "N/A"),
        ("Publisher Country", "publisher_country", "Unknown"),
    ],
)
def test_market_mapper_preserves_raw_source_literals(
    tag_name: str,
    field_name: str,
    value: str,
) -> None:
    rows = build_market_snapshot_rows(
        [_enriched(101, tag_overrides={tag_name: value})],
        scope_name="global",
        cadence="monthly",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        scope_country="WW",
        device_type="total",
        category=7012,
        data_model="DM_2025_Q2",
        collected_at=AS_OF,
    )

    assert getattr(rows[0], field_name) == value


@pytest.mark.parametrize(
    "field_name",
    [
        "source_country",
        "game_theme",
        "game_genre",
        "game_subgenre",
        "game_product_model",
        "game_art_style",
        "game_setting",
        "publisher_country",
        "most_popular_country_by_revenue",
        "is_unified_source_value",
    ],
)
def test_market_snapshot_rejects_non_string_raw_source_values(field_name: str) -> None:
    row = _snapshot_rows((101,))[0]

    with pytest.raises(StorageValidationError, match=field_name):
        replace(row, **{field_name: 123})


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("name", "Unknown"), ("publisher_display_name", "N/A")],
)
def test_app_metadata_rejects_generated_placeholder_text(
    field_name: str,
    value: str,
) -> None:
    values: dict[str, object] = {
        "unified_app_id": "1",
        "name": None,
        "publisher_display_name": None,
        "publisher_resolution_source": "unavailable",
        "android_app_id": None,
        "ios_app_id": None,
        "fetched_at": AS_OF,
    }
    values[field_name] = value

    with pytest.raises(StorageValidationError, match="placeholder text"):
        AppMetadataRow(**values)  # type: ignore[arg-type]


def test_app_metadata_missing_values_remain_none() -> None:
    row = AppMetadataRow(
        unified_app_id="1",
        name=None,
        publisher_display_name=None,
        publisher_resolution_source="unavailable",
        android_app_id=None,
        ios_app_id=None,
        fetched_at=AS_OF,
    )

    assert row.name is None
    assert row.publisher_display_name is None
    assert row.android_app_id is None
    assert row.ios_app_id is None


def test_opaque_ids_and_missing_metrics_round_trip_through_duckdb_and_parquet(
    tmp_path: Path,
) -> None:
    market_record = SensorTowerMarketRecord.model_validate(
        {
            "app_id": "synthetic-source-app-001",
            "date": "2026-08-07T00:00:00Z",
            "units_absolute": 9,
            "units_delta": 1,
            "units_transformed_delta": None,
            "revenue_absolute": 19,
            "revenue_delta": 2,
            "revenue_transformed_delta": None,
            "custom_tags": {"Game Theme": "Decoration", "Game Genre": "Puzzle"},
        }
    )
    metadata = SensorTowerNormalizedMetadata(
        unified_app_id="synthetic-unified-app-001",
        name="Synthetic App",
        publisher_display_name=None,
        publisher_resolution_source="unavailable",
        android_app_id=None,
        ios_app_id=None,
    )
    rows = build_market_snapshot_rows(
        [EnrichedMarketRecord(market_record=market_record, metadata=metadata)],
        scope_name="global",
        cadence="monthly",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        scope_country="WW",
        device_type="total",
        category=7012,
        data_model="DM_2025_Q2",
        collected_at=AS_OF,
    )

    repository = _initialized_repository(tmp_path)
    repository.replace_market_snapshot_period(rows)
    repository.upsert_app_metadata(
        [
            AppMetadataRow(
                unified_app_id="synthetic-unified-app-001",
                name=None,
                publisher_display_name=None,
                publisher_resolution_source="unavailable",
                android_app_id=None,
                ios_app_id=None,
                fetched_at=AS_OF,
            )
        ]
    )

    stored = repository.get_market_snapshot_period(rows[0].period_key)
    assert stored[0].source_app_id == "synthetic-source-app-001"
    assert stored[0].unified_app_id == "synthetic-unified-app-001"
    assert stored[0].current_units_value is None
    assert stored[0].current_revenue_value is None
    assert repository.open().execute(
        "SELECT current_units_value, current_revenue_value "
        "FROM market_snapshots WHERE unified_app_id = ?",
        ["synthetic-unified-app-001"],
    ).fetchone() == (None, None)
    assert repository.get_app_metadata(["synthetic-unified-app-001"])[
        "synthetic-unified-app-001"
    ].name is None

    cache = repository.lookup_metadata_cache(
        [" synthetic-unified-app-001 ", "synthetic-missing-app"],
        as_of=AS_OF,
    )
    assert tuple(cache.fresh_metadata_by_id) == ("synthetic-unified-app-001",)
    assert cache.missing_ids == ("synthetic-missing-app",)

    market_path = tmp_path / "exports" / "market.parquet"
    metadata_path = tmp_path / "exports" / "metadata.parquet"
    repository.export_market_snapshots_to_parquet(market_path)
    repository.export_app_metadata_to_parquet(metadata_path)
    assert repository.open().execute(
        "SELECT source_app_id, unified_app_id, current_units_value "
        "FROM read_parquet(?)",
        [str(market_path)],
    ).fetchone() == (
        "synthetic-source-app-001",
        "synthetic-unified-app-001",
        None,
    )
    assert repository.open().execute(
        "SELECT unified_app_id FROM read_parquet(?)",
        [str(metadata_path)],
    ).fetchone() == ("synthetic-unified-app-001",)
    repository.close()


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("game_setting", "N/A"),
        ("game_setting", "Unknown"),
        ("game_theme", "N/A"),
        ("publisher_country", "Unknown"),
        ("game_setting", None),
    ],
)
def test_raw_source_values_round_trip_through_duckdb_and_parquet(
    tmp_path: Path,
    field_name: str,
    value: str | None,
) -> None:
    row = replace(_snapshot_rows((101,))[0], **{field_name: value})
    repository = _initialized_repository(tmp_path)
    repository.replace_market_snapshot_period([row])

    stored = repository.get_market_snapshot_period(row.period_key)
    assert getattr(stored[0], field_name) == value

    parquet_path = tmp_path / "exports" / "market.parquet"
    repository.export_market_snapshots_to_parquet(parquet_path)
    assert repository.open().execute(
        f"SELECT {field_name} FROM read_parquet(?)",
        [str(parquet_path)],
    ).fetchone() == (value,)
    repository.close()


def test_duplicate_opaque_snapshot_ids_are_rejected_before_write(tmp_path: Path) -> None:
    repository = _initialized_repository(tmp_path)
    rows = _snapshot_rows((101, 102))
    duplicate_rows = [rows[0], replace(rows[1], unified_app_id=rows[0].unified_app_id)]

    with pytest.raises(StorageValidationError, match="unified_app_id"):
        repository.replace_market_snapshot_period(duplicate_rows)

    repository.close()


def test_metadata_mapper_stores_only_returned_metadata() -> None:
    result = parse_metadata_response(
        {
            "apps": [
                {
                    "unified_app_id": "001",
                    "name": "App 1",
                    "publisher": {"name": "Publisher 1"},
                }
            ]
        },
        [1, 2],
    )

    rows = build_app_metadata_rows(result, fetched_at=AS_OF)
    assert len(rows) == 1
    assert rows[0].unified_app_id == "1"
    assert rows[0].publisher_resolution_source == "publisher_name"
    assert result.missing_unified_app_ids == ("2",)


def test_market_period_can_be_written_read_and_replaced_idempotently(tmp_path: Path) -> None:
    repository = _initialized_repository(tmp_path)
    rows = _snapshot_rows()
    key = rows[0].period_key

    repository.replace_market_snapshot_period(rows)
    repository.replace_market_snapshot_period(rows)

    stored = repository.get_market_snapshot_period(key)
    assert [row.rank_position for row in stored] == [1, 2]
    assert [row.unified_app_id for row in stored] == ["101", "102"]
    assert stored[1].game_theme is None
    assert stored[1].current_units_value == 10.0
    repository.close()


def test_replacing_a_period_replaces_all_old_ranks(tmp_path: Path) -> None:
    repository = _initialized_repository(tmp_path)
    old_rows = _snapshot_rows((101, 102))
    repository.replace_market_snapshot_period(old_rows)

    new_rows = _snapshot_rows((202,))
    repository.replace_market_snapshot_period(new_rows)

    stored = repository.get_market_snapshot_period(new_rows[0].period_key)
    assert len(stored) == 1
    assert stored[0].unified_app_id == "202"
    repository.close()


@pytest.mark.parametrize(
    "invalid_rows",
    [
        lambda rows: [rows[0], replace(rows[1], unified_app_id=rows[0].unified_app_id)],
        lambda rows: [rows[0], replace(rows[1], rank_position=1)],
        lambda rows: [rows[0], replace(rows[1], rank_position=3)],
        lambda rows: [
            rows[0],
            replace(
                rows[1],
                period_start=date(2026, 9, 1),
                period_end=date(2026, 9, 30),
            ),
        ],
        lambda rows: [rows[0], replace(rows[1], scope_country="US")],
    ],
)
def test_invalid_period_replacement_is_rejected_before_write(
    tmp_path: Path,
    invalid_rows: object,
) -> None:
    repository = _initialized_repository(tmp_path)
    old_rows = _snapshot_rows((101, 102))
    repository.replace_market_snapshot_period(old_rows)
    invalid = invalid_rows(old_rows)  # type: ignore[operator]

    with pytest.raises(StorageValidationError):
        repository.replace_market_snapshot_period(invalid)

    assert repository.get_market_snapshot_period(old_rows[0].period_key) == old_rows
    repository.close()


def test_metadata_upsert_round_trips_nulls_and_latest_duplicate_wins(tmp_path: Path) -> None:
    repository = _initialized_repository(tmp_path)
    initial = _metadata_row("001")
    latest = _metadata_row(
        "1",
        name=None,
        publisher=None,
        source="unavailable",
    )

    repository.upsert_app_metadata([initial, latest, _metadata_row("2")])
    result = repository.get_app_metadata([2, "001", 2, "3"])

    assert list(result) == ["2", "1"]
    assert result["1"].name is None
    assert result["1"].publisher_display_name is None
    assert result["1"].android_app_id is not None
    assert result["1"].ios_app_id is not None
    repository.close()


def test_metadata_cache_distinguishes_fresh_stale_missing_and_deduplicates_ids(
    tmp_path: Path,
) -> None:
    repository = _initialized_repository(tmp_path)
    repository.upsert_app_metadata(
        [
            _metadata_row("1", fetched_at=AS_OF - timedelta(days=14)),
            _metadata_row("2", fetched_at=AS_OF - timedelta(days=14, seconds=1)),
            _metadata_row("3", fetched_at=AS_OF, name=None, publisher=None),
        ]
    )

    result = repository.lookup_metadata_cache(
        ["3", "1", "2", "4", "1"],
        as_of=AS_OF,
    )

    assert list(result.fresh_metadata_by_id) == ["3", "1"]
    assert result.stale_ids == ("2",)
    assert result.missing_ids == ("4",)
    assert result.ids_to_fetch == ("2", "4")
    assert result.fresh_metadata_by_id["3"].name is None
    repository.close()


def test_metadata_cache_rejects_naive_as_of_and_negative_age(tmp_path: Path) -> None:
    repository = _initialized_repository(tmp_path)
    with pytest.raises(StorageValidationError, match="timezone-aware"):
        repository.lookup_metadata_cache(["1"], as_of=datetime(2026, 8, 10))
    with pytest.raises(StorageValidationError, match="non-negative"):
        repository.lookup_metadata_cache(["1"], as_of=AS_OF, max_age_days=-1)
    repository.close()


def test_parquet_exports_are_readable_ordered_and_atomic(tmp_path: Path) -> None:
    repository = _initialized_repository(tmp_path)
    rows = _snapshot_rows((102, 101))
    repository.replace_market_snapshot_period(rows)
    repository.upsert_app_metadata([_metadata_row("2"), _metadata_row("1")])

    market_path = tmp_path / "exports" / "market.parquet"
    metadata_path = tmp_path / "exports" / "metadata.parquet"
    repository.export_market_snapshots_to_parquet(market_path)
    repository.export_app_metadata_to_parquet(metadata_path)

    assert market_path.exists()
    assert metadata_path.exists()
    assert repository.open().execute(
        "SELECT unified_app_id, rank_position FROM read_parquet(?) ORDER BY rank_position",
        [str(market_path)],
    ).fetchall() == [("102", 1), ("101", 2)]
    assert repository.open().execute(
        "SELECT unified_app_id FROM read_parquet(?)",
        [str(metadata_path)],
    ).fetchall() == [("1",), ("2",)]
    assert repository.open().execute(
        "SELECT count(*) FROM read_parquet(?)",
        [str(market_path)],
    ).fetchone() == (2,)
    assert repository.open().execute(
        "SELECT count(*) FROM read_parquet(?)",
        [str(metadata_path)],
    ).fetchone() == (2,)

    previous_bytes = market_path.read_bytes()
    repository.close()
    with pytest.raises(RepositoryNotOpenError):
        repository.export_market_snapshots_to_parquet(market_path)
    assert market_path.read_bytes() == previous_bytes


def test_no_production_database_is_created_by_test_helpers(tmp_path: Path) -> None:
    repository = DuckDBRepository(tmp_path / "only-test.duckdb")
    repository.close()
    assert not (tmp_path / "only-test.duckdb").exists()


def test_duckdb_schema_does_not_include_credential_columns(tmp_path: Path) -> None:
    repository = _initialized_repository(tmp_path)
    connection = repository.open()
    for table_name in ("schema_migrations", "app_metadata", "market_snapshots"):
        columns = connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        assert not any(
            any(
                fragment in str(column[1]).lower()
                for fragment in ("token", "credential", "password", "secret", "url")
            )
            for column in columns
        )
    repository.close()


def test_duckdb_files_are_not_written_outside_tmp_path(tmp_path: Path) -> None:
    connection = duckdb.connect(":memory:")
    assert connection.execute("SELECT 1").fetchone() == (1,)
    connection.close()
