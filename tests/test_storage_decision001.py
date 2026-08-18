"""Focused synthetic DECISION-001 schema, storage, and export tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest
from test_analysis_decision_v1 import (
    SCOPE,
    TARGET_MONTH,
    _category_decision,
    _decision,
    _period_end,
)

from src.analysis.decision_models import ThemeDecisionResult
from src.storage import DuckDBRepository, SnapshotPeriodKey
from src.storage import schema as schema_module
from src.storage.errors import (
    ParquetExportError,
    StorageValidationError,
    UnsupportedSchemaVersionError,
)

CALCULATED_AT = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def _key(month_start: date = TARGET_MONTH) -> SnapshotPeriodKey:
    return SnapshotPeriodKey(SCOPE, "monthly", month_start, _period_end(month_start))


def _repository(tmp_path: Path) -> DuckDBRepository:
    repository = DuckDBRepository(tmp_path / "decision.duckdb")
    repository.open()
    repository.initialize_schema()
    return repository


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
        (8, schema_module._apply_version_eight),
    ):
        if current_version > version:
            break
        apply_version(connection)
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, CURRENT_TIMESTAMP)",
            [current_version],
        )
    connection.close()


def _store(repository: DuckDBRepository, result: ThemeDecisionResult) -> None:
    repository.replace_theme_decision_result(result, target_period=_key())


def test_fresh_schema_records_versions_one_through_nine_and_exact_tables(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    connection = repository._connection
    assert connection is not None
    assert connection.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall() == [(index,) for index in range(1, 10)]
    expected = {
        schema_module.THEME_DECISION_SUMMARIES_TABLE: (
            schema_module.THEME_DECISION_SUMMARIES_COLUMNS
        ),
        schema_module.THEME_LAUNCH_WINDOW_ASSESSMENTS_TABLE: (
            schema_module.THEME_LAUNCH_WINDOW_ASSESSMENTS_COLUMNS
        ),
        schema_module.THEME_DECISION_RISKS_TABLE: schema_module.THEME_DECISION_RISKS_COLUMNS,
        schema_module.THEME_CATEGORY_FIT_ASSESSMENTS_TABLE: (
            schema_module.THEME_CATEGORY_FIT_ASSESSMENTS_COLUMNS
        ),
        schema_module.THEME_MIGRATION_HYPOTHESES_TABLE: (
            schema_module.THEME_MIGRATION_HYPOTHESES_COLUMNS
        ),
    }
    for table_name, columns in expected.items():
        assert [row[1] for row in connection.execute(
            f"PRAGMA table_info('{table_name}')"
        ).fetchall()] == list(columns)
    repository.close()


def test_writable_v8_migrates_without_changing_existing_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "v8.duckdb"
    _create_schema_at_version(database_path, 8)
    connection = duckdb.connect(str(database_path))
    connection.execute(
        "INSERT INTO monthly_market_totals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            SCOPE,
            "monthly",
            date(2026, 7, 1),
            date(2026, 7, 31),
            1,
            1,
            0,
            0,
            1,
            2.0,
            1,
            3.0,
            CALCULATED_AT,
        ],
    )
    connection.close()

    repository = DuckDBRepository(database_path)
    repository.open()
    repository.initialize_schema()
    assert repository._connection is not None
    assert repository._connection.execute(
        "SELECT max(version) FROM schema_migrations"
    ).fetchone() == (9,)
    assert repository._connection.execute(
        "SELECT snapshot_count, units_absolute_sum FROM monthly_market_totals"
    ).fetchall() == [(1, 2.0)]
    assert repository._connection.execute(
        "SELECT count(*) FROM theme_decision_summaries"
    ).fetchone() == (0,)
    repository.close()


def test_read_only_v8_is_not_migrated_and_v9_verifies(tmp_path: Path) -> None:
    v8_path = tmp_path / "v8-read-only.duckdb"
    _create_schema_at_version(v8_path, 8)
    v8_repository = DuckDBRepository(v8_path)
    connection = v8_repository.open_read_only()
    v8_repository.verify_read_only_schema()
    assert connection.execute("SELECT max(version) FROM schema_migrations").fetchone() == (8,)
    assert connection.execute(
        "SELECT count(*) FROM duckdb_tables() "
        "WHERE table_name = 'theme_decision_summaries'"
    ).fetchone() == (0,)
    v8_repository.close()

    v9_repository = _repository(tmp_path / "v9")
    v9_repository.close()
    read_only = DuckDBRepository(tmp_path / "v9" / "decision.duckdb")
    read_only.open_read_only()
    read_only.verify_read_only_schema()
    read_only.close()


def test_unsupported_future_schema_fails_without_creating_v9_tables(tmp_path: Path) -> None:
    path = tmp_path / "future.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute(schema_module._CREATE_SCHEMA_MIGRATIONS_SQL)
    connection.execute(
        "INSERT INTO schema_migrations VALUES (?, CURRENT_TIMESTAMP)",
        [99],
    )
    connection.close()
    repository = DuckDBRepository(path)
    repository.open()
    with pytest.raises(UnsupportedSchemaVersionError):
        repository.initialize_schema()
    assert repository._connection is not None
    assert repository._connection.execute(
        "SELECT count(*) FROM duckdb_tables() "
        "WHERE table_name = 'theme_decision_summaries'"
    ).fetchone() == (0,)
    repository.close()


def test_v8_to_v9_migration_rolls_back_on_injected_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "rollback.duckdb"
    _create_schema_at_version(path, 8)
    original = schema_module._apply_version_nine

    def fail_after_first_table(connection: duckdb.DuckDBPyConnection) -> None:
        connection.execute(schema_module._V9_TABLE_DEFINITIONS[0][1])
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(schema_module, "_apply_version_nine", fail_after_first_table)
    repository = DuckDBRepository(path)
    repository.open()
    with pytest.raises(RuntimeError, match="injected"):
        repository.initialize_schema()
    assert repository._connection is not None
    assert repository._connection.execute(
        "SELECT max(version) FROM schema_migrations"
    ).fetchone() == (8,)
    assert repository._connection.execute(
        "SELECT count(*) FROM duckdb_tables() "
        "WHERE table_name LIKE 'theme_decision_%'"
    ).fetchone() == (0,)
    repository.close()
    monkeypatch.setattr(schema_module, "_apply_version_nine", original)


def test_decision_result_round_trips_all_five_output_sets_and_filters(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    result = _category_decision()
    _store(repository, result)
    assert repository.get_theme_decision_summaries(game_theme="Theme") == list(
        result.decision_summaries
    )
    assert repository.get_theme_launch_window_assessments(horizon_months=2) == [
        row for row in result.launch_window_assessments if row.horizon_months == 2
    ]
    assert repository.get_theme_decision_risks(risk_code="migration_not_validated") == [
        row for row in result.decision_risks if row.risk_code.value == "migration_not_validated"
    ]
    assert repository.get_theme_category_fit_assessments(game_subgenre="Observed") == [
        row for row in result.category_fit_assessments if row.game_subgenre == "Observed"
    ]
    assert repository.get_theme_migration_hypotheses(
        validated_source_game_subgenre="Validated",
        target_observed_game_subgenre="Observed",
    ) == list(result.migration_hypotheses)
    repository.close()


def test_literal_labels_nulls_and_observed_zero_are_preserved(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    result = _category_decision()
    labels = ("", "Unknown")
    fits = tuple(
        replace(row, game_subgenre=label)
        for row, label in zip(result.category_fit_assessments, labels, strict=True)
    )
    summaries = (
        replace(
            result.decision_summaries[0],
            market_size_product_share_percentile=None,
            market_size_downloads_share_percentile=0.0,
        ),
    )
    result = ThemeDecisionResult(
        summaries,
        result.launch_window_assessments,
        result.decision_risks,
        fits,
        (),
    )
    _store(repository, result)
    stored_summary = repository.get_theme_decision_summaries()[0]
    assert stored_summary.market_size_product_share_percentile is None
    assert stored_summary.market_size_downloads_share_percentile == 0.0
    assert [row.game_subgenre for row in repository.get_theme_category_fit_assessments()] == [
        "",
        "Unknown",
    ]
    repository.close()


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("policy", "DECISION001_V1"),
        ("period", "period_end"),
        ("timestamp", "one calculation timestamp"),
        ("horizon", "horizon_months"),
        ("orphan", "summary population"),
    ),
)
def test_invalid_decision_payloads_are_rejected_before_write(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    repository = _repository(tmp_path)
    original = _decision(("Theme",))
    changed = original
    if mutation == "policy":
        object.__setattr__(changed.decision_summaries[0], "decision_policy_version", "BAD")
    elif mutation == "period":
        object.__setattr__(changed.decision_summaries[0], "period_start", date(2026, 6, 1))
    elif mutation == "timestamp":
        object.__setattr__(
            changed.launch_window_assessments[0],
            "calculated_at",
            datetime(2026, 8, 19, tzinfo=UTC),
        )
    elif mutation == "horizon":
        object.__setattr__(changed.launch_window_assessments[0], "horizon_months", 4)
    elif mutation == "orphan":
        object.__setattr__(changed.launch_window_assessments[0], "game_theme", "orphan")
    with pytest.raises(StorageValidationError, match=message):
        _store(repository, changed)
    assert repository._connection is not None
    assert repository._connection.execute(
        "SELECT count(*) FROM theme_decision_summaries"
    ).fetchone() == (0,)
    repository.close()


def test_duplicate_risk_code_is_rejected_even_when_source_metric_differs(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    result = _decision(("Theme",))
    duplicate = replace(
        result.decision_risks[0],
        source_metric_name="different_metric",
    )
    changed = ThemeDecisionResult(
        result.decision_summaries,
        result.launch_window_assessments,
        (*result.decision_risks, duplicate),
        result.category_fit_assessments,
        result.migration_hypotheses,
    )
    with pytest.raises(StorageValidationError, match="duplicate identities"):
        _store(repository, changed)
    repository.close()


def test_atomic_replacement_removes_stale_children_and_is_idempotent(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    rich = _category_decision()
    _store(repository, rich)
    reduced = ThemeDecisionResult(
        rich.decision_summaries,
        rich.launch_window_assessments,
        (),
        (),
        (),
    )
    _store(repository, reduced)
    assert repository.get_theme_decision_risks() == []
    assert repository.get_theme_category_fit_assessments() == []
    assert repository.get_theme_migration_hypotheses() == []
    _store(repository, reduced)
    assert repository.get_theme_decision_summaries() == list(reduced.decision_summaries)
    repository.close()


def test_insert_failure_rolls_back_all_five_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)
    first = _decision(("Theme",))
    _store(repository, first)
    second = _decision(("Theme", "Other"))
    connection = repository._connection
    assert connection is not None
    def fail_risk_parameter(*args: object, **kwargs: object) -> object:
        raise RuntimeError("injected insert failure")

    monkeypatch.setattr(
        "src.storage.repository._theme_decision_risk_parameters",
        fail_risk_parameter,
    )
    with pytest.raises(StorageValidationError, match="replacement failed"):
        _store(repository, second)
    assert repository.get_theme_decision_summaries() == list(first.decision_summaries)
    assert repository.get_theme_launch_window_assessments() == list(first.launch_window_assessments)
    assert repository.get_theme_decision_risks() == list(first.decision_risks)
    repository.close()


def test_precommit_readback_mismatch_rolls_back_all_five_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)
    first = _decision(("Theme",))
    _store(repository, first)
    second = _decision(("Theme", "Other"))

    def fail_readback(*args: object, **kwargs: object) -> None:
        raise StorageValidationError("injected readback mismatch")

    monkeypatch.setattr("src.storage.repository._verify_theme_decision_readback", fail_readback)
    with pytest.raises(StorageValidationError, match="readback mismatch"):
        _store(repository, second)
    assert repository.get_theme_decision_summaries() == list(first.decision_summaries)
    assert repository.get_theme_migration_hypotheses() == list(first.migration_hypotheses)
    repository.close()


def test_parquet_exports_have_exact_columns_zstd_order_and_deterministic_content(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    _store(repository, _category_decision())
    exports = (
        ("theme_decision_summaries", schema_module.THEME_DECISION_SUMMARIES_COLUMNS),
        (
            "theme_launch_window_assessments",
            schema_module.THEME_LAUNCH_WINDOW_ASSESSMENTS_COLUMNS,
        ),
        ("theme_decision_risks", schema_module.THEME_DECISION_RISKS_COLUMNS),
        (
            "theme_category_fit_assessments",
            schema_module.THEME_CATEGORY_FIT_ASSESSMENTS_COLUMNS,
        ),
        ("theme_migration_hypotheses", schema_module.THEME_MIGRATION_HYPOTHESES_COLUMNS),
    )
    paths: list[Path] = []
    for table_name, columns in exports:
        method = getattr(repository, f"export_{table_name}_to_parquet")
        path = tmp_path / "exports" / f"{table_name}.parquet"
        method(path)
        paths.append(path)
        reader = duckdb.connect()
        assert [row[0] for row in reader.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
        ).fetchall()] == list(columns)
        assert reader.execute(
            "SELECT compression FROM parquet_metadata(?) LIMIT 1", [str(path)]
        ).fetchone() == ("ZSTD",)
        reader.close()
    first_bytes = paths[0].read_bytes()
    repository.export_theme_decision_summaries_to_parquet(paths[0])
    assert paths[0].read_bytes() == first_bytes
    repository.close()


def test_empty_risk_and_migration_exports_keep_full_schema(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    result = _decision(("Theme",))
    _store(repository, ThemeDecisionResult(
        result.decision_summaries,
        result.launch_window_assessments,
        (),
        result.category_fit_assessments,
        (),
    ))
    for table_name, columns in (
        ("theme_decision_risks", schema_module.THEME_DECISION_RISKS_COLUMNS),
        ("theme_migration_hypotheses", schema_module.THEME_MIGRATION_HYPOTHESES_COLUMNS),
    ):
        path = tmp_path / f"{table_name}.parquet"
        getattr(repository, f"export_{table_name}_to_parquet")(path)
        reader = duckdb.connect()
        assert reader.execute(
            "SELECT count(*) FROM read_parquet(?)", [str(path)]
        ).fetchone() == (0,)
        assert [row[0] for row in reader.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
        ).fetchall()] == list(columns)
        reader.close()
    repository.close()


def test_export_failure_leaves_no_temporary_sibling_and_preserves_database(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    result = _decision(("Theme",))
    _store(repository, result)
    destination = tmp_path / "exports" / "existing-directory"
    destination.mkdir(parents=True)
    with pytest.raises(ParquetExportError):
        repository.export_theme_decision_summaries_to_parquet(destination)
    assert repository.get_theme_decision_summaries() == list(result.decision_summaries)
    assert list(destination.parent.glob(f".{destination.name}.*.parquet.tmp")) == []
    repository.close()
