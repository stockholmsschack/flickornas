"""Packaged standalone web entry point."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from . import create_app


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local Flickornas standings web application.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface to bind (default: 127.0.0.1).",
    )
    parser.add_argument("--port", default=7001, type=int)
    parser.add_argument("--state-directory", default=Path("state"), type=Path)
    parser.add_argument("--output-directory", default=Path("output"), type=Path)
    parser.add_argument("--debug", action="store_true")
    return parser


def main(arguments: Sequence[str] | None = None) -> None:
    """Run the standalone app with the local operator already authorized."""
    options = _parser().parse_args(arguments)
    app = create_app(
        {
            "STATE_DIRECTORY": options.state_directory,
            "OUTPUT_DIRECTORY": options.output_directory,
        }
    )
    run_options = {
        "host": options.host,
        "port": options.port,
        "debug": options.debug,
    }
    if options.debug:
        run_options["extra_files"] = tuple(
            (Path(__file__).parent / "locales").glob("*.json")
        )
    app.run(**run_options)


if __name__ == "__main__":
    main()
