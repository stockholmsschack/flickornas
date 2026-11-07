"""Discover user-facing generated files without serving their contents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
from urllib.parse import quote
from zoneinfo import ZoneInfo


RUNS_DIRECTORY = "runs"
STOCKHOLM = ZoneInfo("Europe/Stockholm")


@dataclass(frozen=True)
class AvailableFile:
    label_key: str
    partial: bool
    generated_at: datetime
    download_url: str
    order: int


_DOWNLOAD_FILE_TYPES = (
    (("flickornas-standings.pdf",), "available_files.names.pdf", True),
    (("standings.pdf",), "available_files.names.pdf", True),
    (("standings.xlsx",), "available_files.names.standings_workbook", True),
    (("validation.xlsx",), "available_files.names.validation_workbook", True),
)

_REPORT_FILE_TYPES = (
    (("standings.json",), "available_files.names.json", False),
    (
        ("diagnostics", "walkovers.txt"),
        "available_files.names.walkovers",
        False,
    ),
    (
        ("diagnostics", "no_matches_played.txt"),
        "available_files.names.no_matches_played",
        False,
    ),
    (
        ("diagnostics", "dropouts.txt"),
        "available_files.names.dropouts",
        False,
    ),
    (
        ("diagnostics", "unmatched_player_ids.txt"),
        "available_files.names.unmatched_players",
        False,
    ),
    (
        ("diagnostics", "round_count_mismatches.txt"),
        "available_files.names.round_count_mismatches",
        False,
    ),
)


def list_available_files(
    output_directory: Path,
    public_origin: str = "",
) -> tuple[AvailableFile, ...]:
    """Return standings deliverables, newest generation first."""
    return _list_files(
        output_directory,
        _DOWNLOAD_FILE_TYPES,
        public_file_url(public_origin, "/downloads"),
    )


def list_report_files(
    output_directory: Path,
    public_origin: str = "",
) -> tuple[AvailableFile, ...]:
    """Return generated data and diagnostic reports, newest first."""
    return _list_files(
        output_directory,
        _REPORT_FILE_TYPES,
        public_file_url(public_origin, "/reports"),
    )


def _list_files(
    output_directory: Path,
    file_types: tuple[tuple[tuple[str, ...], str, bool], ...],
    url_prefix: str,
) -> tuple[AvailableFile, ...]:
    download_root = Path(output_directory) / RUNS_DIRECTORY
    if not download_root.is_dir() or download_root.is_symlink():
        return ()

    try:
        generation_directories = tuple(download_root.iterdir())
    except OSError:
        return ()

    files: list[AvailableFile] = []
    for run_directory in generation_directories:
        if not run_directory.is_dir() or run_directory.is_symlink():
            continue
        for order, (relative_parts, label_key, timestamped) in enumerate(
            file_types
        ):
            candidates = _candidate_files(
                run_directory,
                relative_parts,
                timestamped,
            )
            for candidate, partial, filename_timestamp in candidates:
                download_url = _download_url(
                    download_root,
                    candidate,
                    url_prefix,
                )
                if download_url is None:
                    continue
                try:
                    generated_at = _generated_at(
                        candidate,
                        filename_timestamp,
                    )
                except (OSError, ValueError):
                    continue
                files.append(
                    AvailableFile(
                        label_key=label_key,
                        partial=partial,
                        generated_at=generated_at,
                        download_url=download_url,
                        order=order,
                    )
                )

    return tuple(
        sorted(
            files,
            key=lambda item: (-item.generated_at.timestamp(), item.order),
        )
    )


def generation_download_links(
    run_id: str,
    partial: bool,
    *,
    pdf_filename: str | None = None,
    public_origin: str = "",
    url_prefix: str = "",
) -> dict[str, str]:
    """Return links to the run PDF and the Available files page."""
    filename = pdf_filename or (
        "standings-partial.pdf" if partial else "standings.pdf"
    )
    encoded_run_id = quote(run_id, safe="")
    encoded_filename = quote(filename, safe="")
    return {
        "files": f"{url_prefix}/downloads",
        "pdf": public_file_url(
            public_origin,
            f"/downloads/{encoded_run_id}/{encoded_filename}",
        ),
    }


def public_file_url(public_origin: str, path: str) -> str:
    return f"{public_origin.rstrip('/')}{path}"


def _candidate_files(
    run_directory: Path,
    relative_parts: tuple[str, ...],
    timestamped: bool,
) -> tuple[tuple[Path, bool, str | None], ...]:
    if not timestamped:
        return tuple(
            (
                run_directory.joinpath(
                    *_partial_parts(relative_parts, partial)
                ),
                partial,
                None,
            )
            for partial in (False, True)
        )

    expected = Path(relative_parts[-1])
    pattern = re.compile(
        rf"^{re.escape(expected.stem)}"
        rf"(?P<partial>-partial)?"
        rf"(?:-(?P<timestamp>\d{{8}}T\d{{6}}Z))?"
        rf"{re.escape(expected.suffix)}$"
    )
    try:
        children = tuple(run_directory.iterdir())
    except OSError:
        return ()

    matches = []
    for candidate in children:
        match = pattern.fullmatch(candidate.name)
        if match is not None:
            matches.append(
                (
                    candidate,
                    match.group("partial") is not None,
                    match.group("timestamp"),
                )
            )
    return tuple(matches)


def _generated_at(candidate: Path, timestamp: str | None) -> datetime:
    if timestamp is not None:
        generated_at = datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ")
        return generated_at.replace(tzinfo=UTC).astimezone(STOCKHOLM)
    return datetime.fromtimestamp(candidate.stat().st_mtime, tz=STOCKHOLM)


def _partial_parts(parts: tuple[str, ...], partial: bool) -> tuple[str, ...]:
    if not partial:
        return parts
    filename = Path(parts[-1])
    partial_name = f"{filename.stem}-partial{filename.suffix}"
    return (*parts[:-1], partial_name)


def _download_url(
    download_root: Path,
    candidate: Path,
    url_prefix: str,
) -> str | None:
    """Build a direct URL only for a regular file contained by the root."""
    if not candidate.is_file():
        return None

    try:
        relative = candidate.relative_to(download_root)
        resolved_root = download_root.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
        resolved_candidate.relative_to(resolved_root)
    except (OSError, ValueError):
        return None

    current = download_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return None

    encoded_path = "/".join(quote(part, safe="") for part in relative.parts)
    return f"{url_prefix}/{encoded_path}"
