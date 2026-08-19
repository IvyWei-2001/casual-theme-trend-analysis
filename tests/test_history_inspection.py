"""Synthetic coverage for the HIST-002 read-only history inspection."""

from __future__ import annotations

import calendar
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest

from src.config import AppConfig
from src.storage import AppMetadataRow, DuckDBRepository, MarketSnapshotRow
from src.storage import schema as schema_module
from src.workflows.history_inspection import (
    HistoryInspectionRequest,
    format_history_inspection_plan,
    inspect_history,
)

AS_OF = datetime(2026, 8, 12, tzinfo=UTC)


def _row(month: str, rank: int = 1) -> MarketSnapshotRow:
    year, month_number = (int(part) for part in month.split("-"))
    period_start = date(year, month_number, 1)
    period_end = date(year, month_number, calendar.monthrange(year, month_number)[1])
    return MarketSnapshotRow(
        scope_name="casual_puzzle_tabletop",
        cadence="monthly",
        period_start=period_start,
        period_end=period_end,
        rank_position=rank,
        source_app_id=f"synthetic-source-{month}-{rank}",
        unified_app_id=f"synthetic-unified-{month}-{rank}",
        scope_country="WW",
        device_type="total",
        category=7012,
        data_model="DM_2025_Q2",
        source_date=AS_OF,
        source_country=None,
        current_units_value=None,
        units_absolute=0.0,
        comparison_units_value=None,
        units_delta=None,
        units_transformed_delta=None,
        current_revenue_value=None,
        revenue_absolute=None,
        comparison_revenue_value=None,
        revenue_delta=None,
        revenue_transformed_delta=None,
        absolute=None,
        delta=None,
        transformed_delta=None,
        game_theme="",
        game_genre="Puzzle",
        game_subgenre="N/A",
        game_product_model="Unknown",
        game_art_style=None,
        game_setting=None,
        earliest_release_date=None,
        release_date_ww=None,
        publisher_country=None,
        most_popular_country_by_revenue=None,
        is_unified_source_value=None,
        collected_at=AS_OF,
    )


def _repository(tmp_path: Path) -> DuckDBRepository:
    repository = DuckDBRepository(tmp_path / "history.duckdb")
    repository.open()
    repository.initialize_schema()
    return repository


def _request(path: Path) -> HistoryInspectionRequest:
    return HistoryInspectionRequest(start_month="2023-08", end_month="2026-07", database_path=path)


class _FakeHistoryRepository:
    """Aggregate-only repository double for invalid-shape inspection cases."""

    def __init__(
        self,
        rows_by_month: Mapping[str, Sequence[MarketSnapshotRow]],
        metadata: Mapping[str, AppMetadataRow] | None = None,
    ) -> None:
        self.rows_by_month = rows_by_month
        self.metadata = {} if metadata is None else metadata

    def open_read_only(self) -> object:
        return object()

    def verify_read_only_schema(self) -> None:
        return None

    def close(self) -> None:
        return None

    def get_market_snapshot_period(self, key: object) -> list[MarketSnapshotRow]:
        month = key.period_start.strftime("%Y-%m")  # type: ignore[attr-defined]
        return list(self.rows_by_month.get(month, ()))

    def get_app_metadata(self, unified_app_ids: Sequence[object]) -> Mapping[str, AppMetadataRow]:
        ids = {str(value).strip() for value in unified_app_ids}
        return {app_id: row for app_id, row in self.metadata.items() if app_id in ids}


def _inspect_fake(
    rows_by_month: Mapping[str, Sequence[MarketSnapshotRow]],
    *,
    start_month: str = "2026-07",
    end_month: str = "2026-07",
    config: AppConfig | None = None,
    metadata: Mapping[str, AppMetadataRow] | None = None,
):
    return inspect_history(
        HistoryInspectionRequest(
            start_month,
            end_month,
            database_path=Path("unused-history.duckdb"),
        ),
        AppConfig() if config is None else config,
        current_utc=AS_OF,
        repository=_FakeHistoryRepository(rows_by_month, metadata),  # type: ignore[arg-type]
    )


def test_plan_only_validates_exact_36_months_without_configuration_or_storage() -> None:
    summary = inspect_history(
        HistoryInspectionRequest("2023-08", "2026-07", plan_only=True),
        current_utc=AS_OF,
    )

    assert summary.expected_month_count == 36
    assert summary.expected_months[0] == "2023-08"
    assert summary.expected_months[-1] == "2026-07"
    assert "configuration=disabled" in format_history_inspection_plan(summary)
    assert "database=disabled" in format_history_inspection_plan(summary)


def test_missing_database_is_not_created_by_read_only_inspection(tmp_path: Path) -> None:
    database_path = tmp_path / "missing" / "history.duckdb"

    with pytest.raises(FileNotFoundError):
        inspect_history(_request(database_path), AppConfig(), current_utc=AS_OF)

    assert not database_path.exists()
    assert not database_path.parent.exists()


def test_schema_v4_is_inspectable_read_only_without_model_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "version-four-history.duckdb"
    writable = DuckDBRepository(database_path)
    writable.open()
    writable.initialize_schema()
    writable.replace_market_snapshot_period([_row("2026-07")])
    connection = writable.open()
    for table_name in (
        schema_module.THEME_HORIZON_METRICS_TABLE,
        schema_module.THEME_MODEL_SUMMARIES_TABLE,
        schema_module.THEME_SEASONALITY_PROFILES_TABLE,
        schema_module.THEME_LAUNCH_WINDOW_OUTCOMES_TABLE,
        schema_module.THEME_BACKTEST_FEATURE_METRICS_TABLE,
        schema_module.THEME_BACKTEST_SEGMENT_METRICS_TABLE,
        schema_module.APP_MONETIZATION_PROFILES_TABLE,
        schema_module.THEME_MONETIZATION_OBSERVABILITY_METRICS_TABLE,
    ):
        connection.execute(f"DROP TABLE {table_name}")
    connection.execute("DELETE FROM schema_migrations WHERE version IN (5, 6, 7, 8, 9)")
    assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (4,)
    writable.close()

    summary = inspect_history(
        HistoryInspectionRequest("2026-07", "2026-07", database_path=database_path),
        AppConfig(),
        current_utc=AS_OF,
    )

    assert summary.present_month_count == 1
    assert summary.structurally_complete is True
    read_only_connection = duckdb.connect(str(database_path), read_only=True)
    try:
        table_names = {
            row[0]
            for row in read_only_connection.execute(
                "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main'"
            ).fetchall()
        }
        assert {
            schema_module.THEME_HORIZON_METRICS_TABLE,
            schema_module.THEME_MODEL_SUMMARIES_TABLE,
            schema_module.THEME_SEASONALITY_PROFILES_TABLE,
        }.isdisjoint(table_names)
        assert read_only_connection.execute(
            "SELECT max(version) FROM schema_migrations"
        ).fetchone() == (4,)
    finally:
        read_only_connection.close()


def test_complete_36_month_history_preserves_null_and_zero_evidence(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    for month in inspect_history(
        HistoryInspectionRequest("2023-08", "2026-07", plan_only=True), current_utc=AS_OF
    ).expected_months:
        repository.replace_market_snapshot_period([_row(month)])
    repository.close()

    summary = inspect_history(_request(tmp_path / "history.duckdb"), AppConfig(), current_utc=AS_OF)

    assert summary.structurally_complete is True
    assert summary.present_month_count == 36
    first = summary.month_results[0]
    assert first.downloads_coverage_count == 1
    assert first.downloads_zero_count == 1
    assert first.downloads_sum == 0.0
    assert first.revenue_usd_coverage_count == 0
    assert first.revenue_usd_sum is None
    assert first.game_theme_coverage_count == 1
    assert first.game_art_style_coverage_count == 0


@pytest.mark.parametrize(
    ("genre", "issue_count"),
    [
        ("Puzzle", 0),
        ("puzzle", 0),
        (" Puzzle ", 0),
        ("Tabletop", 0),
        ("TABLETOP", 0),
        ("Strategy", 1),
        (None, 1),
    ],
)
def test_game_genre_validation_matches_production_normalization(
    genre: str | None, issue_count: int
) -> None:
    row = replace(_row("2026-07"), game_genre=genre)

    summary = _inspect_fake({"2026-07": [row]})

    assert summary.month_results[0].structural_issue_count == issue_count
    assert summary.month_results[0].game_genre_coverage_count == (1 if genre is not None else 0)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("scope_country", "US"),
        ("device_type", "phone"),
        ("category", 7013),
        ("data_model", "DM_2024_Q4"),
    ],
)
def test_wrong_configured_provenance_is_structurally_invalid(
    field_name: str, value: object
) -> None:
    row = replace(_row("2026-07"), **{field_name: value})

    summary = _inspect_fake({"2026-07": [row]})

    result = summary.month_results[0]
    assert result.provenance_mismatch_count == 1
    assert result.structural_issue_count >= 1
    assert summary.structurally_complete is False


def test_correct_configured_provenance_is_compatible() -> None:
    summary = _inspect_fake({"2026-07": [_row("2026-07")]})

    assert summary.expected_provenance == ("WW", "total", 7012, "DM_2025_Q2")
    assert summary.month_results[0].provenance_mismatch_count == 0
    assert summary.structurally_complete is True


def test_one_wrong_month_breaks_range_provenance_completeness() -> None:
    months = ("2026-06", "2026-07")
    rows_by_month = {
        "2026-06": [_row("2026-06")],
        "2026-07": [replace(_row("2026-07"), scope_country="US")],
    }

    summary = _inspect_fake(
        rows_by_month,
        start_month=months[0],
        end_month=months[1],
    )

    assert summary.provenance_variant_count == 2
    assert summary.month_results[1].provenance_mismatch_count == 1
    assert summary.structurally_complete is False


def test_all_months_using_one_identical_wrong_provenance_still_fail() -> None:
    rows_by_month = {
        month: [replace(_row(month), scope_country="US")] for month in ("2026-06", "2026-07")
    }

    summary = _inspect_fake(
        rows_by_month,
        start_month="2026-06",
        end_month="2026-07",
    )

    assert summary.provenance_variant_count == 1
    assert summary.structural_issue_count == 2
    assert summary.structurally_complete is False


def test_mixed_within_month_provenance_is_reported() -> None:
    rows = [_row("2026-07", rank=1), replace(_row("2026-07", rank=2), category=7013)]

    result = _inspect_fake({"2026-07": rows}).month_results[0]

    assert result.provenance_variant_count == 2
    assert result.provenance_mismatch_count == 1
    assert result.structural_issue_count >= 1


def test_range_inventory_reports_chronological_missing_months() -> None:
    rows_by_month = {
        "2026-01": [_row("2026-01")],
        "2026-04": [_row("2026-04")],
    }

    summary = _inspect_fake(
        rows_by_month,
        start_month="2026-01",
        end_month="2026-04",
    )

    assert summary.missing_months == ("2026-02", "2026-03")
    assert summary.present_month_count == 2
    assert summary.missing_month_count == 2


def test_fewer_than_configured_top_n_is_valid_and_over_cap_is_invalid() -> None:
    valid = _inspect_fake({"2026-07": [_row("2026-07")]})
    capped_config = AppConfig(sensor_tower_api_limit=2, sensor_tower_final_top_n=1)
    over_cap = _inspect_fake(
        {"2026-07": [_row("2026-07", 1), _row("2026-07", 2)]},
        config=capped_config,
    )

    assert valid.month_results[0].snapshot_count == 1
    assert valid.month_results[0].structural_issue_count == 0
    assert over_cap.month_results[0].exceeds_configured_cap is True
    assert over_cap.month_results[0].structural_issue_count == 1


@pytest.mark.parametrize(
    "rows",
    [
        [_row("2026-07", 1), _row("2026-07", 3)],
        [replace(_row("2026-07", 1), rank_position=1), _row("2026-07", 1)],
        [
            _row("2026-07", 1),
            replace(
                _row("2026-07", 2),
                unified_app_id="synthetic-unified-2026-07-1",
            ),
        ],
    ],
)
def test_rank_and_identifier_integrity_checks(rows: list[MarketSnapshotRow]) -> None:
    result = _inspect_fake({"2026-07": rows}).month_results[0]

    assert result.structural_issue_count >= 1


@pytest.mark.parametrize(
    "row_factory",
    [
        lambda row: replace(row, scope_name="other-scope"),
        lambda row: replace(row, cadence="weekly"),
        lambda row: replace(
            row,
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
        ),
    ],
)
def test_period_identity_scope_and_cadence_checks(row_factory: object) -> None:
    row = row_factory(_row("2026-07"))  # type: ignore[operator]

    result = _inspect_fake({"2026-07": [row]}).month_results[0]

    assert result.structural_issue_count >= 1


def test_coverage_counts_and_ratios_preserve_null_zero_and_source_literals() -> None:
    row_with_values = replace(
        _row("2026-07"),
        units_absolute=0.0,
        revenue_absolute=0.0,
        game_theme="",
        game_genre="Puzzle",
        game_subgenre="N/A",
        game_product_model="Unknown",
        game_art_style="Watercolor",
        game_setting="Unknown",
        earliest_release_date=date(2024, 1, 1),
        release_date_ww=date(2024, 2, 1),
    )
    row_with_nulls = replace(
        _row("2026-07", rank=2),
        units_absolute=None,
        revenue_absolute=None,
        game_theme=None,
        game_genre=None,
        game_subgenre=None,
        game_product_model=None,
        game_art_style=None,
        game_setting=None,
        earliest_release_date=None,
        release_date_ww=None,
    )
    metadata = {
        row_with_values.unified_app_id: AppMetadataRow(
            unified_app_id=row_with_values.unified_app_id,
            name="Synthetic App",
            publisher_display_name="Synthetic Publisher",
            publisher_resolution_source="publisher_name",
            android_app_id=None,
            ios_app_id=None,
            fetched_at=AS_OF,
        )
    }

    result = _inspect_fake(
        {"2026-07": [row_with_values, row_with_nulls]}, metadata=metadata
    ).month_results[0]

    assert result.downloads_coverage_count == 1
    assert result.downloads_coverage_ratio == 0.5
    assert result.downloads_null_count == 1
    assert result.downloads_zero_count == 1
    assert result.downloads_sum == 0.0
    assert result.revenue_usd_coverage_count == 1
    assert result.revenue_usd_coverage_ratio == 0.5
    assert result.revenue_usd_null_count == 1
    assert result.revenue_usd_zero_count == 1
    assert result.revenue_usd_sum == 0.0
    assert result.game_theme_coverage_count == 1
    assert result.game_genre_coverage_count == 1
    assert result.game_subgenre_coverage_count == 1
    assert result.game_product_model_coverage_count == 1
    assert result.game_art_style_coverage_count == 1
    assert result.game_setting_coverage_count == 1
    assert result.metadata_coverage_count == 1
    assert result.metadata_coverage_ratio == 0.5
    assert result.name_coverage_count == 1
    assert result.publisher_coverage_count == 1
    assert result.earliest_release_date_coverage_count == 1
    assert result.release_date_ww_coverage_count == 1


@pytest.mark.parametrize(
    "replacement",
    [
        lambda row: replace(row, units_absolute=-1.0),
        lambda row: replace(row, revenue_absolute=-1.0),
        lambda row: replace(row, game_genre="Strategy"),
        lambda row: replace(row, most_popular_country_by_revenue="China"),
    ],
)
def test_structural_quality_detects_invalid_stored_rows(
    tmp_path: Path, replacement: object
) -> None:
    row = replacement(_row("2026-07"))  # type: ignore[operator]
    # Database constraints intentionally reject several invalid shapes; inject
    # a fake read-only repository for the aggregate quality boundary instead.

    class FakeRepository:
        def open_read_only(self) -> object:
            return object()

        def verify_read_only_schema(self) -> None:
            return None

        def close(self) -> None:
            return None

        def get_market_snapshot_period(self, key: object) -> list[MarketSnapshotRow]:
            return [row] if key.period_start.month == 7 else []  # type: ignore[attr-defined]

        def get_app_metadata(self, _ids: object) -> dict[str, object]:
            return {}

    summary = inspect_history(
        HistoryInspectionRequest("2026-07", "2026-07", database_path=tmp_path / "unused.duckdb"),
        AppConfig(),
        current_utc=AS_OF,
        repository=FakeRepository(),  # type: ignore[arg-type]
    )
    assert summary.month_results[0].structural_issue_count == 1
