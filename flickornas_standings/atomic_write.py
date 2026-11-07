"""Crash-safe atomic file replacement and creation."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Callable


ReplaceFunction = Callable[[Path, Path], None]


def atomic_replace_bytes(path: Path, content: bytes) -> None:
    """Replace path with complete content and fsync the containing directory."""
    _atomic_write(Path(path), content, replace_existing=True)


def atomic_create_bytes(path: Path, content: bytes) -> None:
    """Create path atomically and fail if another writer created it first."""
    _atomic_write(Path(path), content, replace_existing=False)


def atomic_replace_text(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    replace: ReplaceFunction | None = None,
) -> None:
    """Encode and atomically replace a text file."""
    _atomic_write(
        Path(path),
        content.encode(encoding),
        replace_existing=True,
        replace=replace,
    )


def atomic_create_text(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Encode and atomically create a text file."""
    atomic_create_bytes(path, content.encode(encoding))


def _atomic_write(
    path: Path,
    content: bytes,
    *,
    replace_existing: bool,
    replace: ReplaceFunction | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())

        if replace_existing:
            (replace or os.replace)(temporary_path, path)
        else:
            os.link(temporary_path, path)
            temporary_path.unlink()
        temporary_path = None
        _fsync_directory(path.parent)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
