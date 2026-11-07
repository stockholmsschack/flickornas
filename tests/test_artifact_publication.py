from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from flickornas_standings.active_configuration import ActiveConfiguration, LayoutConfiguration
from flickornas_standings.artifact_publication import (
    DEFAULT_TYPST_ASSETS,
    PUBLISHED_PDF_LINK,
    PUBLIC_JSON_LINK,
    TypstRenderer,
    clear_downloads,
    generate_and_publish,
    publish_generation,
    read_public_snapshot,
    read_published_pdf,
    render_run,
)
from flickornas_standings.generation_core import (
    DIAGNOSTIC_FILENAMES,
    GeneratedArtifacts,
    GenerationResult,
    RenderingProjection,
    render_projection_to_typst,
    resolve_layout,
    resolve_side_margin,
)
from flickornas_standings.generation_orchestrator import (
    GenerationInputs,
    GenerationStageError,
)
from tests.test_generation_orchestrator import FixtureClient
from flickornas_standings.run_state import load_rendering_projection, load_run_record


MINIMAL_TYPST = """
#import "lib.typ": stylish_table
#set text(font: "Roboto")
#image("stsf.png", width: 1cm)
Flickornas Ställning
"""


class FakeRenderer:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls = []

    def render(
        self,
        source: Path,
        destination: Path,
        *,
        root: Path,
        font_directory: Path,
    ) -> None:
        self.calls.append((source, destination, root, font_directory))
        if self.failure:
            raise self.failure
        destination.write_bytes(b"%PDF-1.7\nfixture\n")


def _result(typst_source: str = MINIMAL_TYPST) -> GenerationResult:
    reports: Mapping[str, str] = {
        filename: f"{filename}\n" for filename in DIAGNOSTIC_FILENAMES
    }
    return GenerationResult(
        standings=Mock(),
        rendering_projection=RenderingProjection(
            effective_year=2026,
            tournament_ids=("11", "22"),
            tournament_names=("One", "Two"),
            rows=(
                {
                    "Placering": 1,
                    "Född": 2012,
                    "Namn": "Fixture Player",
                    "Klubb": "Fixture Club",
                    "1": 25,
                    "2": 18,
                    "Σ": 43,
                    "played": 2,
                },
            ),
            contributor_name="Fixture",
            contributor_email="fixture@example.com",
        ),
        artifacts=GeneratedArtifacts(
            validation_workbook=b"validation",
            standings_workbook=b"standings",
            typst_source=typst_source,
            standings_json="[]\n",
            diagnostic_reports=reports,
        ),
    )


def _configuration() -> ActiveConfiguration:
    return ActiveConfiguration(
        default_tournament_ids=(11, 22),
        contributor={"name": "Fixture", "email": "fixture@example.com"},
    )


def _inputs() -> GenerationInputs:
    return GenerationInputs(effective_year=2026, tournament_ids=(11, 22))


class ArtifactPublicationTests(unittest.TestCase):
    def test_clear_downloads_preserves_configuration_and_run_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "downloads"
            state = root / "state"
            configuration = state / "active-configuration.toml"
            configuration.parent.mkdir()
            configuration.write_text("default_tournament_ids = [11, 22]\n")
            full = publish_generation(
                _result(),
                output,
                state_directory=state,
                run_id="full",
                renderer=FakeRenderer(),
            )
            publish_generation(
                _result(),
                output,
                state_directory=state,
                partial=True,
                run_id="partial",
                renderer=FakeRenderer(),
            )

            self.assertEqual(read_public_snapshot(output), b"[]\n")
            self.assertEqual(read_published_pdf(output), full.pdf_path.read_bytes())

            self.assertEqual(clear_downloads(output, state), 2)

            self.assertEqual(
                configuration.read_text(),
                "default_tournament_ids = [11, 22]\n",
            )
            self.assertFalse((output / "runs").exists())
            self.assertFalse((state / "rendering-projections").exists())
            self.assertFalse((output / PUBLISHED_PDF_LINK).is_symlink())
            self.assertFalse((output / PUBLIC_JSON_LINK).is_symlink())
            self.assertIsNone(read_public_snapshot(output))
            self.assertIsNone(read_published_pdf(output))
            for run_id in ("full", "partial"):
                self.assertFalse(
                    load_run_record(state, run_id).artifacts_available
                )
                self.assertTrue((state / "runs" / f"{run_id}.json").is_file())
                with self.assertRaises(FileNotFoundError):
                    load_rendering_projection(state, run_id)

    def test_clear_downloads_is_idempotent_and_preserves_unrelated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "downloads"
            state = root / "state"
            output.mkdir()
            unrelated = output / "operator-note.txt"
            unrelated.write_text("keep")

            self.assertEqual(clear_downloads(output, state), 0)
            self.assertEqual(clear_downloads(output, state), 0)
            self.assertEqual(unrelated.read_text(), "keep")

    def test_public_reads_treat_missing_and_stale_references_as_not_found(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)

            self.assertIsNone(read_public_snapshot(output))
            self.assertIsNone(read_published_pdf(output))
            os.symlink("runs/missing/standings.json", output / PUBLIC_JSON_LINK)
            os.symlink("runs/missing/standings.pdf", output / PUBLISHED_PDF_LINK)
            self.assertIsNone(read_public_snapshot(output))
            self.assertIsNone(read_published_pdf(output))

    def test_cleared_run_cannot_be_rendered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "downloads"
            state = root / "state"
            publish_generation(
                _result(),
                output,
                state_directory=state,
                run_id="source",
                renderer=FakeRenderer(),
            )
            clear_downloads(output, state)

            with self.assertRaisesRegex(
                GenerationStageError,
                "source run 'source' artifacts are unavailable",
            ):
                render_run(
                    "source",
                    _configuration(),
                    state,
                    output,
                    renderer=FakeRenderer(),
                )

    def test_progress_reports_each_pipeline_operation_in_order(self):
        progress = Mock()
        with tempfile.TemporaryDirectory() as directory:
            generate_and_publish(
                _configuration(),
                _inputs(),
                FixtureClient(),
                Path(directory) / "downloads",
                run_id="progress",
                renderer=FakeRenderer(),
                progress=progress,
            )

        self.assertEqual(
            progress.method_calls,
            [
                call.start("Validating configuration"),
                call.complete(),
                call.begin_phase(
                    "Fetching tournaments",
                    2,
                    "tournaments",
                ),
                call.start("Resolving tournament 11"),
                call.start("Resolving tournament 22"),
                call.start("Fetching district players and clubs"),
                call.start("Fetching tournament 1/2: Tournament 11"),
                call.complete(),
                call.start("Fetching tournament 2/2: Tournament 22"),
                call.complete(),
                call.begin_phase("Processing results", 5, "steps"),
                call.start("Calculating standings"),
                call.complete(),
                call.start("Producing output artifacts"),
                call.complete(),
                call.start("Staging artifacts"),
                call.complete(),
                call.start("Rendering PDF"),
                call.complete(),
                call.start("Publishing generation"),
                call.complete(),
            ],
        )

    def test_one_action_generates_pdf_and_every_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "downloads"

            published = generate_and_publish(
                _configuration(),
                _inputs(),
                FixtureClient(),
                output,
                run_id="fixture-run",
                renderer=FakeRenderer(),
            )

            self.assertEqual(published.run_id, "fixture-run")
            self.assertEqual(
                (output / PUBLISHED_PDF_LINK).resolve(),
                published.pdf_path.resolve(),
            )
            self.assertEqual(
                (output / PUBLIC_JSON_LINK).resolve(),
                (published.run_directory / "standings.json").resolve(),
            )
            timestamp = published.pdf_path.stem.removeprefix("flickornas-standings-")
            self.assertRegex(timestamp, r"^\d{8}T\d{6}Z$")
            expected = {
                f"validation-{timestamp}.xlsx",
                f"standings-{timestamp}.xlsx",
                "standings.typ",
                f"flickornas-standings-{timestamp}.pdf",
                "standings.json",
                "lib.typ",
                "rules.typ",
                "stsf.png",
                "fonts",
                "diagnostics",
            }
            self.assertEqual(
                {path.name for path in published.run_directory.iterdir()},
                expected,
            )
            self.assertEqual(
                {
                    path.name
                    for path in (
                        published.run_directory / "diagnostics"
                    ).iterdir()
                },
                set(DIAGNOSTIC_FILENAMES),
            )
            record = load_run_record(
                Path(directory) / "state",
                "fixture-run",
            )
            self.assertEqual(record.kind, "full")
            self.assertEqual(record.effective_year, 2026)
            self.assertEqual(record.tournament_ids, (11, 22))
            self.assertEqual(record.layout, "portrait")
            self.assertEqual(record.outcome, "succeeded")
            self.assertTrue(record.artifacts_available)
            projection = load_rendering_projection(
                Path(directory) / "state",
                "fixture-run",
            )
            self.assertEqual(projection.tournament_ids, ("11", "22"))

    def test_partial_run_suffixes_every_user_facing_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "downloads"
            inputs = GenerationInputs(
                effective_year=2026,
                tournament_ids=(11,),
                is_partial=True,
            )

            published = generate_and_publish(
                _configuration(),
                inputs,
                FixtureClient(),
                output,
                run_id="partial",
                renderer=FakeRenderer(),
            )

            match = re.fullmatch(
                r"flickornas-standings-partial-(\d{8}T\d{6}Z)\.pdf",
                published.pdf_path.name,
            )
            self.assertIsNotNone(match)
            timestamp = match.group(1)
            self.assertEqual(
                {path.name for path in published.run_directory.iterdir()},
                {
                    f"validation-partial-{timestamp}.xlsx",
                    f"standings-partial-{timestamp}.xlsx",
                    "standings-partial.typ",
                    f"flickornas-standings-partial-{timestamp}.pdf",
                    "standings-partial.json",
                    "lib.typ",
                    "rules.typ",
                    "stsf.png",
                    "fonts",
                    "diagnostics",
                },
            )
            self.assertEqual(
                {
                    path.name
                    for path in (
                        published.run_directory / "diagnostics"
                    ).iterdir()
                },
                {
                    filename.replace(".txt", "-partial.txt")
                    for filename in DIAGNOSTIC_FILENAMES
                },
            )
            self.assertEqual(
                published.result.standings.tournament_ids,
                ("11",),
            )
            self.assertFalse((output / PUBLISHED_PDF_LINK).exists())
            self.assertFalse((output / PUBLIC_JSON_LINK).exists())
            self.assertEqual(
                load_run_record(
                    Path(directory) / "state",
                    "partial",
                ).kind,
                "partial",
            )

    def test_partial_publication_advances_only_pdf_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "downloads"
            full = publish_generation(
                _result(),
                output,
                run_id="full",
                renderer=FakeRenderer(),
            )
            original_json_target = os.readlink(output / PUBLIC_JSON_LINK)
            partial = publish_generation(
                _result(),
                output,
                partial=True,
                publish=True,
                run_id="partial",
                renderer=FakeRenderer(),
            )

            self.assertEqual(
                (output / PUBLISHED_PDF_LINK).resolve(),
                partial.pdf_path.resolve(),
            )
            self.assertEqual(
                os.readlink(output / PUBLIC_JSON_LINK),
                original_json_target,
            )
            self.assertEqual(
                (output / PUBLIC_JSON_LINK).resolve(),
                (full.run_directory / "standings.json").resolve(),
            )

    def test_full_generation_can_suppress_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "downloads"
            publish_generation(
                _result(),
                output,
                publish=False,
                run_id="preview",
                renderer=FakeRenderer(),
            )

            self.assertFalse((output / PUBLISHED_PDF_LINK).exists())
            self.assertFalse((output / PUBLIC_JSON_LINK).exists())

    def test_render_uses_projection_without_changing_source_or_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "downloads"
            state = root / "state"
            source = publish_generation(
                _result(),
                output,
                state_directory=state,
                run_id="source",
                renderer=FakeRenderer(),
            )
            source_before = {
                path.relative_to(source.run_directory): path.read_bytes()
                for path in source.run_directory.rglob("*")
                if path.is_file()
            }
            json_target = os.readlink(output / PUBLIC_JSON_LINK)
            configuration = ActiveConfiguration(
                default_tournament_ids=(11, 22),
                contributor={
                    "name": "Changed",
                    "email": "changed@example.com",
                },
                club_display_names={"Fixture Club": "Short Club"},
            )

            rendered = render_run(
                "source",
                configuration,
                state,
                output,
                layout="landscape",
                publish=True,
                run_id="render",
                renderer=FakeRenderer(),
            )

            self.assertIsNone(rendered.result)
            self.assertEqual(rendered.record.kind, "render")
            self.assertEqual(rendered.record.source_run_id, "source")
            self.assertEqual(rendered.record.layout, "landscape")
            self.assertEqual(
                os.readlink(output / PUBLIC_JSON_LINK),
                json_target,
            )
            self.assertIn(
                "Short Club",
                (rendered.run_directory / "standings.typ").read_text(),
            )
            self.assertEqual(
                source_before,
                {
                    path.relative_to(source.run_directory): path.read_bytes()
                    for path in source.run_directory.rglob("*")
                    if path.is_file()
                },
            )

    def test_presentation_policy_and_typst_escaping_are_explicit(self):
        projection = _result().rendering_projection
        special = RenderingProjection(
            **{
                **projection.__dict__,
                "tournament_names": ("Cup #1 [final]", "Two"),
                "rows": (
                    {
                        **projection.rows[0],
                        "Namn": (
                            "A_very *long* [name] #1 that must wrap without "
                            "discarding any text"
                        ),
                        "Klubb": "Canonical Club With A Very Long Name",
                    },
                ),
            }
        )
        layout = LayoutConfiguration(
            landscape_starts_at=2,
            base_side_margin_cm=0.8,
            margin_reduction_starts_after=0,
            margin_reduction_per_tournament_cm=0.2,
            minimum_side_margin_cm=0.5,
        )

        source = render_projection_to_typst(
            special,
            layout_configuration=layout,
            club_display_names={
                "Canonical Club With A Very Long Name":
                    "Club [With A Very Long Display Name]",
            },
        )

        self.assertIn('paper: "a4", flipped: true', source)
        self.assertIn("top: 0.8cm, bottom: 0.8cm, x: 0.5cm", source)
        self.assertIn("#standings_heading([Flickornas Ställning])", source)
        heading_library = (Path(__file__).resolve().parents[1] / "typst" / "lib.typ").read_text()
        self.assertIn("#datetime.today()", heading_library)
        self.assertIn("Utskrift gäller", heading_library)
        self.assertIn(r"A\_very \*long\* \[name\] \#1", source)
        self.assertIn(r"Club \[With A Very Long Display Name\]", source)
        self.assertIn(r"Cup \#1 \[final\]", source)
        self.assertIn(
            "columns: (auto, 1fr, 1fr, 1fr",
            source,
        )
        self.assertEqual(resolve_layout("portrait", 20, layout), "portrait")
        self.assertEqual(resolve_side_margin(20, layout), 0.5)

    @unittest.skipUnless(shutil.which("typst"), "Typst is not installed")
    def test_typst_significant_values_compile_literally(self):
        base = _result()
        projection = replace(
            base.rendering_projection,
            tournament_names=("Cup #1 [final]", "Two"),
            rows=(
                {
                    **base.rendering_projection.rows[0],
                    "Namn": "Player_#1 [A] *literal*",
                    "Klubb": "Club [North] #1",
                },
            ),
        )
        source = render_projection_to_typst(projection)
        result = replace(
            base,
            rendering_projection=projection,
            artifacts=replace(base.artifacts, typst_source=source),
        )

        with tempfile.TemporaryDirectory() as directory:
            published = publish_generation(
                result,
                Path(directory) / "downloads",
                publish=False,
                run_id="escaped",
            )

            self.assertTrue(published.pdf_path.read_bytes().startswith(b"%PDF"))

    @unittest.skipUnless(shutil.which("typst"), "Typst is not installed")
    def test_real_renderer_produces_pdf_from_bundled_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            published = publish_generation(
                _result(),
                Path(directory) / "downloads",
                run_id="rendered",
            )

            self.assertTrue(
                published.pdf_path.read_bytes().startswith(b"%PDF")
            )

    def test_typst_command_ignores_system_fonts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "standings.typ"
            destination = root / "standings.pdf"
            fonts = root / "fonts"
            source.write_text("Hello")
            fonts.mkdir()

            def complete(command, **_kwargs):
                destination.write_bytes(b"%PDF")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch(
                "flickornas_standings.artifact_publication.subprocess.run",
                side_effect=complete,
            ) as run:
                TypstRenderer().render(
                    source,
                    destination,
                    root=root,
                    font_directory=fonts,
                )

            command = run.call_args.args[0]
            self.assertIn("--ignore-system-fonts", command)
            font_index = command.index("--font-path")
            self.assertEqual(command[font_index + 1], str(fonts))

    def test_read_only_asset_tree_is_not_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "readonly-assets"
            shutil.copytree(DEFAULT_TYPST_ASSETS, assets)
            before = {
                path.relative_to(assets): path.read_bytes()
                for path in assets.rglob("*")
                if path.is_file()
            }
            for path in assets.rglob("*"):
                path.chmod(0o444 if path.is_file() else 0o555)
            assets.chmod(0o555)

            try:
                publish_generation(
                    _result(),
                    root / "downloads",
                    run_id="readonly",
                    typst_assets=assets,
                    renderer=FakeRenderer(),
                )

                after = {
                    path.relative_to(assets): path.read_bytes()
                    for path in assets.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(after, before)
            finally:
                assets.chmod(0o755)
                for path in assets.rglob("*"):
                    path.chmod(0o644 if path.is_file() else 0o755)

    def test_render_failure_leaves_previous_snapshot_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "downloads"
            first = publish_generation(
                _result(),
                output,
                run_id="first",
                renderer=FakeRenderer(),
            )

            with self.assertRaisesRegex(
                GenerationStageError,
                "during rendering: renderer failed",
            ):
                publish_generation(
                    _result(),
                    output,
                    run_id="second",
                    renderer=FakeRenderer(RuntimeError("renderer failed")),
                )

            self.assertEqual(
                (output / PUBLISHED_PDF_LINK).resolve(),
                first.pdf_path.resolve(),
            )
            self.assertFalse((output / "runs" / "second").exists())
            self.assertFalse(
                any(path.name.startswith(".second-") for path in output.iterdir())
            )

    def test_commit_failure_rolls_back_run_and_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "downloads"
            first = publish_generation(
                _result(),
                output,
                run_id="first",
                renderer=FakeRenderer(),
            )
            real_replace = os.replace
            replacements = 0

            def fail_snapshot_replace(source, destination):
                nonlocal replacements
                replacements += 1
                if replacements == 2:
                    raise OSError("snapshot unavailable")
                return real_replace(source, destination)

            with (
                patch(
                    "flickornas_standings.artifact_publication.os.replace",
                    side_effect=fail_snapshot_replace,
                ),
                self.assertRaisesRegex(
                    GenerationStageError,
                    "during committing: snapshot unavailable",
                ),
            ):
                publish_generation(
                    _result(),
                    output,
                    run_id="second",
                    renderer=FakeRenderer(),
                )

            self.assertEqual(
                (output / PUBLISHED_PDF_LINK).resolve(),
                first.pdf_path.resolve(),
            )
            self.assertFalse((output / "runs" / "second").exists())

    def test_staging_failure_leaves_no_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "downloads"

            with self.assertRaisesRegex(
                GenerationStageError,
                "during artifact staging: missing bundled Typst asset",
            ):
                publish_generation(
                    _result(),
                    output,
                    run_id="broken",
                    typst_assets=root / "missing",
                    renderer=FakeRenderer(),
                )

            self.assertEqual(list(output.iterdir()), [])

    def test_validation_failure_does_not_create_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "downloads"
            invalid = ActiveConfiguration(
                default_tournament_ids=(),
                contributor={},
            )
            invalid_inputs = GenerationInputs(
                effective_year=26,
                tournament_ids=(),
            )

            with self.assertRaises(GenerationStageError):
                generate_and_publish(
                    invalid,
                    invalid_inputs,
                    FixtureClient(),
                    output,
                    renderer=FakeRenderer(),
                )

            self.assertFalse(output.exists())

    def test_prepublication_stage_failures_leave_no_output(self):
        for stage in ("fetching", "calculation", "artifact production"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "downloads"
                failure = GenerationStageError(stage, "fixture failure")

                with (
                    patch(
                        "flickornas_standings.artifact_publication.run_generation",
                        side_effect=failure,
                    ),
                    self.assertRaisesRegex(
                        GenerationStageError,
                        f"during {stage}: fixture failure",
                    ),
                ):
                    generate_and_publish(
                        _configuration(),
                        _inputs(),
                        FixtureClient(),
                        output,
                        renderer=FakeRenderer(),
                    )

                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
