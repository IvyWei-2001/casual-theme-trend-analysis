"""Mock-only tests for HIST-001 resumable monthly backfill orchestration."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.config import AppConfig
from src.sensor_tower import (
    SensorTowerMetadataFetchResult,
    SensorTowerMetadataRequest,
    SensorTowerNormalizedMetadata,
    SensorTowerRequestError,
)
from src.sensor_tower.dto import SensorTowerMarketRecord
from src.storage import DuckDBRepository, ParquetExportError, SnapshotPeriodKey
from src.workflows import (
    BackfillMonthRange,
    BackfillMonthsError,
    BackfillMonthsRequest,
    CollectMonthRequest,
    InvalidMonthError,
    backfill_months,
    collect_month,
    format_backfill_summary,
)

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _config() -> AppConfig:
    return AppConfig(
        sensor_tower_api_url="https://api.sensortower.com",
        sensor_tower_api_limit=6,
        sensor_tower_final_top_n=4,
        sensor_tower_metadata_max_retries=0,
        sensor_tower_metadata_retry_delay_seconds=0,
        sensor_tower_metadata_batch_delay_seconds=0,
    )


def _record(app_id: str, month: str) -> SensorTowerMarketRecord:
    return SensorTowerMarketRecord.model_validate(
        {
            "app_id": app_id,
            "date": f"{month}-15T00:00:00Z",
            "units_absolute": 9,
            "units_delta": 1,
            "revenue_absolute": 19,
            "revenue_delta": 2,
            "custom_tags": {"Game Genre": "Puzzle", "Game Theme": "Decoration"},
        }
    )


class ScenarioClient:
    """Small deterministic client fake keyed by the requested calendar month."""

    def __init__(
        self,
        market_by_month: dict[str, list[SensorTowerMarketRecord] | Exception],
    ) -> None:
        self.market_by_month = market_by_month
        self.market_months: list[str] = []
        self.metadata_requests: list[tuple[str, ...]] = []
        self.metadata_call_count: dict[str, int] = {}
        self.closed = False

    def fetch_market_candidates(self, request: object) -> list[SensorTowerMarketRecord]:
        month = request.date.strftime("%Y-%m")  # type: ignore[attr-defined]
        self.market_months.append(month)
        result = self.market_by_month[month]
        if isinstance(result, Exception):
            raise result
        return list(result)

    def fetch_metadata_batch(
        self,
        request: SensorTowerMetadataRequest,
    ) -> SensorTowerMetadataFetchResult:
        self.metadata_requests.append(request.app_ids)
        metadata: dict[str, SensorTowerNormalizedMetadata] = {}
        for app_id in request.app_ids:
            call_count = self.metadata_call_count.get(app_id, 0) + 1
            self.metadata_call_count[app_id] = call_count
            metadata[app_id] = SensorTowerNormalizedMetadata(
                unified_app_id=app_id,
                name=f"App {app_id} call {call_count}",
                publisher_display_name=f"Publisher {app_id}",
                publisher_resolution_source="publisher_name",
                android_app_id=f"com.example.{app_id}",
                ios_app_id=app_id,
            )
        return SensorTowerMetadataFetchResult(
            metadata_by_unified_app_id=metadata,
            requested_unified_app_ids=request.app_ids,
            missing_unified_app_ids=(),
            requested_count=len(request.app_ids),
            returned_count=len(metadata),
        )

    def close(self) -> None:
        self.closed = True


class CountingRepository(DuckDBRepository):
    """Repository spy that verifies HIST-001 owns one initialized instance."""

    def __init__(self, database_path: Path) -> None:
        super().__init__(database_path)
        self.open_calls = 0
        self.initialize_calls = 0
        self.close_calls = 0

    def open(self):
        self.open_calls += 1
        return super().open()

    def initialize_schema(self) -> None:
        self.initialize_calls += 1
        super().initialize_schema()

    def close(self) -> None:
        self.close_calls += 1
        super().close()


def _request(
    tmp_path: Path,
    start: str,
    end: str,
    *,
    plan_only: bool = False,
    refresh_existing: bool = False,
    skip_export: bool = False,
) -> BackfillMonthsRequest:
    return BackfillMonthsRequest(
        start_month=start,
        end_month=end,
        database_path=tmp_path / "data" / "history.duckdb",
        export_directory=tmp_path / "exports",
        plan_only=plan_only,
        refresh_existing=refresh_existing,
        skip_export=skip_export,
    )


def _period_key(month: str) -> SnapshotPeriodKey:
    period = BackfillMonthRange.parse(month, month, current_utc=NOW).periods[0]
    return SnapshotPeriodKey(
        scope_name="casual_puzzle_tabletop",
        cadence="monthly",
        period_start=period.period_start,
        period_end=period.period_end,
    )


def _stored_months(database_path: Path, months: tuple[str, ...]) -> dict[str, int]:
    repository = DuckDBRepository(database_path)
    repository.open()
    repository.initialize_schema()
    result = {
        month: len(repository.get_market_snapshot_period(_period_key(month)))
        for month in months
    }
    repository.close()
    return result


def _seed_months(
    tmp_path: Path,
    months_to_ids: dict[str, tuple[str, ...]],
) -> None:
    market_by_month = {
        month: [_record(app_id, month) for app_id in app_ids]
        for month, app_ids in months_to_ids.items()
    }
    client = ScenarioClient(market_by_month)
    for month in months_to_ids:
        collect_month(
            request=CollectMonthRequest(
                month=month,
                database_path=tmp_path / "data" / "history.duckdb",
                export_directory=tmp_path / "exports",
                skip_export=True,
            ),
            config=_config(),
            current_utc=NOW,
            client=client,
            metadata_sleep=lambda _: None,
        )


def test_backfill_range_is_inclusive_and_handles_year_and_leap_boundaries() -> None:
    assert BackfillMonthRange.parse("2026-07", "2026-07", current_utc=NOW).months == (
        "2026-07",
    )
    assert BackfillMonthRange.parse("2025-12", "2026-02", current_utc=NOW).months == (
        "2025-12",
        "2026-01",
        "2026-02",
    )
    leap_period = BackfillMonthRange.parse(
        "2024-02",
        "2024-03",
        current_utc=NOW,
    ).periods[0]
    assert leap_period.period_end == date(2024, 2, 29)


@pytest.mark.parametrize(
    ("start_month", "end_month"),
    [
        ("2026-7", "2026-07"),
        ("2026-07", "2026/08"),
        ("2026-13", "2026-13"),
        ("2026-00", "2026-01"),
        ("2026-08-01", "2026-08-01"),
        ("2026-08", "2026-07"),
        ("2026-08", "2026-08"),
        ("2026-07", "2026-09"),
    ],
)
def test_backfill_range_rejects_malformed_reversed_current_and_future_months(
    start_month: str,
    end_month: str,
) -> None:
    with pytest.raises(InvalidMonthError):
        BackfillMonthRange.parse(start_month, end_month, current_utc=NOW)


def test_plan_only_does_not_construct_dependencies_open_database_or_create_files(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path, "2026-06", "2026-07", plan_only=True)

    def fail_client_factory() -> ScenarioClient:
        raise AssertionError("client factory must not run in plan-only mode")

    def fail_repository_factory(path: Path) -> DuckDBRepository:
        raise AssertionError(f"repository factory must not run: {path}")

    summary = backfill_months(
        request,
        _config(),
        current_utc=NOW,
        client_factory=fail_client_factory,
        repository_factory=fail_repository_factory,
    )

    rendered = format_backfill_summary(summary)
    assert summary.planned_months == ("2026-06", "2026-07")
    assert summary.planned_month_count == 2
    assert "2026-06" in rendered and "2026-07" in rendered
    assert "app-001" not in rendered
    assert "unit-test-token" not in rendered
    assert "https://api.sensortower.com" not in rendered
    assert not request.database_path.exists()
    assert not request.export_directory.exists()


def test_existing_months_are_skipped_without_client_and_refresh_replaces_them(
    tmp_path: Path,
) -> None:
    _seed_months(
        tmp_path,
        {"2026-06": ("old-june",), "2026-07": ("old-july",)},
    )

    def fail_client_factory() -> ScenarioClient:
        raise AssertionError("skipped months must not construct a client")

    skipped = backfill_months(
        _request(tmp_path, "2026-06", "2026-07", skip_export=True),
        _config(),
        current_utc=NOW,
        client_factory=fail_client_factory,
    )
    assert skipped.collected_month_count == 0
    assert skipped.skipped_existing_month_count == 2

    refresh_client = ScenarioClient(
        {
            "2026-06": [_record("new-june", "2026-06")],
            "2026-07": [_record("new-july", "2026-07")],
        }
    )
    refreshed = backfill_months(
        _request(
            tmp_path,
            "2026-06",
            "2026-07",
            refresh_existing=True,
            skip_export=True,
        ),
        _config(),
        current_utc=NOW,
        client=refresh_client,
        metadata_sleep=lambda _: None,
    )
    assert refreshed.collected_month_count == 2
    assert refreshed.skipped_existing_month_count == 0
    assert refresh_client.market_months == ["2026-06", "2026-07"]
    assert _stored_months(tmp_path / "data" / "history.duckdb", ("2026-06", "2026-07")) == {
        "2026-06": 1,
        "2026-07": 1,
    }


def test_missing_months_reuse_one_metadata_cache_and_aggregate_counts(
    tmp_path: Path,
) -> None:
    client = ScenarioClient(
        {
            "2026-06": [_record("app-1", "2026-06"), _record("app-2", "2026-06")],
            "2026-07": [_record("app-2", "2026-07"), _record("app-3", "2026-07")],
        }
    )

    summary = backfill_months(
        _request(tmp_path, "2026-06", "2026-07", skip_export=True),
        _config(),
        current_utc=NOW,
        client=client,
        metadata_sleep=lambda _: None,
    )

    assert client.market_months == ["2026-06", "2026-07"]
    assert client.metadata_requests == [("app-1", "app-2"), ("app-3",)]
    assert summary.total_metadata_cache_fresh_count == 1
    assert summary.total_metadata_requested_count == 3
    assert summary.total_metadata_returned_count == 3
    assert summary.total_snapshot_rows_written == 4

    repository = DuckDBRepository(summary.database_path)
    repository.open()
    repository.initialize_schema()
    metadata = repository.get_app_metadata(("app-1", "app-2", "app-3"))
    assert metadata["app-2"].name == "App app-2 call 1"
    assert metadata["app-2"].fetched_at == NOW
    repository.close()


def test_backfill_lazily_creates_and_reuses_one_client_and_initialized_repository(
    tmp_path: Path,
) -> None:
    client = ScenarioClient(
        {
            "2026-06": [_record("app-1", "2026-06")],
            "2026-07": [_record("app-2", "2026-07")],
        }
    )
    repository_holder: list[CountingRepository] = []

    def build_repository(path: Path) -> CountingRepository:
        repository = CountingRepository(path)
        repository_holder.append(repository)
        return repository

    client_factory_calls = 0

    def build_client() -> ScenarioClient:
        nonlocal client_factory_calls
        client_factory_calls += 1
        return client

    summary = backfill_months(
        _request(tmp_path, "2026-06", "2026-07", skip_export=True),
        _config(),
        current_utc=NOW,
        client_factory=build_client,
        repository_factory=build_repository,
        metadata_sleep=lambda _: None,
    )

    assert summary.collected_month_count == 2
    assert client_factory_calls == 1
    assert client.market_months == ["2026-06", "2026-07"]
    assert client.closed is True
    assert len(repository_holder) == 1
    assert repository_holder[0].open_calls == 1
    assert repository_holder[0].initialize_calls == 1
    assert repository_holder[0].close_calls == 1


def test_failure_is_fail_fast_preserves_prior_month_and_resume_skips_it(
    tmp_path: Path,
) -> None:
    first_client = ScenarioClient(
        {
            "2026-05": [_record("app-may", "2026-05")],
            "2026-06": SensorTowerRequestError("raw app-should-not-leak"),
            "2026-07": [_record("app-july", "2026-07")],
        }
    )
    export_calls = {"market": 0, "metadata": 0}

    def count_market_export(repository: object, path: Path) -> None:
        export_calls["market"] += 1

    def count_metadata_export(repository: object, path: Path) -> None:
        export_calls["metadata"] += 1

    with pytest.raises(BackfillMonthsError) as failure:
        backfill_months(
            _request(tmp_path, "2026-05", "2026-07"),
            _config(),
            current_utc=NOW,
            client=first_client,
            metadata_sleep=lambda _: None,
            market_exporter=count_market_export,
            metadata_exporter=count_metadata_export,
        )

    assert failure.value.failed_month == "2026-06"
    assert failure.value.failure_kind == "sensor_tower"
    assert "app-should-not-leak" not in str(failure.value)
    assert "auth_token" not in str(failure.value)
    assert first_client.market_months == ["2026-05", "2026-06"]
    assert export_calls == {"market": 0, "metadata": 0}
    assert _stored_months(tmp_path / "data" / "history.duckdb", ("2026-05",)) == {
        "2026-05": 1
    }

    resume_client = ScenarioClient(
        {
            "2026-05": [_record("app-may-new", "2026-05")],
            "2026-06": [_record("app-june", "2026-06")],
            "2026-07": [_record("app-july", "2026-07")],
        }
    )
    resumed = backfill_months(
        _request(tmp_path, "2026-05", "2026-07", skip_export=True),
        _config(),
        current_utc=NOW,
        client=resume_client,
        metadata_sleep=lambda _: None,
    )
    assert resumed.collected_month_count == 2
    assert resumed.skipped_existing_month_count == 1
    assert resume_client.market_months == ["2026-06", "2026-07"]


def test_final_exports_run_once_after_all_months_and_skip_export_runs_none(
    tmp_path: Path,
) -> None:
    client = ScenarioClient(
        {
            "2026-06": [_record("app-1", "2026-06")],
            "2026-07": [_record("app-2", "2026-07")],
        }
    )
    export_calls = {"market": 0, "metadata": 0}

    def count_market_export(repository: object, path: Path) -> None:
        export_calls["market"] += 1

    def count_metadata_export(repository: object, path: Path) -> None:
        export_calls["metadata"] += 1

    summary = backfill_months(
        _request(tmp_path, "2026-06", "2026-07"),
        _config(),
        current_utc=NOW,
        client=client,
        metadata_sleep=lambda _: None,
        market_exporter=count_market_export,
        metadata_exporter=count_metadata_export,
    )
    assert export_calls == {"market": 1, "metadata": 1}
    assert summary.market_parquet_path == tmp_path / "exports" / "market_snapshots.parquet"
    assert summary.metadata_parquet_path == tmp_path / "exports" / "app_metadata.parquet"

    no_export_client = ScenarioClient(
        {
            "2026-06": [_record("app-3", "2026-06")],
            "2026-07": [_record("app-4", "2026-07")],
        }
    )
    no_export = backfill_months(
        _request(tmp_path, "2026-06", "2026-07", refresh_existing=True, skip_export=True),
        _config(),
        current_utc=NOW,
        client=no_export_client,
        metadata_sleep=lambda _: None,
        market_exporter=count_market_export,
        metadata_exporter=count_metadata_export,
    )
    assert no_export.market_parquet_path is None
    assert no_export.metadata_parquet_path is None
    assert export_calls == {"market": 1, "metadata": 1}


def test_export_failure_keeps_duckdb_rows_and_all_skipped_months_can_export_without_token(
    tmp_path: Path,
) -> None:
    _seed_months(tmp_path, {"2026-06": ("app-1",), "2026-07": ("app-2",)})

    def fail_metadata_export(repository: object, path: Path) -> None:
        raise ParquetExportError("app_metadata", str(path))

    with pytest.raises(ParquetExportError):
        backfill_months(
            _request(tmp_path, "2026-06", "2026-07"),
            _config(),
            current_utc=NOW,
            client_factory=lambda: pytest.fail("no client should be needed"),
            metadata_exporter=fail_metadata_export,
        )
    assert _stored_months(tmp_path / "data" / "history.duckdb", ("2026-06", "2026-07")) == {
        "2026-06": 1,
        "2026-07": 1,
    }

    exported = backfill_months(
        _request(tmp_path, "2026-06", "2026-07"),
        AppConfig(),
        current_utc=NOW,
    )
    assert exported.collected_month_count == 0
    assert exported.skipped_existing_month_count == 2
    assert exported.market_parquet_path is not None
    assert exported.metadata_parquet_path is not None
    assert exported.market_parquet_path.exists()
    assert exported.metadata_parquet_path.exists()
