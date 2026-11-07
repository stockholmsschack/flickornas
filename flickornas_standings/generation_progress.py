"""Optional progress reporting for generation entry points."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol

from tqdm import tqdm


class ProgressReporter(Protocol):
    """Receives lifecycle events for long-running pipeline operations."""

    def begin_phase(self, description: str, total: int, unit: str) -> None: ...

    def start(self, operation: str) -> None: ...

    def complete(self) -> None: ...


class ConsoleProgress:
    """Render pipeline progress and the current operation in the console."""

    def __init__(self) -> None:
        self._bar: tqdm | None = None

    def begin_phase(self, description: str, total: int, unit: str) -> None:
        if self._bar is not None:
            self._bar.close()
        self._bar = tqdm(
            total=total,
            desc=description,
            unit=unit,
            dynamic_ncols=True,
            bar_format="{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} {unit}",
        )

    def start(self, operation: str) -> None:
        if self._bar is None:
            tqdm.write(f"{operation}...")
        else:
            self._bar.set_description_str(operation, refresh=True)

    def complete(self) -> None:
        if self._bar is not None:
            self._bar.update()

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()

    def __enter__(self) -> ConsoleProgress:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


@contextmanager
def operation(
    progress: ProgressReporter | None,
    description: str,
) -> Iterator[None]:
    """Report an operation as complete only when its body succeeds."""
    if progress is not None:
        progress.start(description)
    yield
    if progress is not None:
        progress.complete()
