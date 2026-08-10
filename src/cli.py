"""Command-line interface for the local application and collection workflow."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import ValidationError

from .config import load_config
from .logging_config import configure_logging
from .sensor_tower.errors import SensorTowerConfigurationError, SensorTowerError
from .storage.errors import StorageError
from .workflows import (
    CollectMonthRequest,
    InvalidMonthError,
    WorkflowError,
    collect_month,
    format_collection_summary,
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested local command and return a categorized exit code."""

    args = build_parser().parse_args(argv)
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

    _print_error("unsupported command")
    return 2


def _print_error(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
