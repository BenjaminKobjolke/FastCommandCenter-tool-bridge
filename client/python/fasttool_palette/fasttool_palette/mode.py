"""--palette command-line flag helper. Pure stdlib, win32-free, unit-testable."""

from __future__ import annotations

import sys

PALETTE_FLAG = "--palette"


def palette_mode(argv: list[str] | None = None) -> bool:
    """Whether this process was launched in palette-managed mode.

    Pass argv explicitly in tests; at the real entry point call with no
    argument to read sys.argv[1:].
    """
    args = sys.argv[1:] if argv is None else argv
    return PALETTE_FLAG in args
