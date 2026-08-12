"""Read-only completeness and quality inspection for stored monthly history."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from ..config import AppConfig
from ..storage import AppMetadataRow, DuckDBRepository, MarketSnapshotRow, SnapshotPeriodKey
from .errors import WorkflowError
from .models import BackfillMonthRange, MonthlyPeriod

HistoryMonthStatus = Literal["present", "missing"]


class HistoryRepository(Protocol):
    """Only the read operations used by historical inspection."""

    def open_read_only(self) -> object: ...

    def verify_read_only_schema(self) -> None: ...

    def close(self) -> None: ...

    def get_market_snapshot_period(self, key: SnapshotPeriodKey) -> list[MarketSnapshotRow]: ...

    def get_app_metadata(
        self, unified_app_ids: Sequence[object]
    ) -> Mapping[str, AppMetadataRow]: ...


@dataclass(frozen=True, slots=True)
class HistoryInspectionRequest:
    """Validated inputs for a credential-free plan or read-only inspection."""

    start_month: str
    end_month: str
    database_path: Path | None = None
    plan_only: bool = False
    require_complete: bool = False

    def __post_init__(self) -> None:
        for field_name in ("start_month", "end_month"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise WorkflowError(f"{field_name} must be a non-empty string")
        if self.database_path is None:
            if not self.plan_only:
                raise WorkflowError("database_path is required for read-only inspection")
        elif not isinstance(self.database_path, (Path, str)) or not str(self.database_path).strip():
            raise WorkflowError("database_path must be a non-empty path")
        else:
            object.__setattr__(self, "database_path", Path(self.database_path))
        for field_name in ("plan_only", "require_complete"):
            if not isinstance(getattr(self, field_name), bool):
                raise WorkflowError(f"{field_name} must be a boolean")


@dataclass(frozen=True, slots=True)
class HistoryMonthQuality:
    """Aggregate-only data quality evidence for one requested natural month."""

    month: str
    status: HistoryMonthStatus
    snapshot_count: int
    configured_final_top_n: int
    exceeds_configured_cap: bool
    unique_unified_app_count: int
    duplicate_unified_app_count: int
    unique_rank_count: int
    duplicate_rank_count: int
    ranks_are_contiguous: bool
    provenance_variant_count: int
    structural_issue_count: int
    downloads_coverage_count: int
    downloads_coverage_ratio: float | None
    downloads_null_count: int
    downloads_zero_count: int
    downloads_negative_count: int
    downloads_sum: float | None
    revenue_usd_coverage_count: int
    revenue_usd_coverage_ratio: float | None
    revenue_usd_null_count: int
    revenue_usd_zero_count: int
    revenue_usd_negative_count: int
    revenue_usd_sum: float | None
    game_theme_coverage_count: int
    game_theme_coverage_ratio: float | None
    game_genre_coverage_count: int
    game_genre_coverage_ratio: float | None
    game_subgenre_coverage_count: int
    game_subgenre_coverage_ratio: float | None
    game_product_model_coverage_count: int
    game_product_model_coverage_ratio: float | None
    game_art_style_coverage_count: int
    game_art_style_coverage_ratio: float | None
    game_setting_coverage_count: int
    game_setting_coverage_ratio: float | None
    metadata_coverage_count: int
    metadata_coverage_ratio: float | None
    name_coverage_count: int
    name_coverage_ratio: float | None
    publisher_coverage_count: int
    publisher_coverage_ratio: float | None
    earliest_release_date_coverage_count: int
    earliest_release_date_coverage_ratio: float | None
    release_date_ww_coverage_count: int
    release_date_ww_coverage_ratio: float | None


@dataclass(frozen=True, slots=True)
class HistoryInspectionSummary:
    """Typed immutable range-level aggregate inspection result."""

    mode: Literal["plan-only", "read-only"]
    scope_name: str | None
    start_month: str
    end_month: str
    expected_month_count: int
    expected_months: tuple[str, ...]
    present_month_count: int
    missing_month_count: int
    missing_months: tuple[str, ...]
    total_snapshot_count: int
    minimum_snapshot_count: int | None
    maximum_snapshot_count: int | None
    average_snapshot_count: float | None
    provenance_variant_count: int
    structural_issue_count: int
    structurally_complete: bool
    month_results: tuple[HistoryMonthQuality, ...]


def inspect_history(
    request: HistoryInspectionRequest,
    config: AppConfig | None = None,
    *,
    current_utc: datetime | date | None = None,
    utc_clock: Callable[[], datetime] | None = None,
    repository: HistoryRepository | None = None,
    repository_factory: Callable[[Path], HistoryRepository] | None = None,
) -> HistoryInspectionSummary:
    """Inspect stored history without constructing clients, writing, or exporting."""

    started_at = _resolve_current_utc(current_utc, utc_clock)
    month_range = BackfillMonthRange.parse(
        request.start_month, request.end_month, current_utc=started_at
    )
    if request.plan_only:
        return _plan_summary(month_range)
    if config is None:
        raise WorkflowError("config is required for read-only inspection")
    if request.database_path is None:
        raise WorkflowError("database_path is required for read-only inspection")
    if repository is not None and repository_factory is not None:
        raise WorkflowError("provide either repository or repository_factory, not both")

    active_repository = repository
    owns_repository = False
    try:
        if active_repository is None:
            factory = DuckDBRepository if repository_factory is None else repository_factory
            active_repository = factory(request.database_path)
            owns_repository = True
        active_repository.open_read_only()
        active_repository.verify_read_only_schema()
        selection = config.sensor_tower_selection_config
        inspected = tuple(
            _inspect_month(
                active_repository,
                period,
                selection.scope_name,
                selection.final_top_n,
                selection.allowed_genres,
                selection.exclude_china_revenue_market,
            )
            for period in month_range.periods
        )
        return _read_only_summary(
            month_range,
            selection.scope_name,
            tuple(item[0] for item in inspected),
            {value for _result, values in inspected for value in values},
        )
    finally:
        if owns_repository and active_repository is not None:
            active_repository.close()


def format_history_inspection_plan(summary: HistoryInspectionSummary) -> str:
    """Format the credential-free plan contract without local paths."""

    return "\n".join(
        (
            "Historical inspection plan:",
            "mode=plan-only",
            f"start_month={summary.start_month}",
            f"end_month={summary.end_month}",
            f"expected_month_count={summary.expected_month_count}",
            f"month_sequence={','.join(summary.expected_months)}",
            "configuration=disabled",
            "credentials=disabled",
            "network=disabled",
            "database=disabled",
            "file_writes=disabled",
        )
    )


def format_history_inspection_summary(summary: HistoryInspectionSummary) -> str:
    """Format sanitized deterministic quality evidence without raw row values."""

    if summary.mode == "plan-only":
        return format_history_inspection_plan(summary)
    lines = [
        "Historical data quality inspection:",
        "mode=read-only",
        f"scope_name={summary.scope_name}",
        f"start_month={summary.start_month}",
        f"end_month={summary.end_month}",
        f"expected_month_count={summary.expected_month_count}",
        f"present_month_count={summary.present_month_count}",
        f"missing_month_count={summary.missing_month_count}",
        f"missing_months={','.join(summary.missing_months)}",
        f"total_snapshot_count={summary.total_snapshot_count}",
        f"minimum_snapshot_count={_display(summary.minimum_snapshot_count)}",
        f"maximum_snapshot_count={_display(summary.maximum_snapshot_count)}",
        f"average_snapshot_count={_display(summary.average_snapshot_count)}",
        f"provenance_variant_count={summary.provenance_variant_count}",
        f"structural_issue_count={summary.structural_issue_count}",
        f"structurally_complete={str(summary.structurally_complete).lower()}",
        "database_mode=read-only",
        "network=disabled",
        "file_writes=disabled",
    ]
    lines.extend(_format_month(result) for result in summary.month_results)
    return "\n".join(lines)


def _inspect_month(
    repository: HistoryRepository,
    period: MonthlyPeriod,
    scope_name: str,
    final_top_n: int,
    allowed_genres: Sequence[str],
    exclude_china_revenue_market: bool,
) -> tuple[HistoryMonthQuality, set[tuple[str, str, int, str]]]:
    month = period.month
    key = SnapshotPeriodKey(
        scope_name=scope_name,
        cadence="monthly",
        period_start=period.period_start,
        period_end=period.period_end,
    )
    rows = repository.get_market_snapshot_period(key)
    if not rows:
        return _missing_month(month, final_top_n), set()
    metadata = repository.get_app_metadata([row.unified_app_id for row in rows])
    result = _present_month(
        month=month,
        rows=rows,
        metadata=metadata,
        key=key,
        final_top_n=final_top_n,
        allowed_genres=set(allowed_genres),
        exclude_china_revenue_market=exclude_china_revenue_market,
    )
    return result, {_provenance_tuple(row) for row in rows}


def _present_month(
    *,
    month: str,
    rows: Sequence[MarketSnapshotRow],
    metadata: Mapping[str, AppMetadataRow],
    key: SnapshotPeriodKey,
    final_top_n: int,
    allowed_genres: set[str],
    exclude_china_revenue_market: bool,
) -> HistoryMonthQuality:
    snapshot_count = len(rows)
    ids = [row.unified_app_id for row in rows]
    ranks = [row.rank_position for row in rows]
    provenance = {_provenance_tuple(row) for row in rows}
    downloads = _metric_quality(rows, "units_absolute")
    revenue = _metric_quality(rows, "revenue_absolute")
    issues = (
        snapshot_count == 0,
        snapshot_count > final_top_n,
        len(set(ids)) != snapshot_count,
        len(set(ranks)) != snapshot_count,
        set(ranks) != set(range(1, snapshot_count + 1)),
        len(provenance) != 1,
        any(row.scope_name != key.scope_name for row in rows),
        any(row.cadence != "monthly" for row in rows),
        any(
            row.period_start != key.period_start or row.period_end != key.period_end for row in rows
        ),
        downloads[3] > 0,
        revenue[3] > 0,
        any(row.game_genre not in allowed_genres for row in rows),
        exclude_china_revenue_market
        and any(row.most_popular_country_by_revenue == "China" for row in rows),
    )
    metadata_by_id = {app_id: metadata.get(app_id) for app_id in ids}
    values: dict[str, Any] = dict(
        month=month,
        status="present",
        snapshot_count=snapshot_count,
        configured_final_top_n=final_top_n,
        exceeds_configured_cap=snapshot_count > final_top_n,
        unique_unified_app_count=len(set(ids)),
        duplicate_unified_app_count=snapshot_count - len(set(ids)),
        unique_rank_count=len(set(ranks)),
        duplicate_rank_count=snapshot_count - len(set(ranks)),
        ranks_are_contiguous=set(ranks) == set(range(1, snapshot_count + 1)),
        provenance_variant_count=len(provenance),
        structural_issue_count=sum(issues),
        downloads_coverage_count=downloads[0],
        downloads_coverage_ratio=_ratio(downloads[0], snapshot_count),
        downloads_null_count=downloads[1],
        downloads_zero_count=downloads[2],
        downloads_negative_count=downloads[3],
        downloads_sum=downloads[4],
        revenue_usd_coverage_count=revenue[0],
        revenue_usd_coverage_ratio=_ratio(revenue[0], snapshot_count),
        revenue_usd_null_count=revenue[1],
        revenue_usd_zero_count=revenue[2],
        revenue_usd_negative_count=revenue[3],
        revenue_usd_sum=revenue[4],
    )
    values.update(_source_coverage(rows, snapshot_count))
    values.update(_metadata_coverage(metadata_by_id, snapshot_count))
    return HistoryMonthQuality(**cast(Any, values))


def _missing_month(month: str, final_top_n: int) -> HistoryMonthQuality:
    zeros: dict[str, int | float | None | bool] = {
        "snapshot_count": 0,
        "configured_final_top_n": final_top_n,
        "exceeds_configured_cap": False,
        "unique_unified_app_count": 0,
        "duplicate_unified_app_count": 0,
        "unique_rank_count": 0,
        "duplicate_rank_count": 0,
        "ranks_are_contiguous": False,
        "provenance_variant_count": 0,
        "structural_issue_count": 0,
    }
    for prefix in ("downloads", "revenue_usd"):
        zeros.update(
            {
                f"{prefix}_coverage_count": 0,
                f"{prefix}_coverage_ratio": None,
                f"{prefix}_null_count": 0,
                f"{prefix}_zero_count": 0,
                f"{prefix}_negative_count": 0,
                f"{prefix}_sum": None,
            }
        )
    for prefix in (
        "game_theme",
        "game_genre",
        "game_subgenre",
        "game_product_model",
        "game_art_style",
        "game_setting",
        "metadata",
        "name",
        "publisher",
        "earliest_release_date",
        "release_date_ww",
    ):
        zeros.update({f"{prefix}_coverage_count": 0, f"{prefix}_coverage_ratio": None})
    return HistoryMonthQuality(month=month, status="missing", **zeros)  # type: ignore[arg-type]


def _metric_quality(
    rows: Sequence[MarketSnapshotRow], attribute: str
) -> tuple[int, int, int, int, float | None]:
    values = [getattr(row, attribute) for row in rows]
    covered = [value for value in values if value is not None]
    return (
        len(covered),
        len(values) - len(covered),
        sum(value == 0 for value in covered),
        sum(value < 0 for value in covered),
        (float(sum(covered)) if covered else None),
    )


def _source_coverage(
    rows: Sequence[MarketSnapshotRow], total: int
) -> dict[str, int | float | None]:
    attributes = {
        "game_theme": "game_theme",
        "game_genre": "game_genre",
        "game_subgenre": "game_subgenre",
        "game_product_model": "game_product_model",
        "game_art_style": "game_art_style",
        "game_setting": "game_setting",
        "earliest_release_date": "earliest_release_date",
        "release_date_ww": "release_date_ww",
    }
    result: dict[str, int | float | None] = {}
    for prefix, attribute in attributes.items():
        count = sum(getattr(row, attribute) is not None for row in rows)
        result[f"{prefix}_coverage_count"] = count
        result[f"{prefix}_coverage_ratio"] = _ratio(count, total)
    return result


def _metadata_coverage(
    metadata: Mapping[str, AppMetadataRow | None], total: int
) -> dict[str, int | float | None]:
    counts = {
        "metadata": sum(value is not None for value in metadata.values()),
        "name": sum(value is not None and value.name is not None for value in metadata.values()),
        "publisher": sum(
            value is not None and value.publisher_display_name is not None
            for value in metadata.values()
        ),
    }
    result: dict[str, int | float | None] = {}
    for prefix, count in counts.items():
        result[f"{prefix}_coverage_count"] = count
        result[f"{prefix}_coverage_ratio"] = _ratio(count, total)
    return result


def _read_only_summary(
    month_range: BackfillMonthRange,
    scope_name: str,
    results: tuple[HistoryMonthQuality, ...],
    provenance: set[tuple[str, str, int, str]],
) -> HistoryInspectionSummary:
    return _summary_from_results(month_range, scope_name, results, len(provenance))


def _summary_from_results(
    month_range: BackfillMonthRange,
    scope_name: str,
    results: tuple[HistoryMonthQuality, ...],
    provenance_count: int,
) -> HistoryInspectionSummary:
    present = tuple(result for result in results if result.status == "present")
    missing = tuple(result.month for result in results if result.status == "missing")
    snapshots = [result.snapshot_count for result in present]
    structural_issues = sum(result.structural_issue_count for result in present)
    complete = not missing and structural_issues == 0 and provenance_count == 1
    return HistoryInspectionSummary(
        "read-only",
        scope_name,
        month_range.start_month,
        month_range.end_month,
        len(results),
        month_range.months,
        len(present),
        len(missing),
        missing,
        sum(snapshots),
        min(snapshots) if snapshots else None,
        max(snapshots) if snapshots else None,
        (sum(snapshots) / len(snapshots)) if snapshots else None,
        provenance_count,
        structural_issues,
        complete,
        results,
    )


def _plan_summary(month_range: BackfillMonthRange) -> HistoryInspectionSummary:
    return HistoryInspectionSummary(
        "plan-only",
        None,
        month_range.start_month,
        month_range.end_month,
        len(month_range.periods),
        month_range.months,
        0,
        0,
        (),
        0,
        None,
        None,
        None,
        0,
        0,
        False,
        (),
    )


def _provenance_tuple(row: MarketSnapshotRow) -> tuple[str, str, int, str]:
    return row.scope_country, row.device_type, row.category, row.data_model


def _ratio(count: int, total: int) -> float | None:
    return count / total if total else None


def _resolve_current_utc(
    current_utc: datetime | date | None, utc_clock: Callable[[], datetime] | None
) -> datetime | date:
    if current_utc is not None:
        return current_utc
    if utc_clock is None:
        raise WorkflowError("current UTC time must be supplied by the caller")
    value = utc_clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowError("workflow timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _display(value: object) -> str:
    return "" if value is None else str(value)


def _format_month(result: HistoryMonthQuality) -> str:
    if result.status == "missing":
        return f"month={result.month} status=missing"
    values = [f"month={result.month}", "status=present"]
    for field_name in HistoryMonthQuality.__dataclass_fields__:
        if field_name in {"month", "status"}:
            continue
        values.append(f"{field_name}={_display(getattr(result, field_name))}")
    return " ".join(values)
