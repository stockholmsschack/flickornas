"""Render, record, and transactionally publish immutable standings runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Protocol
from uuid import uuid4

from .active_configuration import ActiveConfiguration
from .generation_core import (
    GeneratedArtifacts,
    GenerationResult,
    RenderingProjection,
    render_projection_to_typst,
    resolve_layout,
)
from .generation_orchestrator import (
    GenerationInputs,
    ResolvedGenerationRequest,
    GenerationStageError,
    run_generation,
)
from .generation_progress import ProgressReporter, operation
from .member_system_client import MemberSystemClient
from .run_state import (
    RENDERING_PROJECTIONS_DIRECTORY,
    RunRecord,
    load_rendering_projection,
    load_run_record,
    mark_all_artifacts_unavailable,
    remove_run_state,
    save_run_state,
)
from .typst_rules import effective_rules_path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TYPST_ASSETS = PROJECT_ROOT / "typst"
PUBLISHED_PDF_LINK = "published-pdf"
PUBLIC_JSON_LINK = "public-standings.json"
RUNS_DIRECTORY = "runs"
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_TYPST_SUPPORT_FILES = ("lib.typ", "rules.typ", "stsf.png")
_DELIVERABLE_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


class Renderer(Protocol):
    def render(
        self,
        source: Path,
        destination: Path,
        *,
        root: Path,
        font_directory: Path,
    ) -> None: ...


@dataclass(frozen=True)
class PublishedGeneration:
    result: GenerationResult | None
    record: RunRecord
    run_id: str
    run_directory: Path
    pdf_path: Path


class TypstRenderer:
    """Compile Typst while explicitly excluding every system font."""

    def __init__(self, executable: str = "typst") -> None:
        self.executable = executable

    def render(
        self,
        source: Path,
        destination: Path,
        *,
        root: Path,
        font_directory: Path,
    ) -> None:
        try:
            completed = subprocess.run(
                [
                    self.executable,
                    "compile",
                    "--root",
                    str(root),
                    "--font-path",
                    str(font_directory),
                    "--ignore-system-fonts",
                    "--no-pdf-tags",
                    str(source),
                    str(destination),
                ],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as error:
            raise RuntimeError(
                f"could not start Typst renderer: {error}"
            ) from error
        if completed.returncode:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(
                f"Typst exited with status {completed.returncode}: {detail}"
            )
        if not destination.is_file() or not destination.stat().st_size:
            raise RuntimeError("Typst did not produce a PDF")


def clear_downloads(output_directory: Path, state_directory: Path) -> int:
    """Remove generated files while retaining configuration and run metadata."""
    output_directory = Path(output_directory)
    state_directory = Path(state_directory)

    record_count = mark_all_artifacts_unavailable(state_directory)
    for reference in (PUBLISHED_PDF_LINK, PUBLIC_JSON_LINK):
        (output_directory / reference).unlink(missing_ok=True)
    for directory in (
        output_directory / RUNS_DIRECTORY,
        state_directory / RENDERING_PROJECTIONS_DIRECTORY,
    ):
        if directory.exists():
            shutil.rmtree(directory)
    return record_count


def read_public_snapshot(output_directory: Path) -> bytes | None:
    """Read the published JSON snapshot, or return not found explicitly."""
    return _read_publication_reference(
        Path(output_directory) / PUBLIC_JSON_LINK
    )


def read_published_pdf(output_directory: Path) -> bytes | None:
    """Read the published PDF, or return not found explicitly."""
    return _read_publication_reference(
        Path(output_directory) / PUBLISHED_PDF_LINK
    )


def generate_and_publish(
    configuration: ActiveConfiguration,
    request: ResolvedGenerationRequest | GenerationInputs,
    client: MemberSystemClient,
    output_directory: Path,
    *,
    state_directory: Path | None = None,
    publish: bool | None = None,
    run_id: str | None = None,
    typst_assets: Path = DEFAULT_TYPST_ASSETS,
    renderer: Renderer | None = None,
    progress: ProgressReporter | None = None,
) -> PublishedGeneration:
    """Run the complete pipeline, persist its state, and optionally publish."""
    result = run_generation(configuration, request, client, progress=progress)
    inputs = (
        request.inputs
        if isinstance(request, ResolvedGenerationRequest)
        else request
    )
    return publish_generation(
        result,
        output_directory,
        configuration=configuration,
        inputs=inputs,
        state_directory=state_directory,
        publish=publish,
        run_id=run_id,
        typst_assets=typst_assets,
        renderer=renderer,
        progress=progress,
    )


def publish_generation(
    result: GenerationResult,
    output_directory: Path,
    *,
    configuration: ActiveConfiguration | None = None,
    inputs: GenerationInputs | None = None,
    state_directory: Path | None = None,
    partial: bool | None = None,
    publish: bool | None = None,
    run_id: str | None = None,
    typst_assets: Path = DEFAULT_TYPST_ASSETS,
    renderer: Renderer | None = None,
    progress: ProgressReporter | None = None,
) -> PublishedGeneration:
    """Persist one generated run and apply safe publication defaults."""
    projection = result.rendering_projection
    resolved_partial = (
        inputs.is_partial
        if partial is None and inputs is not None
        else bool(partial)
    )
    resolved_inputs = inputs or GenerationInputs(
        effective_year=projection.effective_year,
        tournament_ids=tuple(int(value) for value in projection.tournament_ids),
        is_partial=resolved_partial,
    )
    resolved_configuration = configuration or ActiveConfiguration(
        default_tournament_ids=resolved_inputs.tournament_ids,
        contributor={
            "name": projection.contributor_name,
            "email": projection.contributor_email,
        },
    )
    return _publish_run(
        result=result,
        projection=projection,
        artifacts=result.artifacts,
        configuration=resolved_configuration,
        inputs=resolved_inputs,
        output_directory=Path(output_directory),
        state_directory=_state_directory(output_directory, state_directory),
        kind="partial" if resolved_partial else "full",
        source_run_id=None,
        partial=resolved_partial,
        publish=(not resolved_partial) if publish is None else publish,
        run_id=run_id,
        typst_assets=Path(typst_assets),
        renderer=renderer,
        progress=progress,
    )


def render_run(
    source_run_id: str,
    configuration: ActiveConfiguration,
    state_directory: Path,
    output_directory: Path,
    *,
    layout: str = "auto",
    publish: bool = False,
    run_id: str | None = None,
    typst_assets: Path = DEFAULT_TYPST_ASSETS,
    renderer: Renderer | None = None,
    progress: ProgressReporter | None = None,
) -> PublishedGeneration:
    """Create a new run solely from a persisted rendering projection."""
    _validate_run_id(source_run_id)
    source_record = load_run_record(state_directory, source_run_id)
    if not source_record.artifacts_available:
        raise GenerationStageError(
            "rendering",
            f"source run {source_run_id!r} artifacts are unavailable",
        )
    projection = load_rendering_projection(state_directory, source_run_id)
    partial = _source_is_partial(state_directory, source_record)
    typst_source = render_projection_to_typst(
        projection,
        layout_configuration=configuration.layout,
        club_display_names=configuration.club_display_names,
        finals_separators=configuration.finals_separators,
        layout=layout,
    )
    inputs = GenerationInputs(
        effective_year=source_record.effective_year,
        tournament_ids=source_record.tournament_ids,
        is_partial=partial,
        layout=layout,
    )
    return _publish_run(
        result=None,
        projection=projection,
        artifacts=GeneratedArtifacts(
            validation_workbook=b"",
            standings_workbook=b"",
            typst_source=typst_source,
            standings_json="",
            diagnostic_reports={},
        ),
        configuration=configuration,
        inputs=inputs,
        output_directory=Path(output_directory),
        state_directory=Path(state_directory),
        kind="render",
        source_run_id=source_run_id,
        partial=partial,
        publish=publish,
        run_id=run_id,
        typst_assets=Path(typst_assets),
        renderer=renderer,
        progress=progress,
    )


def _publish_run(
    *,
    result: GenerationResult | None,
    projection: RenderingProjection,
    artifacts: GeneratedArtifacts,
    configuration: ActiveConfiguration,
    inputs: GenerationInputs,
    output_directory: Path,
    state_directory: Path,
    kind: str,
    source_run_id: str | None,
    partial: bool,
    publish: bool,
    run_id: str | None,
    typst_assets: Path,
    renderer: Renderer | None,
    progress: ProgressReporter | None,
) -> PublishedGeneration:
    generated_at = datetime.now(UTC)
    resolved_run_id = run_id or _new_run_id(generated_at)
    deliverable_timestamp = generated_at.strftime(
        _DELIVERABLE_TIMESTAMP_FORMAT
    )
    pdf_filename = _deliverable_name(
        "flickornas-standings.pdf",
        partial,
        deliverable_timestamp,
    )
    try:
        _validate_run_id(resolved_run_id)
    except ValueError as error:
        raise GenerationStageError("committing", str(error)) from error
    target = output_directory / RUNS_DIRECTORY / resolved_run_id
    if target.exists():
        raise GenerationStageError(
            "committing",
            f"run {resolved_run_id!r} already exists",
        )

    effective_layout = resolve_layout(
        inputs.layout,
        len(inputs.tournament_ids),
        configuration.layout,
    )
    rules_source = effective_rules_path(
        state_directory,
        typst_assets / "rules.typ",
    )
    record = RunRecord(
        run_id=resolved_run_id,
        effective_year=inputs.effective_year,
        tournament_ids=inputs.tournament_ids,
        kind=kind,
        layout=effective_layout,
        source_run_id=source_run_id,
        outcome="succeeded",
        artifacts_available=True,
    )

    output_directory.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{resolved_run_id}-", dir=output_directory)
    )
    try:
        try:
            with operation(progress, "Staging artifacts"):
                if kind == "render":
                    _stage_render_artifacts(
                        artifacts.typst_source,
                        staging,
                        typst_assets,
                        rules_source=rules_source,
                        partial=partial,
                    )
                else:
                    _stage_generation_artifacts(
                        artifacts,
                        staging,
                        typst_assets,
                        rules_source=rules_source,
                        partial=partial,
                        deliverable_timestamp=deliverable_timestamp,
                    )
        except Exception as error:
            raise GenerationStageError("artifact staging", str(error)) from error

        try:
            with operation(progress, "Rendering PDF"):
                (renderer or TypstRenderer()).render(
                    staging / _artifact_name("standings.typ", partial),
                    staging / pdf_filename,
                    root=staging,
                    font_directory=staging / "fonts",
                )
        except Exception as error:
            raise GenerationStageError("rendering", str(error)) from error

        with operation(progress, "Publishing generation"):
            _commit(
                staging,
                target,
                state_directory,
                record,
                projection,
                output_directory,
                partial=partial,
                pdf_filename=pdf_filename,
                publish_pdf=publish,
                publish_json=publish and kind == "full",
            )
    finally:
        if staging.exists():
            shutil.rmtree(staging)

    return PublishedGeneration(
        result=result,
        record=record,
        run_id=resolved_run_id,
        run_directory=target,
        pdf_path=target / pdf_filename,
    )


def _stage_generation_artifacts(
    artifacts: GeneratedArtifacts,
    staging: Path,
    typst_assets: Path,
    *,
    rules_source: Path | None = None,
    partial: bool,
    deliverable_timestamp: str,
) -> None:
    validation_filename = _deliverable_name(
        "validation.xlsx",
        partial,
        deliverable_timestamp,
    )
    standings_filename = _deliverable_name(
        "standings.xlsx",
        partial,
        deliverable_timestamp,
    )
    (staging / validation_filename).write_bytes(
        artifacts.validation_workbook
    )
    (staging / standings_filename).write_bytes(
        artifacts.standings_workbook
    )
    (staging / _artifact_name("standings.json", partial)).write_text(
        artifacts.standings_json,
        encoding="utf-8",
    )
    diagnostics = staging / "diagnostics"
    diagnostics.mkdir()
    for filename, report in artifacts.diagnostic_reports.items():
        (diagnostics / _artifact_name(filename, partial)).write_text(
            report,
            encoding="utf-8",
        )
    _stage_render_artifacts(
        artifacts.typst_source,
        staging,
        typst_assets,
        rules_source=rules_source,
        partial=partial,
    )


def _stage_render_artifacts(
    typst_source: str,
    staging: Path,
    typst_assets: Path,
    *,
    rules_source: Path | None = None,
    partial: bool,
) -> None:
    (staging / _artifact_name("standings.typ", partial)).write_text(
        typst_source,
        encoding="utf-8",
    )
    for filename in _TYPST_SUPPORT_FILES:
        source = (
            rules_source
            if filename == "rules.typ" and rules_source is not None
            else typst_assets / filename
        )
        if not source.is_file():
            raise FileNotFoundError(f"missing bundled Typst asset: {source}")
        shutil.copy2(source, staging / filename)

    fonts = typst_assets / "fonts"
    has_fonts = fonts.is_dir() and any(
        path.is_file() and path.suffix.lower() in {".otf", ".ttf"}
        for path in fonts.iterdir()
    )
    if not has_fonts:
        raise FileNotFoundError(f"no bundled Typst fonts found in: {fonts}")
    shutil.copytree(fonts, staging / "fonts")


def _artifact_name(filename: str, partial: bool) -> str:
    if not partial:
        return filename
    path = Path(filename)
    return f"{path.stem}-partial{path.suffix}"


def _deliverable_name(
    filename: str,
    partial: bool,
    timestamp: str,
) -> str:
    path = Path(_artifact_name(filename, partial))
    return f"{path.stem}-{timestamp}{path.suffix}"


def _commit(
    staging: Path,
    target: Path,
    state_directory: Path,
    record: RunRecord,
    projection: RenderingProjection,
    output_directory: Path,
    *,
    partial: bool,
    pdf_filename: str,
    publish_pdf: bool,
    publish_json: bool,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    changed_links: list[tuple[Path, str | None]] = []
    committed = False
    state_saved = False
    try:
        os.replace(staging, target)
        committed = True
        save_run_state(state_directory, record, projection)
        state_saved = True
        if publish_json:
            changed_links.append(
                _replace_link(
                    output_directory / PUBLIC_JSON_LINK,
                    Path(RUNS_DIRECTORY)
                    / target.name
                    / _artifact_name("standings.json", partial),
                )
            )
        if publish_pdf:
            changed_links.append(
                _replace_link(
                    output_directory / PUBLISHED_PDF_LINK,
                    Path(RUNS_DIRECTORY)
                    / target.name
                    / pdf_filename,
                )
            )
    except Exception as error:
        for path, old_target in reversed(changed_links):
            _restore_link(path, old_target)
        if state_saved:
            remove_run_state(state_directory, record.run_id)
        if committed and target.exists():
            shutil.rmtree(target)
        if isinstance(error, GenerationStageError):
            raise
        raise GenerationStageError("committing", str(error)) from error


def _replace_link(path: Path, target: Path) -> tuple[Path, str | None]:
    if path.exists() and not path.is_symlink():
        raise FileExistsError(f"publication reference is not a symlink: {path}")
    old_target = os.readlink(path) if path.is_symlink() else None
    temporary = path.parent / f".{path.name}-{uuid4().hex}"
    try:
        os.symlink(target, temporary)
        os.replace(temporary, path)
    finally:
        if temporary.is_symlink():
            temporary.unlink()
    return path, old_target


def _restore_link(path: Path, old_target: str | None) -> None:
    if old_target is None:
        path.unlink(missing_ok=True)
        return
    temporary = path.parent / f".{path.name}-rollback-{uuid4().hex}"
    os.symlink(old_target, temporary)
    os.replace(temporary, path)


def _read_publication_reference(path: Path) -> bytes | None:
    if not path.is_symlink():
        return None
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _source_is_partial(
    state_directory: Path,
    source_record: RunRecord,
) -> bool:
    record = source_record
    visited = set()
    while record.kind == "render":
        if record.run_id in visited or record.source_run_id is None:
            raise GenerationStageError("rendering", "invalid render provenance")
        visited.add(record.run_id)
        record = load_run_record(state_directory, record.source_run_id)
    return record.kind == "partial"


def _state_directory(
    output_directory: Path,
    state_directory: Path | None,
) -> Path:
    output_directory = Path(output_directory)
    return (
        Path(state_directory)
        if state_directory is not None
        else output_directory.parent / "state"
    )


def _validate_run_id(run_id: str) -> None:
    if not _RUN_ID_PATTERN.fullmatch(run_id) or run_id in {".", ".."}:
        raise ValueError(
            "run_id must contain only letters, digits, dots, underscores, "
            "and hyphens"
        )


def _new_run_id(generated_at: datetime) -> str:
    timestamp = generated_at.strftime(_DELIVERABLE_TIMESTAMP_FORMAT)
    return f"{timestamp}-{uuid4().hex[:8]}"
