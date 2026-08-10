"""Mock-only tests for DB-002 single-month collection orchestration."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from src.config import AppConfig
from src.sensor_tower import (
    SensorTowerMetadataBatchError,
    SensorTowerMetadataFetchResult,
    SensorTowerMetadataIntegrityError,
    SensorTowerMetadataRequest,
    SensorTowerNormalizedMetadata,
    SensorTowerRequestError,
)
from src.sensor_tower.dto import SensorTowerMarketRecord
from src.storage import (
    AppMetadataRow,
    DuckDBRepository,
    ParquetExportError,
    SnapshotPeriodKey,
    StorageValidationError,
)
from src.workflows import (
    CollectMonthRequest,
    InvalidMonthError,
    collect_month,
    format_collection_summary,
)

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _market_record(
    app_id: int | str,
    *,
    genre: str = "Puzzle",
    revenue_country: str | None = None,
    current_units_value: float = 10,
    game_setting: object | None = None,
) -> SensorTowerMarketRecord:
    tags: dict[str, object] = {"Game Genre": genre}
    if revenue_country is not None:
        tags["Most Popular Country by Revenue"] = revenue_country
    if game_setting is not None:
        tags["Game Setting"] = game_setting
    return SensorTowerMarketRecord.model_validate(
        {
            "app_id": app_id,
            "country": "WW",
            "date": "2026-07-15T00:00:00Z",
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


def _live_market_record(app_id: str, *, genre: str = "Puzzle") -> SensorTowerMarketRecord:
    """Synthetic live-shape row with only the currently observed metrics."""

    return SensorTowerMarketRecord.model_validate(
        {
            "app_id": app_id,
            "date": "2026-07-15T00:00:00Z",
            "units_absolute": 9,
            "units_delta": 1,
            "units_transformed_delta": None,
            "revenue_absolute": 19,
            "revenue_delta": 2,
            "revenue_transformed_delta": None,
            "custom_tags": {"Game Genre": genre, "Game Theme": "Decoration"},
        }
    )


def _normalized_metadata(app_id: str) -> SensorTowerNormalizedMetadata:
    return SensorTowerNormalizedMetadata(
        unified_app_id=app_id,
        name=f"App {app_id}",
        publisher_display_name=f"Publisher {app_id}",
        publisher_resolution_source="publisher_name",
        android_app_id=f"com.example.{app_id}",
        ios_app_id=app_id,
    )


def _metadata_row(
    app_id: str,
    *,
    fetched_at: datetime,
    name: str | None = None,
) -> AppMetadataRow:
    return AppMetadataRow(
        unified_app_id=app_id,
        name=name if name is not None else f"Cached {app_id}",
        publisher_display_name=f"Cached Publisher {app_id}",
        publisher_resolution_source="publisher_name",
        android_app_id=f"com.cached.{app_id}",
        ios_app_id=app_id,
        fetched_at=fetched_at,
    )


class FakeCollectionClient:
    """Small injected client; no HTTP transport or real credentials are used."""

    def __init__(
        self,
        candidates: list[SensorTowerMarketRecord] | Exception,
        *,
        omit_metadata_ids: set[str] | None = None,
        metadata_error: Exception | None = None,
    ) -> None:
        self.candidates = candidates
        self.omit_metadata_ids = set() if omit_metadata_ids is None else omit_metadata_ids
        self.metadata_error = metadata_error
        self.market_calls = 0
        self.metadata_requests: list[tuple[str, ...]] = []

    def fetch_market_candidates(self, request: object) -> list[SensorTowerMarketRecord]:
        self.market_calls += 1
        if isinstance(self.candidates, Exception):
            raise self.candidates
        return self.candidates

    def fetch_metadata_batch(
        self,
        request: SensorTowerMetadataRequest,
    ) -> SensorTowerMetadataFetchResult:
        self.metadata_requests.append(request.app_ids)
        if self.metadata_error is not None:
            raise self.metadata_error
        metadata = {
            app_id: _normalized_metadata(app_id)
            for app_id in request.app_ids
            if app_id not in self.omit_metadata_ids
        }
        missing = tuple(app_id for app_id in request.app_ids if app_id not in metadata)
        return SensorTowerMetadataFetchResult(
            metadata_by_unified_app_id=metadata,
            requested_unified_app_ids=request.app_ids,
            missing_unified_app_ids=missing,
            requested_count=len(request.app_ids),
            returned_count=len(metadata),
        )

    def close(self) -> None:
        return None


def _config() -> AppConfig:
    return AppConfig(
        sensor_tower_api_url="https://api.sensortower.com",
        sensor_tower_api_limit=6,
        sensor_tower_final_top_n=4,
        sensor_tower_metadata_max_retries=0,
        sensor_tower_metadata_retry_delay_seconds=0,
        sensor_tower_metadata_batch_delay_seconds=0,
    )


def _request(tmp_path: Path, *, skip_export: bool = False) -> CollectMonthRequest:
    return CollectMonthRequest(
        month="2026-07",
        database_path=tmp_path / "data" / "collection.duckdb",
        export_directory=tmp_path / "exports",
        skip_export=skip_export,
    )


def _initialize_repository(database_path: Path) -> DuckDBRepository:
    repository = DuckDBRepository(database_path)
    repository.open()
    repository.initialize_schema()
    return repository


def test_completed_month_resolves_boundaries_and_rejects_invalid_months() -> None:
    from src.workflows import MonthlyPeriod

    period = MonthlyPeriod.parse("2024-02", current_utc=NOW)
    assert period.period_start == date(2024, 2, 1)
    assert period.period_end == date(2024, 2, 29)

    for value in ("2026-7", "2026/07", "2026-13", "2026-00", "2026-07-01"):
        with pytest.raises(InvalidMonthError):
            MonthlyPeriod.parse(value, current_utc=NOW)

    for value in ("2026-08", "2026-09"):
        with pytest.raises(InvalidMonthError):
            MonthlyPeriod.parse(value, current_utc=NOW)

    assert MonthlyPeriod.parse("2026-07", current_utc=NOW).period_end == date(2026, 7, 31)


def test_plan_only_validates_without_client_database_or_files(tmp_path: Path) -> None:
    client = FakeCollectionClient([])
    request = _request(tmp_path)

    summary = collect_month(
        request.__class__(
            month=request.month,
            database_path=request.database_path,
            export_directory=request.export_directory,
            plan_only=True,
        ),
        _config(),
        current_utc=NOW,
        utc_clock=lambda: NOW,
        client=client,
    )

    assert summary.plan_only is True
    assert summary.period_start == date(2026, 7, 1)
    assert summary.period_end == date(2026, 7, 31)
    assert client.market_calls == 0
    assert not request.database_path.exists()
    assert not request.export_directory.exists()
    assert "Collection plan validated" in format_collection_summary(summary)


def test_workflow_filters_before_metadata_and_exports_rows_in_selected_order(
    tmp_path: Path,
) -> None:
    client = FakeCollectionClient(
        [
            _market_record(1, genre="Arcade"),
            _market_record(2),
            _market_record(3, genre="Tabletop"),
            _market_record(4, revenue_country="China"),
        ]
    )

    summary = collect_month(
        _request(tmp_path),
        _config(),
        current_utc=NOW,
        utc_clock=lambda: NOW,
        client=client,
        metadata_sleep=lambda _: None,
    )

    assert summary.candidate_count == 4
    assert summary.selected_count == 2
    assert summary.metadata_requested_count == 2
    assert summary.metadata_returned_count == 2
    assert summary.snapshot_rows_written == 2
    assert client.metadata_requests == [("2", "3")]
    assert summary.market_parquet_path is not None
    assert summary.metadata_parquet_path is not None
    assert summary.market_parquet_path.exists()
    assert summary.metadata_parquet_path.exists()
    rendered_summary = format_collection_summary(summary)
    assert "987654321" not in rendered_summary
    assert "unit-test-token" not in rendered_summary

    repository = _initialize_repository(summary.database_path)
    key = SnapshotPeriodKey(
        scope_name="casual_puzzle_tabletop",
        cadence="monthly",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
    )
    rows = repository.get_market_snapshot_period(key)
    assert [(row.rank_position, row.unified_app_id) for row in rows] == [(1, "2"), (2, "3")]
    metadata = repository.get_app_metadata(["2", "3"])
    assert list(metadata) == ["2", "3"]
    repository.close()


@pytest.mark.parametrize("game_setting", ["N/A", "Unknown"])
def test_complete_month_preserves_raw_source_literal_through_storage_and_parquet(
    tmp_path: Path,
    game_setting: str,
) -> None:
    client = FakeCollectionClient([_market_record("synthetic-app-001", game_setting=game_setting)])

    summary = collect_month(
        _request(tmp_path),
        _config(),
        current_utc=NOW,
        utc_clock=lambda: NOW,
        client=client,
        metadata_sleep=lambda _: None,
    )

    assert summary.snapshot_rows_written == 1
    assert summary.metadata_returned_count == 1
    assert summary.market_parquet_path is not None
    assert summary.metadata_parquet_path is not None
    assert summary.market_parquet_path.exists()
    assert summary.metadata_parquet_path.exists()

    rendered_summary = format_collection_summary(summary)
    assert game_setting not in rendered_summary
    assert "synthetic-app-001" not in rendered_summary
    assert "auth_token" not in rendered_summary
    assert "https://api.sensortower.com" not in rendered_summary

    repository = _initialize_repository(summary.database_path)
    key = SnapshotPeriodKey(
        scope_name="casual_puzzle_tabletop",
        cadence="monthly",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
    )
    rows = repository.get_market_snapshot_period(key)
    assert len(rows) == 1
    assert rows[0].game_setting == game_setting
    assert list(repository.get_app_metadata(["synthetic-app-001"])) == [
        "synthetic-app-001"
    ]
    assert repository.open().execute(
        "SELECT game_setting FROM read_parquet(?)",
        [str(summary.market_parquet_path)],
    ).fetchone() == (game_setting,)
    repository.close()


def test_live_shape_opaque_ids_flow_through_metadata_cache_and_snapshot_order(
    tmp_path: Path,
) -> None:
    client = FakeCollectionClient(
        [
            _live_market_record("synthetic-unified-app-002"),
            _live_market_record("synthetic-unified-app-001"),
        ]
    )

    summary = collect_month(
        _request(tmp_path, skip_export=True),
        _config(),
        current_utc=NOW,
        utc_clock=lambda: NOW,
        client=client,
        metadata_sleep=lambda _: None,
    )

    assert summary.metadata_requested_count == 2
    assert client.metadata_requests == [
        ("synthetic-unified-app-002", "synthetic-unified-app-001")
    ]
    repository = _initialize_repository(summary.database_path)
    rows = repository.get_market_snapshot_period(
        SnapshotPeriodKey(
            scope_name="casual_puzzle_tabletop",
            cadence="monthly",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
        )
    )
    assert [(row.rank_position, row.source_app_id, row.unified_app_id) for row in rows] == [
        (1, "synthetic-unified-app-002", "synthetic-unified-app-002"),
        (2, "synthetic-unified-app-001", "synthetic-unified-app-001"),
    ]
    assert all(row.current_units_value is None for row in rows)
    assert all(row.current_revenue_value is None for row in rows)
    repository.close()


def test_fresh_cache_is_reused_and_only_missing_id_is_requested(tmp_path: Path) -> None:
    database_path = tmp_path / "cached.duckdb"
    repository = _initialize_repository(database_path)
    cached_time = NOW - timedelta(days=1)
    repository.upsert_app_metadata([_metadata_row("2", fetched_at=cached_time)])
    repository.close()

    client = FakeCollectionClient([_market_record(2), _market_record(3)])
    request = CollectMonthRequest(
        month="2026-07",
        database_path=database_path,
        export_directory=tmp_path / "exports",
        skip_export=True,
    )
    summary = collect_month(
        request,
        _config(),
        current_utc=NOW,
        utc_clock=lambda: NOW,
        client=client,
        metadata_sleep=lambda _: None,
    )

    assert summary.metadata_cache_fresh_count == 1
    assert summary.metadata_missing_count == 1
    assert summary.metadata_requested_count == 1
    assert client.metadata_requests == [("3",)]
    assert not request.export_directory.exists()

    repository = _initialize_repository(database_path)
    metadata = repository.get_app_metadata(["2", "3"])
    assert metadata["2"].fetched_at == cached_time
    assert metadata["3"].fetched_at == NOW
    repository.close()


def test_stale_cache_is_not_used_when_refresh_omits_the_id(tmp_path: Path) -> None:
    database_path = tmp_path / "stale.duckdb"
    repository = _initialize_repository(database_path)
    stale_time = NOW - timedelta(days=15)
    repository.upsert_app_metadata([_metadata_row("2", fetched_at=stale_time, name="Stale")])
    repository.close()

    client = FakeCollectionClient(
        [_market_record(2)],
        omit_metadata_ids={"2"},
    )
    request = CollectMonthRequest(
        month="2026-07",
        database_path=database_path,
        export_directory=tmp_path / "exports",
        skip_export=True,
    )
    summary = collect_month(
        request,
        _config(),
        current_utc=NOW,
        utc_clock=lambda: NOW,
        client=client,
        metadata_sleep=lambda _: None,
    )

    assert summary.metadata_stale_count == 1
    assert summary.metadata_unresolved_count == 1
    repository = _initialize_repository(database_path)
    assert repository.get_app_metadata(["2"])["2"].name == "Stale"
    assert repository.get_app_metadata(["2"])["2"].fetched_at == stale_time
    assert len(repository.get_market_snapshot_period(
        SnapshotPeriodKey(
            scope_name="casual_puzzle_tabletop",
            cadence="monthly",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
        )
    )) == 1
    repository.close()


def test_rerunning_month_replaces_ranks_and_is_idempotent(tmp_path: Path) -> None:
    request = _request(tmp_path, skip_export=True)
    first_client = FakeCollectionClient([_market_record(1), _market_record(2)])
    collect_month(
        request,
        _config(),
        current_utc=NOW,
        utc_clock=lambda: NOW,
        client=first_client,
        metadata_sleep=lambda _: None,
    )

    second_client = FakeCollectionClient([_market_record(2), _market_record(1)])
    summary = collect_month(
        request,
        _config(),
        current_utc=NOW,
        utc_clock=lambda: NOW,
        client=second_client,
        metadata_sleep=lambda _: None,
    )

    assert second_client.metadata_requests == []
    assert summary.snapshot_rows_written == 2
    repository = _initialize_repository(request.database_path)
    rows = repository.get_market_snapshot_period(
        SnapshotPeriodKey(
            scope_name="casual_puzzle_tabletop",
            cadence="monthly",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
        )
    )
    assert [(row.rank_position, row.unified_app_id) for row in rows] == [(1, "2"), (2, "1")]
    repository.close()


def test_market_or_selection_failure_writes_no_database_period(tmp_path: Path) -> None:
    market_failure = FakeCollectionClient(SensorTowerRequestError("market failed"))
    with pytest.raises(SensorTowerRequestError):
        collect_month(
            _request(tmp_path),
            _config(),
            current_utc=NOW,
            utc_clock=lambda: NOW,
            client=market_failure,
        )
    assert not (_request(tmp_path).database_path).exists()

    no_eligible = FakeCollectionClient([_market_record(1, genre="Arcade")])
    with pytest.raises(Exception, match="No eligible"):
        collect_month(
            _request(tmp_path),
            _config(),
            current_utc=NOW,
            utc_clock=lambda: NOW,
            client=no_eligible,
        )


def test_metadata_failure_writes_no_market_period(tmp_path: Path) -> None:
    client = FakeCollectionClient(
        [_market_record(1)],
        metadata_error=SensorTowerMetadataBatchError(1, 1),
    )
    request = _request(tmp_path, skip_export=True)
    with pytest.raises(SensorTowerMetadataBatchError):
        collect_month(
            request,
            _config(),
            current_utc=NOW,
            utc_clock=lambda: NOW,
            client=client,
        )

    repository = _initialize_repository(request.database_path)
    assert repository.open().execute("SELECT count(*) FROM market_snapshots").fetchone() == (0,)
    repository.close()


def test_metadata_integrity_failure_writes_no_market_period(tmp_path: Path) -> None:
    client = FakeCollectionClient(
        [_market_record(1)],
        metadata_error=SensorTowerMetadataIntegrityError("metadata integrity failed"),
    )
    request = _request(tmp_path, skip_export=True)
    with pytest.raises(SensorTowerMetadataIntegrityError):
        collect_month(
            request,
            _config(),
            current_utc=NOW,
            utc_clock=lambda: NOW,
            client=client,
        )

    repository = _initialize_repository(request.database_path)
    assert repository.open().execute("SELECT count(*) FROM market_snapshots").fetchone() == (0,)
    repository.close()


def test_mapping_failure_happens_before_metadata_or_snapshot_write(tmp_path: Path) -> None:
    client = FakeCollectionClient([_market_record(1, current_units_value=float("nan"))])
    request = _request(tmp_path, skip_export=True)

    with pytest.raises(StorageValidationError):
        collect_month(
            request,
            _config(),
            current_utc=NOW,
            utc_clock=lambda: NOW,
            client=client,
        )

    repository = _initialize_repository(request.database_path)
    assert repository.open().execute("SELECT count(*) FROM market_snapshots").fetchone() == (0,)
    assert repository.open().execute("SELECT count(*) FROM app_metadata").fetchone() == (0,)
    repository.close()


def test_invalid_non_string_source_tag_fails_before_metadata_or_snapshot_write(
    tmp_path: Path,
) -> None:
    client = FakeCollectionClient([_market_record(1, game_setting=123)])
    request = _request(tmp_path, skip_export=True)

    with pytest.raises(StorageValidationError, match="game_setting"):
        collect_month(
            request,
            _config(),
            current_utc=NOW,
            utc_clock=lambda: NOW,
            client=client,
        )

    repository = _initialize_repository(request.database_path)
    assert repository.open().execute("SELECT count(*) FROM market_snapshots").fetchone() == (0,)
    assert repository.open().execute("SELECT count(*) FROM app_metadata").fetchone() == (0,)
    repository.close()


def test_export_failure_leaves_committed_duckdb_rows(tmp_path: Path) -> None:
    request = _request(tmp_path)
    client = FakeCollectionClient([_market_record(1)])

    def fail_metadata_export(repository: object, path: Path) -> None:
        raise ParquetExportError("app_metadata", str(path))

    with pytest.raises(ParquetExportError):
        collect_month(
            request,
            _config(),
            current_utc=NOW,
            utc_clock=lambda: NOW,
            client=client,
            metadata_exporter=fail_metadata_export,
        )

    repository = _initialize_repository(request.database_path)
    assert repository.open().execute("SELECT count(*) FROM market_snapshots").fetchone() == (1,)
    repository.close()
