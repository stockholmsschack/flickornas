"""Compare generated Typst source with an accepted golden source."""

from __future__ import annotations

import argparse
import difflib
from pathlib import Path


class TypstMismatch(AssertionError):
    """Raised when generated Typst differs from its golden baseline."""


def compare_typst(golden_path: Path, actual_path: Path) -> None:
    """Require byte-for-byte equality and report a readable source diff."""
    golden = golden_path.read_bytes()
    actual = actual_path.read_bytes()
    if golden == actual:
        return

    golden_text = golden.decode("utf-8", errors="replace").splitlines(keepends=True)
    actual_text = actual.decode("utf-8", errors="replace").splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            golden_text,
            actual_text,
            fromfile=str(golden_path),
            tofile=str(actual_path),
        )
    )
    raise TypstMismatch(f"generated Typst differs from the golden baseline\n{diff}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare generated Typst source byte-for-byte with a golden file."
    )
    parser.add_argument("golden", type=Path)
    parser.add_argument("actual", type=Path)
    args = parser.parse_args()

    try:
        compare_typst(args.golden, args.actual)
    except (OSError, TypstMismatch) as error:
        parser.exit(1, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
