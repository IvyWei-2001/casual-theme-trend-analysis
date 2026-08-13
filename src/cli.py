"""Command-line interface for the local application and collection workflow."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from .analysis.errors import AggregationError
from .config import DEFAULT_DATABASE_PATH, DEFAULT_EXPORT_DIRECTORY, AppConfig, load_config
from .feishu.errors import (
    FeishuConfigurationError,
    FeishuError,
    FeishuSchemaIntegrityError,
    FeishuSyncIntegrityError,
)
from .feishu.inspection import (
    format_feishu_inspection_plan,
    format_feishu_inspection_summary,
    format_feishu_record_inspection_plan,
    format_feishu_record_inspection_summary,
    inspect_feishu,
    inspect_feishu_records,
)
from .feishu.provisioning import (
    format_feishu_schema_plan,
    format_feishu_schema_plan_only,
    format_feishu_schema_provision_result,
    plan_feishu_schema,
    provision_feishu_schema,
)
from .logging_config import configure_logging
from .sensor_tower.errors import SensorTowerConfigurationError, SensorTowerError
from .storage.errors import StorageError
from .workflows import (
    AggregateThemesRequest,
    BackfillMonthsError,
    BackfillMonthsRequest,
    CollectMonthRequest,
    HistoryInspectionRequest,
    InvalidMonthError,
    ModelThemesError,
    ModelThemesRequest,
    ScoreThemesRequest,
    SyncFeishuTrendsRequest,
    WorkflowError,
    aggregate_themes,
    backfill_months,
    collect_month,
    format_aggregate_themes_summary,
    format_backfill_summary,
    format_collection_summary,
    format_feishu_trend_sync_plan_only,
    format_feishu_trend_sync_summary,
    format_history_inspection_plan,
    format_history_inspection_summary,
    format_model_themes_summary,
    format_score_themes_summary,
    inspect_history,
    model_themes,
    score_themes,
    sync_feishu_trends,
)

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the small command parser without loading configuration."""

    parser = argparse.ArgumentParser(
        prog="python -m src",
        description="Casual Theme Trend Analysis local workflows",
    )
    subparsers = parser.add_subparsers(dest="command")
    collect_parser = subparsers.add_parser(
        "collect-month",
        help="collect one completed natural calendar month",
    )
    collect_parser.add_argument(
        "--month",
        required=True,
        help="completed natural calendar month in YYYY-MM format",
    )
    collect_parser.add_argument(
        "--plan-only",
        action="store_true",
        help="validate and print the execution plan without network or database access",
    )
    collect_parser.add_argument(
        "--skip-export",
        action="store_true",
        help="store DuckDB rows but skip both Parquet exports",
    )
    backfill_parser = subparsers.add_parser(
        "backfill-months",
        help="run an inclusive, resumable range of completed calendar months",
    )
    backfill_parser.add_argument(
        "--start",
        required=True,
        help="oldest completed natural calendar month in YYYY-MM format",
    )
    backfill_parser.add_argument(
        "--end",
        required=True,
        help="newest completed natural calendar month in YYYY-MM format",
    )
    backfill_parser.add_argument(
        "--plan-only",
        action="store_true",
        help="validate and print the month plan without network or database access",
    )
    backfill_parser.add_argument(
        "--refresh-existing",
        action="store_true",
        help="recollect and atomically replace existing stored months",
    )
    backfill_parser.add_argument(
        "--skip-export",
        action="store_true",
        help="store DuckDB rows but skip the final Parquet exports",
    )
    history_parser = subparsers.add_parser(
        "inspect-history",
        help="inspect stored monthly history without network or writes",
    )
    history_parser.add_argument(
        "--start", required=True, help="oldest completed month in YYYY-MM format"
    )
    history_parser.add_argument(
        "--end", required=True, help="newest completed month in YYYY-MM format"
    )
    history_parser.add_argument(
        "--plan-only",
        action="store_true",
        help="validate the range without configuration or storage access",
    )
    history_parser.add_argument(
        "--require-complete",
        action="store_true",
        help="return exit code 4 unless history is structurally complete",
    )
    aggregate_parser = subparsers.add_parser(
        "aggregate-themes",
        help="aggregate stored monthly Game Theme rows without network access",
    )
    aggregate_parser.add_argument(
        "--start",
        required=True,
        help="oldest completed natural calendar month in YYYY-MM format",
    )
    aggregate_parser.add_argument(
        "--end",
        required=True,
        help="newest completed natural calendar month in YYYY-MM format",
    )
    aggregate_parser.add_argument(
        "--plan-only",
        action="store_true",
        help="validate and print the month plan without database or file access",
    )
    aggregate_parser.add_argument(
        "--skip-export",
        action="store_true",
        help="store derived DuckDB rows but skip both derived Parquet exports",
    )
    score_parser = subparsers.add_parser(
        "score-themes",
        help="calculate explainable monthly Game Theme trend scores without network access",
    )
    score_parser.add_argument(
        "--start",
        required=True,
        help="oldest completed natural calendar month in YYYY-MM format",
    )
    score_parser.add_argument(
        "--end",
        required=True,
        help="newest completed natural calendar month in YYYY-MM format",
    )
    score_parser.add_argument(
        "--plan-only",
        action="store_true",
        help="validate and print the score plan without database or file access",
    )
    score_parser.add_argument(
        "--skip-export",
        action="store_true",
        help="store trend rows but skip the trend Parquet export",
    )
    score_parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="positive number of latest-month actionable themes to display (default: 20)",
    )
    model_parser = subparsers.add_parser(
        "model-themes",
        help="calculate MODEL-002 horizon, lifecycle, and seasonality evidence",
    )
    model_parser.add_argument(
        "--start",
        required=True,
        help="oldest completed natural calendar month in YYYY-MM format",
    )
    model_parser.add_argument(
        "--end",
        required=True,
        help="newest completed natural calendar month in YYYY-MM format",
    )
    model_parser.add_argument(
        "--plan-only",
        action="store_true",
        help="validate and print the model plan without database or file access",
    )
    model_parser.add_argument(
        "--skip-export",
        action="store_true",
        help="store model rows but skip all four Parquet exports",
    )
    inspect_parser = subparsers.add_parser(
        "inspect-feishu",
        help="inspect configured Feishu Bitable field metadata without writes",
    )
    inspect_parser.add_argument(
        "--plan-only",
        action="store_true",
        help="validate and print the read-only plan without network or local storage access",
    )
    inspect_records_parser = subparsers.add_parser(
        "inspect-feishu-records",
        help="inspect configured Feishu Bitable records without writes",
    )
    inspect_records_parser.add_argument(
        "--plan-only",
        action="store_true",
        help="print the read-only record plan without configuration or network access",
    )
    provision_parser = subparsers.add_parser(
        "provision-feishu-schema",
        help="plan or provision the configured Feishu Bitable trend-score fields",
    )
    provision_mode = provision_parser.add_mutually_exclusive_group()
    provision_mode.add_argument(
        "--plan-only",
        action="store_true",
        help="validate and print the desired schema without network or local storage access",
    )
    provision_mode.add_argument(
        "--apply",
        action="store_true",
        help="create missing fields after a complete live compatibility check",
    )
    sync_parser = subparsers.add_parser(
        "sync-feishu-trends",
        help="plan or explicitly synchronize stored monthly trend scores to Feishu",
    )
    sync_mode = sync_parser.add_mutually_exclusive_group()
    sync_mode.add_argument(
        "--plan-only",
        action="store_true",
        help="print the credential-free synchronization contract",
    )
    sync_mode.add_argument(
        "--apply",
        action="store_true",
        help="apply idempotent batch record synchronization and verify it",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested local command and return a categorized exit code."""

    args = build_parser().parse_args(argv)
    if args.command == "provision-feishu-schema" and args.plan_only:
        try:
            print(format_feishu_schema_plan_only())
        except FeishuConfigurationError as error:
            _print_error(str(error))
            return 2
        return 0
    if args.command == "inspect-feishu-records" and args.plan_only:
        print(format_feishu_record_inspection_plan())
        return 0
    if args.command == "sync-feishu-trends" and args.plan_only:
        try:
            print(format_feishu_trend_sync_plan_only())
        except (FeishuConfigurationError, FeishuSyncIntegrityError) as error:
            _print_error(str(error))
            return 2
        return 0
    if args.command == "aggregate-themes" and args.plan_only:
        try:
            aggregate_plan_summary = aggregate_themes(
                AggregateThemesRequest(
                    start_month=args.start,
                    end_month=args.end,
                    database_path=Path(DEFAULT_DATABASE_PATH),
                    export_directory=Path(DEFAULT_EXPORT_DIRECTORY),
                    plan_only=True,
                ),
                AppConfig.model_construct(),
                current_utc=datetime.now(UTC),
            )
        except (InvalidMonthError, WorkflowError) as error:
            _print_error(str(error))
            return 2
        print(format_aggregate_themes_summary(aggregate_plan_summary))
        return 0
    if args.command == "model-themes" and args.plan_only:
        try:
            model_plan_summary = model_themes(
                ModelThemesRequest(
                    start_month=args.start,
                    end_month=args.end,
                    database_path=Path(DEFAULT_DATABASE_PATH),
                    export_directory=Path(DEFAULT_EXPORT_DIRECTORY),
                    plan_only=True,
                ),
                AppConfig.model_construct(),
                current_utc=datetime.now(UTC),
            )
        except (InvalidMonthError, WorkflowError) as error:
            _print_error(str(error))
            return 2
        print(format_model_themes_summary(model_plan_summary))
        return 0
    if args.command == "inspect-history" and args.plan_only:
        try:
            history_plan_summary = inspect_history(
                HistoryInspectionRequest(
                    start_month=args.start,
                    end_month=args.end,
                    plan_only=True,
                    require_complete=args.require_complete,
                ),
                current_utc=datetime.now(UTC),
            )
        except (InvalidMonthError, WorkflowError) as error:
            _print_error(str(error))
            return 2
        print(format_history_inspection_plan(history_plan_summary))
        return 0

    try:
        config = load_config()
        configure_logging(config.log_level)
    except (ValidationError, ValueError, OSError):
        _print_error("invalid local configuration")
        return 2
    except Exception:
        _print_error("invalid local configuration")
        return 2

    if args.command is None:
        LOGGER.info("bootstrap startup complete: %s", config.app_name)
        return 0

    if args.command == "inspect-feishu":
        if args.plan_only:
            print(format_feishu_inspection_plan(config))
            return 0
        try:
            inspection_result = inspect_feishu(config)
        except FeishuConfigurationError as error:
            _print_error(str(error))
            return 2
        except FeishuError as error:
            _print_error(str(error))
            return 3
        except OSError:
            _print_error("local Feishu inspection operation failed")
            return 4
        except Exception:
            _print_error("Feishu inspection failed")
            return 4

        print(format_feishu_inspection_summary(inspection_result))
        return 0

    if args.command == "inspect-feishu-records":
        try:
            record_inspection_result = inspect_feishu_records(config)
        except FeishuConfigurationError as error:
            _print_error(str(error))
            return 2
        except FeishuSchemaIntegrityError as error:
            _print_error(str(error))
            return 4
        except FeishuError as error:
            _print_error(str(error))
            return 3
        except OSError:
            _print_error("local Feishu record inspection operation failed")
            return 4
        except Exception:
            _print_error("Feishu record inspection failed")
            return 4

        print(format_feishu_record_inspection_summary(record_inspection_result))
        return 0

    if args.command == "provision-feishu-schema":
        try:
            if args.apply:
                provision_result = provision_feishu_schema(config)
                print(format_feishu_schema_provision_result(provision_result))
            else:
                schema_plan = plan_feishu_schema(config)
                print(format_feishu_schema_plan(schema_plan))
        except FeishuConfigurationError as error:
            _print_error(str(error))
            return 2
        except FeishuSchemaIntegrityError as error:
            _print_error(str(error))
            return 4
        except FeishuError as error:
            _print_error(str(error))
            return 3
        except OSError:
            _print_error("local Feishu schema operation failed")
            return 4
        except Exception:
            _print_error("Feishu schema provisioning failed")
            return 4
        return 0

    if args.command == "sync-feishu-trends":
        try:
            sync_request = SyncFeishuTrendsRequest(
                database_path=config.database_path,
                plan_only=args.plan_only,
                apply=args.apply,
            )
            sync_summary = sync_feishu_trends(sync_request, config)
        except FeishuConfigurationError as error:
            _print_error(str(error))
            return 2
        except FeishuSchemaIntegrityError as error:
            _print_error(str(error))
            return 4
        except FeishuSyncIntegrityError as error:
            _print_error(str(error))
            return 4
        except FeishuError as error:
            _print_error(str(error))
            return 3
        except StorageError as error:
            _print_error(str(error))
            return 4
        except WorkflowError as error:
            _print_error(str(error))
            return 2
        except OSError:
            _print_error("local Feishu trend synchronization operation failed")
            return 4
        except Exception:
            _print_error("Feishu trend synchronization failed")
            return 4

        print(format_feishu_trend_sync_summary(sync_summary))
        return 0

    if args.command == "collect-month":
        current_utc = datetime.now(UTC)
        request = CollectMonthRequest(
            month=args.month,
            database_path=config.database_path,
            export_directory=config.export_directory,
            plan_only=args.plan_only,
            skip_export=args.skip_export,
        )
        try:
            summary = collect_month(
                request,
                config,
                current_utc=current_utc,
            )
        except InvalidMonthError as error:
            _print_error(str(error))
            return 2
        except SensorTowerConfigurationError as error:
            _print_error(str(error))
            return 2
        except SensorTowerError as error:
            _print_error(str(error))
            return 3
        except StorageError as error:
            _print_error(str(error))
            return 4
        except WorkflowError as error:
            _print_error(str(error))
            return 3
        except OSError:
            _print_error("local storage operation failed")
            return 4
        except Exception:
            _print_error("collection failed")
            return 4

        print(format_collection_summary(summary))
        return 0

    if args.command == "backfill-months":
        current_utc = datetime.now(UTC)
        backfill_request = BackfillMonthsRequest(
            start_month=args.start,
            end_month=args.end,
            database_path=config.database_path,
            export_directory=config.export_directory,
            plan_only=args.plan_only,
            refresh_existing=args.refresh_existing,
            skip_export=args.skip_export,
        )
        try:
            backfill_summary = backfill_months(
                backfill_request,
                config,
                current_utc=current_utc,
            )
        except InvalidMonthError as error:
            _print_error(str(error))
            return 2
        except BackfillMonthsError as error:
            _print_error(str(error))
            return _backfill_failure_exit_code(error.failure_kind)
        except SensorTowerConfigurationError as error:
            _print_error(str(error))
            return 2
        except SensorTowerError as error:
            _print_error(str(error))
            return 3
        except StorageError as error:
            _print_error(str(error))
            return 4
        except WorkflowError as error:
            _print_error(str(error))
            return 3
        except OSError:
            _print_error("local storage operation failed")
            return 4
        except Exception:
            _print_error("backfill failed")
            return 4

        print(format_backfill_summary(backfill_summary))
        return 0

    if args.command == "inspect-history":
        try:
            history_summary = inspect_history(
                HistoryInspectionRequest(
                    start_month=args.start,
                    end_month=args.end,
                    database_path=config.database_path,
                    require_complete=args.require_complete,
                ),
                config,
                current_utc=datetime.now(UTC),
            )
        except InvalidMonthError as error:
            _print_error(str(error))
            return 2
        except StorageError:
            _print_error("local read-only history inspection failed")
            return 4
        except WorkflowError:
            _print_error("invalid history inspection request")
            return 2
        except OSError:
            _print_error("local read-only history inspection failed")
            return 4
        except Exception:
            _print_error("history inspection failed")
            return 4
        print(format_history_inspection_summary(history_summary))
        return 0 if not args.require_complete or history_summary.structurally_complete else 4

    if args.command == "aggregate-themes":
        current_utc = datetime.now(UTC)
        aggregate_request = AggregateThemesRequest(
            start_month=args.start,
            end_month=args.end,
            database_path=config.database_path,
            export_directory=config.export_directory,
            plan_only=args.plan_only,
            skip_export=args.skip_export,
        )
        try:
            aggregate_summary = aggregate_themes(
                aggregate_request,
                config,
                current_utc=current_utc,
            )
        except InvalidMonthError as error:
            _print_error(str(error))
            return 2
        except AggregationError as error:
            _print_error(str(error))
            return 3
        except StorageError as error:
            _print_error(str(error))
            return 4
        except WorkflowError as error:
            _print_error(str(error))
            return 3
        except OSError:
            _print_error("local storage operation failed")
            return 4
        except Exception:
            _print_error("theme aggregation failed")
            return 4

        print(format_aggregate_themes_summary(aggregate_summary))
        return 0

    if args.command == "score-themes":
        current_utc = datetime.now(UTC)
        try:
            score_request = ScoreThemesRequest(
                start_month=args.start,
                end_month=args.end,
                database_path=config.database_path,
                export_directory=config.export_directory,
                plan_only=args.plan_only,
                skip_export=args.skip_export,
                top_n=args.top,
            )
            score_summary = score_themes(
                score_request,
                config,
                current_utc=current_utc,
            )
        except InvalidMonthError as error:
            _print_error(str(error))
            return 2
        except AggregationError as error:
            _print_error(str(error))
            return 3
        except StorageError as error:
            _print_error(str(error))
            return 4
        except WorkflowError as error:
            _print_error(str(error))
            return 2
        except OSError:
            _print_error("local storage operation failed")
            return 4
        except Exception:
            _print_error("theme trend scoring failed")
            return 4

        print(format_score_themes_summary(score_summary))
        return 0

    if args.command == "model-themes":
        current_utc = datetime.now(UTC)
        model_request = ModelThemesRequest(
            start_month=args.start,
            end_month=args.end,
            database_path=config.database_path,
            export_directory=config.export_directory,
            plan_only=args.plan_only,
            skip_export=args.skip_export,
        )
        try:
            model_summary = model_themes(
                model_request,
                config,
                current_utc=current_utc,
            )
        except InvalidMonthError as error:
            _print_error(str(error))
            return 2
        except AggregationError as error:
            _print_error(str(error))
            return 4
        except StorageError as error:
            _print_error("local MODEL-002 storage operation failed")
            LOGGER.debug("MODEL-002 storage failure: %s", error)
            return 4
        except ModelThemesError as error:
            _print_error(str(error))
            return 4
        except WorkflowError as error:
            _print_error(str(error))
            return 2
        except OSError:
            _print_error("local MODEL-002 storage operation failed")
            return 4
        except Exception:
            _print_error("theme model calculation failed")
            return 4

        print(format_model_themes_summary(model_summary))
        return 0

    _print_error("unsupported command")
    return 2


def _print_error(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)


def _backfill_failure_exit_code(failure_kind: str) -> int:
    if failure_kind == "configuration":
        return 2
    if failure_kind == "storage":
        return 4
    return 3
