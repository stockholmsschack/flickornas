"""Command-line adapter for Flickornas standings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
import os
from pathlib import Path
import re
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from .active_configuration import (
    ActiveConfiguration,
    ConfigurationValidationError,
    configuration_path,
    load_configuration,
)
from .artifact_publication import (
    PUBLISHED_PDF_LINK,
    RUNS_DIRECTORY,
    Renderer,
    TypstRenderer,
    clear_downloads as clear_generated_downloads,
    generate_and_publish,
    render_run,
)
from .generation_orchestrator import (
    GenerationInputs,
    resolve_generation_request,
    GenerationStageError,
    resolve_generation_inputs,
    validate_generation_inputs,
)
from .generation_progress import ProgressReporter
from .member_system_client import MemberSystemClient


@dataclass(frozen=True)
class WorkingDirectories:
    """Filesystem locations shared by CLI operations."""

    state: Path
    output: Path


class RichProgress:
    """Present generation stages without coupling the core to Rich."""

    def __init__(self) -> None:
        self.console = Console(stderr=True)

    def begin_phase(self, description: str, total: int, unit: str) -> None:
        self.console.print(
            f"{description} ({total} {unit})",
            style="cyan",
        )

    def start(self, operation: str) -> None:
        self.console.print(f"{operation}...", style="cyan")

    def complete(self) -> None:
        pass


def _calendar_year() -> int:
    return date.today().year


@dataclass(frozen=True)
class CliDependencies:
    """Replaceable runtime services for deterministic command tests."""

    client_factory: Callable[[], MemberSystemClient] = MemberSystemClient
    renderer_factory: Callable[[], Renderer] = TypstRenderer
    current_year: Callable[[], int] = _calendar_year
    progress_factory: Callable[[], ProgressReporter | None] = RichProgress


@dataclass(frozen=True)
class CliContext:
    directories: WorkingDirectories
    dependencies: CliDependencies


def create_app(dependencies: CliDependencies | None = None) -> typer.Typer:
    """Create the command application with replaceable external services."""
    runtime_dependencies = dependencies or CliDependencies()
    application = typer.Typer(
        help="Generate and manage Flickornas standings.",
        no_args_is_help=True,
    )

    @application.callback()
    def configure(
        context: typer.Context,
        state_directory: Annotated[
            Path,
            typer.Option(
                "--state-directory",
                dir_okay=True,
                file_okay=False,
                help="Directory containing active-configuration.toml.",
            ),
        ] = Path("state"),
        output_directory: Annotated[
            Path,
            typer.Option(
                "--output-directory",
                dir_okay=True,
                file_okay=False,
                help="Directory for generated artifacts.",
            ),
        ] = Path("output"),
    ) -> None:
        """Set the state and output directories used by each command."""
        context.obj = CliContext(
            directories=WorkingDirectories(
                state=state_directory,
                output=output_directory,
            ),
            dependencies=runtime_dependencies,
        )

    application.command()(validate)
    application.command()(generate)
    application.command()(render)
    application.command(name="clear-downloads")(clear_downloads)
    return application


def validate(context: typer.Context) -> None:
    """Validate the active configuration without changing any files."""
    runtime = context.ensure_object(CliContext)
    path = configuration_path(runtime.directories.state).resolve()

    try:
        load_configuration(runtime.directories.state)
    except ConfigurationValidationError as error:
        _print_configuration_error(path, error)
        raise typer.Exit(code=1) from error

    message = Text("Configuration valid: ", style="green")
    message.append(str(path), style=None)
    Console().print(message, soft_wrap=True)


def generate(
    context: typer.Context,
    year: Annotated[
        int | None,
        typer.Option("--year", help="Effective standings year."),
    ] = None,
    tournaments: Annotated[
        list[int] | None,
        typer.Option(
            "--tournament",
            help="Tournament ID; repeat to replace the configured list.",
        ),
    ] = None,
    layout: Annotated[
        str,
        typer.Option(
            "--layout",
            help="Page layout: auto, portrait, or landscape.",
        ),
    ] = "auto",
    publish: Annotated[
        bool,
        typer.Option("--publish", help="Publish the successful run."),
    ] = False,
    no_publish: Annotated[
        bool,
        typer.Option(
            "--no-publish",
            help="Do not publish the successful run.",
        ),
    ] = False,
) -> None:
    """Generate, render, record, and optionally publish standings."""
    runtime = context.ensure_object(CliContext)
    if publish and no_publish:
        _print_generation_error(
            "validation",
            "--publish and --no-publish cannot be combined",
        )
        raise typer.Exit(code=1)

    try:
        configuration = load_configuration(runtime.directories.state)
        inputs = _resolve_inputs(
            configuration,
            year=year,
            tournaments=tournaments,
            layout=layout,
            current_year=runtime.dependencies.current_year(),
        )
        client = runtime.dependencies.client_factory()
        resolved = resolve_generation_request(configuration, inputs, client)
        published = generate_and_publish(
            configuration,
            resolved,
            client,
            runtime.directories.output,
            state_directory=runtime.directories.state,
            publish=_publication_choice(publish, no_publish),
            renderer=runtime.dependencies.renderer_factory(),
            progress=runtime.dependencies.progress_factory(),
        )
    except ConfigurationValidationError as error:
        _print_configuration_error(
            configuration_path(runtime.directories.state).resolve(),
            error,
            heading="Generation failed during validation",
        )
        raise typer.Exit(code=1) from error
    except GenerationStageError as error:
        _print_generation_error(error.stage, str(error))
        raise typer.Exit(code=1) from error
    except Exception as error:
        _print_generation_error("generation", str(error))
        raise typer.Exit(code=1) from error

    Console().print(str(published.pdf_path.resolve()), soft_wrap=True)


def render(
    context: typer.Context,
    from_run: Annotated[
        str | None,
        typer.Option(
            "--from-run",
            help="Run ID whose persisted projection should be rendered.",
        ),
    ] = None,
    layout: Annotated[
        str,
        typer.Option(
            "--layout",
            help="Page layout: auto, portrait, or landscape.",
        ),
    ] = "auto",
    publish: Annotated[
        bool,
        typer.Option("--publish", help="Publish the rendered PDF."),
    ] = False,
) -> None:
    """Render a new PDF from an immutable standings projection."""
    runtime = context.ensure_object(CliContext)

    try:
        configuration = load_configuration(runtime.directories.state)
        _validate_render_layout(
            configuration,
            layout,
            runtime.dependencies.current_year(),
        )
        source_run_id = (
            from_run
            if from_run is not None
            else _published_pdf_source_run_id(runtime.directories.output)
        )
        if source_run_id is None:
            source_run_id = _generate_unpublished_render_source(
                runtime,
                configuration,
            )
        rendered = render_run(
            source_run_id,
            configuration,
            runtime.directories.state,
            runtime.directories.output,
            layout=layout,
            publish=publish,
            renderer=runtime.dependencies.renderer_factory(),
            progress=runtime.dependencies.progress_factory(),
        )
    except ConfigurationValidationError as error:
        _print_configuration_error(
            configuration_path(runtime.directories.state).resolve(),
            error,
            heading="Rendering failed during validation",
        )
        raise typer.Exit(code=1) from error
    except GenerationStageError as error:
        _print_generation_error(error.stage, str(error))
        raise typer.Exit(code=1) from error
    except Exception as error:
        _print_generation_error("rendering", str(error))
        raise typer.Exit(code=1) from error

    Console().print(str(rendered.pdf_path.resolve()), soft_wrap=True)


def clear_downloads(context: typer.Context) -> None:
    """Remove generated artifacts while retaining run metadata."""
    runtime = context.ensure_object(CliContext)

    try:
        record_count = clear_generated_downloads(
            runtime.directories.output,
            runtime.directories.state,
        )
    except Exception as error:
        _print_generation_error("cleanup", str(error))
        raise typer.Exit(code=1) from error

    noun = "record" if record_count == 1 else "records"
    Console().print(
        f"Downloads cleared; marked {record_count} retained run "
        f"{noun} unavailable."
    )


def _resolve_inputs(
    configuration: ActiveConfiguration,
    *,
    year: int | None,
    tournaments: list[int] | None,
    layout: str,
    current_year: int,
) -> GenerationInputs:
    inputs = resolve_generation_inputs(
        configuration,
        explicit_year=year,
        explicit_tournament_ids=tournaments,
        current_calendar_year=current_year,
    )
    inputs = replace(inputs, layout=layout)
    validate_generation_inputs(inputs)
    return inputs


def _validate_render_layout(
    configuration: ActiveConfiguration,
    layout: str,
    current_year: int,
) -> None:
    validate_generation_inputs(
        GenerationInputs(
            effective_year=current_year,
            tournament_ids=configuration.default_tournament_ids,
            layout=layout,
        )
    )


def _published_pdf_source_run_id(output_directory: Path) -> str | None:
    reference = Path(output_directory) / PUBLISHED_PDF_LINK
    if not reference.is_symlink():
        if reference.exists():
            raise GenerationStageError(
                "source selection",
                f"published PDF reference is not a symlink: {reference}",
            )
        return None

    target = Path(os.readlink(reference))
    if (
        target.is_absolute()
        or len(target.parts) != 3
        or target.parts[0] != RUNS_DIRECTORY
        or re.fullmatch(
            r"(?:flickornas-)?standings(?:-partial)?(?:-\d{8}T\d{6}Z)?\.pdf",
            target.parts[2],
        )
        is None
    ):
        raise GenerationStageError(
            "source selection",
            f"published PDF reference has an invalid target: {target}",
        )
    return target.parts[1]


def _generate_unpublished_render_source(
    runtime: CliContext,
    configuration: ActiveConfiguration,
) -> str:
    inputs = _resolve_inputs(
        configuration,
        year=None,
        tournaments=None,
        layout="auto",
        current_year=runtime.dependencies.current_year(),
    )
    generated = generate_and_publish(
        configuration,
        inputs,
        runtime.dependencies.client_factory(),
        runtime.directories.output,
        state_directory=runtime.directories.state,
        publish=False,
        renderer=runtime.dependencies.renderer_factory(),
        progress=runtime.dependencies.progress_factory(),
    )
    return generated.run_id


def _publication_choice(publish: bool, no_publish: bool) -> bool | None:
    if publish:
        return True
    if no_publish:
        return False
    return None


def _print_configuration_error(
    path: Path,
    error: ConfigurationValidationError,
    *,
    heading: str = "Invalid configuration",
) -> None:
    console = Console(stderr=True)
    console.print(heading, style="bold red")
    console.print(Text(f"Path: {path}"), soft_wrap=True)
    for problem in error.problems:
        console.print(Text(f"- {problem}"))


def _print_generation_error(stage: str, detail: str) -> None:
    console = Console(stderr=True)
    console.print(f"Generation failed during {stage}", style="bold red")
    console.print(Text(detail), soft_wrap=True)


app = create_app()


def main() -> None:
    """Run the packaged command-line application."""
    app()


if __name__ == "__main__":
    main()
