"""Application entrypoint for bootstrap and local collection commands."""

from __future__ import annotations

from collections.abc import Sequence

from .cli import main as cli_main


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI while preserving the no-command bootstrap behavior."""

    return cli_main(() if argv is None else argv)
