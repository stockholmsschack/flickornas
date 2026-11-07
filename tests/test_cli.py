from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from flickornas_standings.active_configuration import load_configuration
from flickornas_standings.artifact_publication import PUBLISHED_PDF_LINK, PUBLIC_JSON_LINK
from flickornas_standings.cli import CliDependencies, app, create_app
from flickornas_standings.run_state import load_run_record
from tests.test_generation_orchestrator import FixtureClient, _metadata


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_CONFIGURATION = (
    PROJECT_ROOT / "state" / "active-configuration.toml"
)


class FixtureRenderer:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure

    def render(
        self,
        source: Path,
        destination: Path,
        *,
        root: Path,
        font_directory: Path,
    ) -> None:
        if self.failure is not None:
            raise self.failure
        destination.write_bytes(b"%PDF-1.7\nfixture\n")


def _write_configuration(state: Path) -> Path:
    state.mkdir()
    path = state / "active-configuration.toml"
    path.write_text(
        "revision = 1\n"
        "tournament_ids = [11, 22]\n"
        "[contributor]\n"
        'name = "Fixture"\n'
        'email = "fixture@example.com"\n',
        encoding="utf-8",
    )
    return path


def _generation_app(
    client: FixtureClient,
    renderer: FixtureRenderer | None = None,
):
    fixture_renderer = renderer if renderer is not None else FixtureRenderer()
    return create_app(
        CliDependencies(
            client_factory=lambda: client,
            renderer_factory=lambda: fixture_renderer,
            current_year=lambda: 2026,
            progress_factory=lambda: None,
        )
    )


class CliValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_help_exposes_packaged_commands_and_directory_options(self):
        result = self.runner.invoke(app, ["--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("--state-directory", result.output)
        self.assertIn("--output-directory", result.output)
        self.assertIn("validate", result.output)
        self.assertIn("generate", result.output)
        self.assertIn("render", result.output)
        self.assertIn("clear-downloads", result.output)

    def test_validate_accepts_committed_configuration_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "operator-state"
            output = root / "operator-output"
            state.mkdir()
            destination = state / "active-configuration.toml"
            shutil.copyfile(COMMITTED_CONFIGURATION, destination)
            before = destination.read_bytes()

            result = self.runner.invoke(
                app,
                [
                    "--state-directory",
                    str(state),
                    "--output-directory",
                    str(output),
                    "validate",
                ],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Configuration valid", result.output)
            self.assertIn(str(destination.resolve()), result.output)
            self.assertEqual(destination.read_bytes(), before)
            self.assertEqual(list(state.iterdir()), [destination])
            self.assertFalse(output.exists())

    def test_missing_configuration_names_path_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "missing-state"
            output = root / "missing-output"
            expected_path = state / "active-configuration.toml"

            result = self.runner.invoke(
                app,
                [
                    "--state-directory",
                    str(state),
                    "--output-directory",
                    str(output),
                    "validate",
                ],
            )

            self.assertEqual(result.exit_code, 1, result.output)
            self.assertIn("Invalid configuration", result.output)
            self.assertIn(str(expected_path.resolve()), result.output)
            self.assertFalse(state.exists())
            self.assertFalse(output.exists())

    def test_invalid_configuration_reports_all_problems_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "operator-state"
            output = root / "operator-output"
            state.mkdir()
            configuration = state / "active-configuration.toml"
            configuration.write_text(
                "revision = 1\n"
                "tournament_ids = []\n"
                "[contributor]\n"
                'name = ""\n'
                'email = ""\n',
                encoding="utf-8",
            )
            before = configuration.read_bytes()

            result = self.runner.invoke(
                app,
                [
                    "--state-directory",
                    str(state),
                    "--output-directory",
                    str(output),
                    "validate",
                ],
            )

            self.assertEqual(result.exit_code, 1, result.output)
            self.assertIn(
                "at least one default tournament id is required",
                result.output,
            )
            self.assertIn("contributor name is required", result.output)
            self.assertIn("contributor email is required", result.output)
            self.assertEqual(configuration.read_bytes(), before)
            self.assertEqual(list(state.iterdir()), [configuration])
            self.assertFalse(output.exists())


class CliGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def invoke(
        self,
        root: Path,
        arguments: list[str],
        *,
        client: FixtureClient | None = None,
        renderer: FixtureRenderer | None = None,
    ):
        state = root / "state"
        output = root / "output"
        _write_configuration(state)
        fixture_client = client or FixtureClient()
        result = self.runner.invoke(
            _generation_app(fixture_client, renderer),
            [
                "--state-directory",
                str(state),
                "--output-directory",
                str(output),
                "generate",
                *arguments,
            ],
        )
        return result, fixture_client, state, output

    def test_default_generation_uses_current_year_and_configured_tournaments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            result, client, state, output = self.invoke(root, [])

            self.assertEqual(result.exit_code, 0, result.output)
            pdf_path = Path(result.output.strip())
            self.assertTrue(pdf_path.is_absolute())
            self.assertTrue(pdf_path.is_file())
            run_id = pdf_path.parent.name
            record = load_run_record(state, run_id)
            self.assertEqual(record.effective_year, 2026)
            self.assertEqual(record.tournament_ids, (11, 22))
            self.assertEqual(record.kind, "full")
            self.assertEqual(
                (output / PUBLISHED_PDF_LINK).resolve(),
                pdf_path,
            )
            self.assertEqual(
                (output / PUBLIC_JSON_LINK).resolve(),
                pdf_path.with_name("standings.json"),
            )
            self.assertTrue(client.calls)

    def test_committed_configuration_generates_a_pdf_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            output = root / "output"
            state.mkdir()
            shutil.copyfile(
                COMMITTED_CONFIGURATION,
                state / "active-configuration.toml",
            )
            configuration = load_configuration(state)
            client = FixtureClient()
            client.metadata = {
                tournament_id: _metadata(
                    tournament_id,
                    start="2026-01-01",
                    end="2026-01-02",
                )
                for tournament_id in configuration.default_tournament_ids
            }

            result = self.runner.invoke(
                _generation_app(client),
                [
                    "--state-directory",
                    str(state),
                    "--output-directory",
                    str(output),
                    "generate",
                ],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue(Path(result.output.strip()).is_file())

    def test_year_tournaments_and_layout_override_one_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            result, _, state, _ = self.invoke(
                root,
                [
                    "--year",
                    "2025",
                    "--tournament",
                    "11",
                    "--layout",
                    "landscape",
                ],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            pdf_path = Path(result.output.strip())
            record = load_run_record(state, pdf_path.parent.name)
            self.assertEqual(record.effective_year, 2025)
            self.assertEqual(record.tournament_ids, (11,))
            self.assertEqual(record.kind, "partial")
            self.assertEqual(record.layout, "landscape")
            self.assertRegex(
                pdf_path.name,
                r"^flickornas-standings-partial-\d{8}T\d{6}Z\.pdf$",
            )

    def test_full_and_partial_publication_combinations(self):
        cases = (
            ([], True, True),
            (["--publish"], True, True),
            (["--no-publish"], False, False),
            (["--tournament", "11"], False, False),
            (["--tournament", "11", "--publish"], True, False),
            (["--tournament", "11", "--no-publish"], False, False),
        )
        for arguments, expect_pdf, expect_json in cases:
            with self.subTest(arguments=arguments):
                with tempfile.TemporaryDirectory() as directory:
                    result, _, _, output = self.invoke(
                        Path(directory),
                        arguments,
                    )

                    self.assertEqual(result.exit_code, 0, result.output)
                    self.assertEqual(
                        (output / PUBLISHED_PDF_LINK).is_symlink(),
                        expect_pdf,
                    )
                    self.assertEqual(
                        (output / PUBLIC_JSON_LINK).is_symlink(),
                        expect_json,
                    )

    def test_invalid_inputs_fail_before_network_or_output_writes(self):
        cases = (
            (
                ["--year", "2025"],
                "explicit non-current year requires explicit tournament ids",
            ),
            (
                ["--tournament", "11", "--tournament", "11"],
                "tournament ids must be unique",
            ),
            (
                ["--layout", "square"],
                "layout must be auto, portrait, or landscape",
            ),
            (
                ["--publish", "--no-publish"],
                "--publish and --no-publish cannot be combined",
            ),
        )
        for arguments, expected_error in cases:
            with self.subTest(arguments=arguments):
                with tempfile.TemporaryDirectory() as directory:
                    result, client, state, output = self.invoke(
                        Path(directory),
                        arguments,
                    )

                    self.assertEqual(result.exit_code, 1, result.output)
                    self.assertIn(
                        "Generation failed during validation",
                        result.output,
                    )
                    self.assertIn(expected_error, result.output)
                    self.assertEqual(client.calls, [])
                    self.assertEqual(
                        [path.name for path in state.iterdir()],
                        ["active-configuration.toml"],
                    )
                    self.assertFalse(output.exists())

    def test_renderer_failure_names_stage_and_does_not_print_pdf_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failure = FixtureRenderer(RuntimeError("fixture compiler failed"))

            result, _, state, output = self.invoke(
                root,
                [],
                renderer=failure,
            )

            self.assertEqual(result.exit_code, 1, result.output)
            self.assertIn("Generation failed during rendering", result.output)
            self.assertIn("fixture compiler failed", result.output)
            self.assertEqual(list(output.iterdir()), [])
            self.assertEqual(
                [path.name for path in state.iterdir()],
                ["active-configuration.toml"],
            )


class CliRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def invoke(
        self,
        app,
        state: Path,
        output: Path,
        arguments: list[str],
    ):
        return self.runner.invoke(
            app,
            [
                "--state-directory",
                str(state),
                "--output-directory",
                str(output),
                "render",
                *arguments,
            ],
        )

    def test_default_source_rerenders_without_upstream_and_applies_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            output = root / "output"
            _write_configuration(state)
            client = FixtureClient()
            application = _generation_app(client)

            generated = self.runner.invoke(
                application,
                [
                    "--state-directory",
                    str(state),
                    "--output-directory",
                    str(output),
                    "generate",
                ],
            )
            self.assertEqual(generated.exit_code, 0, generated.output)
            source_pdf = Path(generated.output.strip())
            source_run_id = source_pdf.parent.name
            source_record = load_run_record(state, source_run_id)
            source_files = {
                path.relative_to(source_pdf.parent): path.read_bytes()
                for path in source_pdf.parent.rglob("*")
                if path.is_file()
            }
            configuration_path = state / "active-configuration.toml"
            configuration_path.write_text(
                configuration_path.read_text(encoding="utf-8")
                + "[layout]\nlandscape_starts_at = 2\n",
                encoding="utf-8",
            )
            configuration_before = configuration_path.read_bytes()
            client.calls.clear()

            with patch(
                "flickornas_standings.cli.generate_and_publish",
                side_effect=AssertionError("rerender started generation"),
            ):
                rendered = self.invoke(application, state, output, [])

            self.assertEqual(rendered.exit_code, 0, rendered.output)
            rendered_pdf = Path(rendered.output.strip())
            record = load_run_record(state, rendered_pdf.parent.name)
            self.assertEqual(record.kind, "render")
            self.assertEqual(record.source_run_id, source_run_id)
            self.assertEqual(record.layout, "landscape")
            self.assertEqual(source_record.layout, "portrait")
            self.assertEqual(client.calls, [])
            self.assertEqual(
                configuration_path.read_bytes(),
                configuration_before,
            )
            self.assertEqual(
                source_files,
                {
                    path.relative_to(source_pdf.parent): path.read_bytes()
                    for path in source_pdf.parent.rglob("*")
                    if path.is_file()
                },
            )
            self.assertEqual(
                (output / PUBLISHED_PDF_LINK).resolve(),
                source_pdf,
            )

    def test_explicit_partial_source_preserves_naming_and_publishes_only_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            output = root / "output"
            _write_configuration(state)
            client = FixtureClient()
            application = _generation_app(client)
            prefix = [
                "--state-directory",
                str(state),
                "--output-directory",
                str(output),
            ]

            full = self.runner.invoke(application, [*prefix, "generate"])
            self.assertEqual(full.exit_code, 0, full.output)
            json_target = os.readlink(output / PUBLIC_JSON_LINK)
            partial = self.runner.invoke(
                application,
                [*prefix, "generate", "--tournament", "11"],
            )
            self.assertEqual(partial.exit_code, 0, partial.output)
            partial_run_id = Path(partial.output.strip()).parent.name
            client.calls.clear()

            rendered = self.invoke(
                application,
                state,
                output,
                [
                    "--from-run",
                    partial_run_id,
                    "--layout",
                    "landscape",
                    "--publish",
                ],
            )

            self.assertEqual(rendered.exit_code, 0, rendered.output)
            rendered_pdf = Path(rendered.output.strip())
            record = load_run_record(state, rendered_pdf.parent.name)
            self.assertRegex(
                rendered_pdf.name,
                r"^flickornas-standings-partial-\d{8}T\d{6}Z\.pdf$",
            )
            self.assertEqual(record.source_run_id, partial_run_id)
            self.assertEqual(record.layout, "landscape")
            self.assertEqual(client.calls, [])
            self.assertEqual(
                (output / PUBLISHED_PDF_LINK).resolve(),
                rendered_pdf,
            )
            self.assertEqual(
                os.readlink(output / PUBLIC_JSON_LINK),
                json_target,
            )

    def test_absent_default_source_generates_unpublished_full_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            output = root / "output"
            _write_configuration(state)
            client = FixtureClient()
            application = _generation_app(client)

            rendered = self.invoke(application, state, output, [])

            self.assertEqual(rendered.exit_code, 0, rendered.output)
            rendered_pdf = Path(rendered.output.strip())
            rendered_record = load_run_record(state, rendered_pdf.parent.name)
            source_record = load_run_record(
                state,
                rendered_record.source_run_id,
            )
            self.assertEqual(rendered_record.kind, "render")
            self.assertEqual(source_record.kind, "full")
            self.assertTrue(client.calls)
            self.assertEqual(len(list((state / "runs").glob("*.json"))), 2)
            self.assertFalse((output / PUBLISHED_PDF_LINK).exists())
            self.assertFalse((output / PUBLIC_JSON_LINK).exists())

    def test_invalid_explicit_source_never_falls_back_to_generation(self):
        for source_run_id in ("missing", "../invalid", ""):
            with self.subTest(source_run_id=source_run_id):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    state = root / "state"
                    output = root / "output"
                    _write_configuration(state)
                    client = FixtureClient()

                    result = self.invoke(
                        _generation_app(client),
                        state,
                        output,
                        ["--from-run", source_run_id],
                    )

                    self.assertEqual(result.exit_code, 1, result.output)
                    self.assertIn(
                        "Generation failed during rendering",
                        result.output,
                    )
                    self.assertEqual(client.calls, [])
                    self.assertFalse(output.exists())
                    self.assertEqual(
                        [path.name for path in state.iterdir()],
                        ["active-configuration.toml"],
                    )

    def test_invalid_layout_fails_before_default_source_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            output = root / "output"
            _write_configuration(state)
            client = FixtureClient()

            result = self.invoke(
                _generation_app(client),
                state,
                output,
                ["--layout", "square"],
            )

            self.assertEqual(result.exit_code, 1, result.output)
            self.assertIn("Generation failed during validation", result.output)
            self.assertIn(
                "layout must be auto, portrait, or landscape",
                result.output,
            )
            self.assertEqual(client.calls, [])
            self.assertFalse(output.exists())


class CliCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def invoke(self, state: Path, output: Path):
        return self.runner.invoke(
            app,
            [
                "--state-directory",
                str(state),
                "--output-directory",
                str(output),
                "clear-downloads",
            ],
        )

    def test_clear_downloads_reports_and_marks_retained_runs_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            output = root / "output"
            _write_configuration(state)
            application = _generation_app(FixtureClient())
            prefix = [
                "--state-directory",
                str(state),
                "--output-directory",
                str(output),
            ]
            full = self.runner.invoke(application, [*prefix, "generate"])
            partial = self.runner.invoke(
                application,
                [*prefix, "generate", "--tournament", "11"],
            )
            self.assertEqual(full.exit_code, 0, full.output)
            self.assertEqual(partial.exit_code, 0, partial.output)
            run_ids = (
                Path(full.output.strip()).parent.name,
                Path(partial.output.strip()).parent.name,
            )

            result = self.invoke(state, output)

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn(
                "marked 2 retained run records unavailable",
                result.output,
            )
            for run_id in run_ids:
                self.assertFalse(
                    load_run_record(state, run_id).artifacts_available
                )
            self.assertFalse((output / "runs").exists())
            self.assertFalse((state / "rendering-projections").exists())
            self.assertFalse((output / PUBLISHED_PDF_LINK).exists())
            self.assertFalse((output / PUBLIC_JSON_LINK).exists())
            self.assertTrue(
                (state / "active-configuration.toml").is_file()
            )

    def test_repeated_clear_is_safe_and_reports_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            output = root / "output"

            first = self.invoke(state, output)
            second = self.invoke(state, output)

            self.assertEqual(first.exit_code, 0, first.output)
            self.assertEqual(second.exit_code, 0, second.output)
            self.assertIn(
                "marked 0 retained run records unavailable",
                first.output,
            )
            self.assertIn(
                "marked 0 retained run records unavailable",
                second.output,
            )
            self.assertFalse(state.exists())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
