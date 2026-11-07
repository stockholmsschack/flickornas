"""Durable metadata and rendering projections for immutable runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
from typing import Any

from .atomic_write import atomic_create_text, atomic_replace_text
from .generation_core import RenderingProjection


RUN_RECORDS_DIRECTORY = "runs"
RENDERING_PROJECTIONS_DIRECTORY = "rendering-projections"


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    effective_year: int
    tournament_ids: tuple[int, ...]
    kind: str
    layout: str
    source_run_id: str | None
    outcome: str
    artifacts_available: bool


def save_run_state(
    state_directory: Path,
    record: RunRecord,
    projection: RenderingProjection,
) -> tuple[Path, Path]:
    """Atomically create a run record and its reusable rendering projection."""
    state_directory = Path(state_directory)
    record_path = _record_path(state_directory, record.run_id)
    projection_path = _projection_path(state_directory, record.run_id)
    if record_path.exists() or projection_path.exists():
        raise FileExistsError(f"run state {record.run_id!r} already exists")

    projection_document = {
        "effective_year": projection.effective_year,
        "tournament_ids": list(projection.tournament_ids),
        "tournament_names": list(projection.tournament_names),
        "rows": [dict(row) for row in projection.rows],
        "contributor_name": projection.contributor_name,
        "contributor_email": projection.contributor_email,
    }
    _atomic_create_json(projection_path, projection_document)
    try:
        _atomic_create_json(record_path, asdict(record))
    except Exception:
        projection_path.unlink(missing_ok=True)
        raise
    return record_path, projection_path


def load_run_record(state_directory: Path, run_id: str) -> RunRecord:
    document = _load_json(_record_path(Path(state_directory), run_id))
    return RunRecord(
        run_id=str(document["run_id"]),
        effective_year=int(document["effective_year"]),
        tournament_ids=tuple(int(value) for value in document["tournament_ids"]),
        kind=str(document["kind"]),
        layout=str(document["layout"]),
        source_run_id=document.get("source_run_id"),
        outcome=str(document["outcome"]),
        artifacts_available=bool(document["artifacts_available"]),
    )


def load_rendering_projection(
    state_directory: Path,
    run_id: str,
) -> RenderingProjection:
    document = _load_json(_projection_path(Path(state_directory), run_id))
    return RenderingProjection(
        effective_year=int(document["effective_year"]),
        tournament_ids=tuple(str(value) for value in document["tournament_ids"]),
        tournament_names=tuple(
            str(value) for value in document["tournament_names"]
        ),
        rows=tuple(dict(row) for row in document["rows"]),
        contributor_name=str(document["contributor_name"]),
        contributor_email=str(document["contributor_email"]),
    )


def remove_run_state(state_directory: Path, run_id: str) -> None:
    """Roll back state created for a run that could not be committed."""
    state_directory = Path(state_directory)
    _record_path(state_directory, run_id).unlink(missing_ok=True)
    _projection_path(state_directory, run_id).unlink(missing_ok=True)


def mark_all_artifacts_unavailable(state_directory: Path) -> int:
    """Mark every retained run record as having no downloadable artifacts."""
    records_directory = Path(state_directory) / RUN_RECORDS_DIRECTORY
    if not records_directory.is_dir():
        return 0

    records = [
        load_run_record(state_directory, path.stem)
        for path in sorted(records_directory.glob("*.json"))
    ]
    for record in records:
        if record.artifacts_available:
            _atomic_replace_json(
                _record_path(Path(state_directory), record.run_id),
                asdict(replace(record, artifacts_available=False)),
            )
    return len(records)


def _record_path(state_directory: Path, run_id: str) -> Path:
    return state_directory / RUN_RECORDS_DIRECTORY / f"{run_id}.json"


def _projection_path(state_directory: Path, run_id: str) -> Path:
    return (
        state_directory
        / RENDERING_PROJECTIONS_DIRECTORY
        / f"{run_id}.json"
    )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FileNotFoundError(f"run state is unavailable: {path}") from error
    if not isinstance(document, dict):
        raise ValueError(f"run state must be a JSON object: {path}")
    return document


def _atomic_create_json(path: Path, document: dict[str, Any]) -> None:
    _atomic_write_json(path, document, replace_existing=False)


def _atomic_replace_json(path: Path, document: dict[str, Any]) -> None:
    _atomic_write_json(path, document, replace_existing=True)


def _atomic_write_json(
    path: Path,
    document: dict[str, Any],
    *,
    replace_existing: bool,
) -> None:
    content = json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"
    if replace_existing:
        atomic_replace_text(path, content)
    else:
        atomic_create_text(path, content)
