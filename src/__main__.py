"""Module entrypoint for ``python -m src``."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from .main import main as _main


def main(argv: Sequence[str] | None = None) -> int:
    """Expose a test-friendly entrypoint and forward real module arguments."""

    return _main(() if argv is None else argv)

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
