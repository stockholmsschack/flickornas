from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from flickornas_standings.active_configuration import (
    ActiveConfiguration,
    load_configuration,
    save_configuration,
)
from flickornas_standings.web import create_app
from flickornas_standings.web.available_files import (
    list_available_files,
    list_report_files,
)


class AvailableFilesTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output_directory = Path(self.temporary_directory.name) / "output"
        self.download_root = self.output_directory / "runs"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_downloads_include_only_the_three_operator_deliverables(self):
        generation = self.download_root / "20260801T120000Z-example"
        diagnostics = generation / "diagnostics"
        fonts = generation / "fonts"
        diagnostics.mkdir(parents=True)
        fonts.mkdir()
        for path in (
            generation / "flickornas-standings-20260801T120000Z.pdf",
            generation / "standings-20260801T120000Z.xlsx",
            generation / "validation-20260801T120000Z.xlsx",
            generation / "standings.typ",
            generation / "standings.json",
            diagnostics / "walkovers.txt",
        ):
            path.write_text("fixture", encoding="utf-8")
        (generation / "rules.typ").write_text("support", encoding="utf-8")
        (fonts / "font.ttf").write_text("font", encoding="utf-8")

        available = list_available_files(self.output_directory)

        self.assertEqual(len(available), 3)
        self.assertEqual(
            {item.label_key for item in available},
            {
                "available_files.names.pdf",
                "available_files.names.standings_workbook",
                "available_files.names.validation_workbook",
            },
        )
        urls = " ".join(item.download_url for item in available)
        self.assertNotIn("standings.typ", urls)
        self.assertNotIn("standings.json", urls)
        self.assertNotIn("diagnostics", urls)
        self.assertNotIn("rules.typ", urls)
        self.assertNotIn("fonts", urls)
        self.assertTrue(
            all("20260801T120000Z" in item.download_url for item in available)
        )
        self.assertEqual(
            {item.generated_at.isoformat() for item in available},
            {"2026-08-01T14:00:00+02:00"},
        )

    def test_reports_include_data_and_diagnostics_but_not_typst(self):
        generation = self.download_root / "generated"
        diagnostics = generation / "diagnostics"
        diagnostics.mkdir(parents=True)
        for path in (
            generation / "standings.json",
            generation / "standings.typ",
            diagnostics / "walkovers.txt",
            diagnostics / "dropouts-partial.txt",
        ):
            path.write_text("fixture", encoding="utf-8")

        reports = list_report_files(self.output_directory)

        self.assertEqual(
            {item.label_key for item in reports},
            {
                "available_files.names.json",
                "available_files.names.walkovers",
                "available_files.names.dropouts",
            },
        )
        self.assertTrue(
            all(item.download_url.startswith("/reports/") for item in reports)
        )
        self.assertNotIn(
            "standings.typ",
            " ".join(item.download_url for item in reports),
        )
        self.assertTrue(
            next(
                item
                for item in reports
                if item.label_key == "available_files.names.dropouts"
            ).partial
        )

    def test_reports_page_is_separate_from_downloads(self):
        generation = self.download_root / "generated"
        diagnostics = generation / "diagnostics"
        diagnostics.mkdir(parents=True)
        (generation / "standings.pdf").write_bytes(b"%PDF")
        (generation / "standings.json").write_text("[]", encoding="utf-8")
        (generation / "standings.typ").write_text("source", encoding="utf-8")
        (diagnostics / "walkovers.txt").write_text("report", encoding="utf-8")

        app = create_app(
            {
                "TESTING": True,
                "OUTPUT_DIRECTORY": self.output_directory,
                "STATE_DIRECTORY": Path(self.temporary_directory.name) / "state",
            }
        )
        client = app.test_client()

        downloads = client.get("/downloads?lang=en").get_data(as_text=True)
        reports = client.get("/reports?lang=en").get_data(as_text=True)

        self.assertIn("Standings PDF", downloads)
        self.assertNotIn('href="/downloads/generated/standings.json"', downloads)
        self.assertNotIn('href="/downloads/generated/standings.typ"', downloads)
        self.assertIn("Standings data", reports)
        self.assertIn("Walkovers", reports)
        self.assertNotIn('href="/reports/generated/standings.pdf"', reports)
        self.assertNotIn('href="/reports/generated/standings.typ"', reports)
        self.assertIn(
            'href="http://flickornas.localhost:5000/reports/'
            'generated/standings.json"',
            reports,
        )

    def test_newest_files_come_first_and_partial_names_are_recognized(self):
        older = self.download_root / "older"
        newer = self.download_root / "newer"
        older.mkdir(parents=True)
        newer.mkdir()
        older_pdf = older / "standings.pdf"
        newer_pdf = newer / "standings-partial.pdf"
        older_pdf.write_bytes(b"older")
        newer_pdf.write_bytes(b"newer")
        os.utime(older_pdf, (100, 100))
        os.utime(newer_pdf, (200, 200))

        available = list_available_files(self.output_directory)

        self.assertEqual(
            [item.download_url for item in available],
            [
                "/downloads/newer/standings-partial.pdf",
                "/downloads/older/standings.pdf",
            ],
        )
        self.assertTrue(available[0].partial)
        self.assertFalse(available[1].partial)

    def test_url_segments_are_encoded_and_internal_name_is_not_a_label(self):
        generation = self.download_root / "mapp å"
        generation.mkdir(parents=True)
        (generation / "standings.pdf").write_bytes(b"pdf")

        available = list_available_files(self.output_directory)

        self.assertEqual(
            available[0].download_url,
            "/downloads/mapp%20%C3%A5/standings.pdf",
        )
        self.assertNotIn("mapp å", available[0].label_key)

    def test_symlink_cannot_escape_download_root(self):
        generation = self.download_root / "unsafe"
        generation.mkdir(parents=True)
        outside = Path(self.temporary_directory.name) / "standings.pdf"
        outside.write_bytes(b"private")
        (generation / "standings.pdf").symlink_to(outside)

        self.assertEqual(list_available_files(self.output_directory), ())

    def test_missing_download_directory_is_an_empty_collection(self):
        self.assertEqual(list_available_files(self.output_directory), ())

    def test_malformed_datetime_filename_is_not_listed(self):
        generation = self.download_root / "malformed"
        generation.mkdir(parents=True)
        (generation / "standings-20269999T999999Z.pdf").write_bytes(b"pdf")

        self.assertEqual(list_available_files(self.output_directory), ())


class ClearAvailableFilesTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.state_directory = self.root / "state"
        self.output_directory = self.root / "output"
        self.app = create_app(
            {
                "TESTING": True,
                "STATE_DIRECTORY": self.state_directory,
                "OUTPUT_DIRECTORY": self.output_directory,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _create_download(self) -> Path:
        download = self.output_directory / "runs" / "generated" / "standings.pdf"
        download.parent.mkdir(parents=True)
        download.write_bytes(b"%PDF-test")
        return download

    def test_page_protects_global_clear_with_localized_bootstrap_modal(self):
        self._create_download()

        english = self.client.get("/downloads?lang=en").get_data(as_text=True)
        swedish = self.client.get("/downloads?lang=sv").get_data(as_text=True)

        self.assertIn("Clear downloads", english)
        self.assertIn("Every available file will be removed.", english)
        self.assertIn("Your configuration will be retained.", english)
        self.assertIn("Rensa nedladdningar", swedish)
        self.assertIn("Din konfiguration behålls.", swedish)
        self.assertIn('class="modal"', english)
        self.assertIn('data-clear-endpoint="/api/v1/downloads/clear"', english)
        self.assertIn('src="/static/js/available-files.js"', english)

    def test_empty_page_does_not_offer_clear_action(self):
        body = self.client.get("/downloads?lang=en").get_data(as_text=True)

        self.assertIn("No files available.", body)
        self.assertNotIn("data-clear-open", body)

    def test_structured_clear_removes_downloads_and_preserves_configuration(self):
        configuration = save_configuration(
            self.state_directory,
            ActiveConfiguration(
                default_tournament_ids=(11,),
                contributor={"name": "Fixture", "email": "test@example.com"},
            ),
        )
        download = self._create_download()
        unrelated = self.output_directory / "operator-note.txt"
        unrelated.write_text("keep", encoding="utf-8")

        response = self.client.post(
            "/api/v1/downloads/clear",
            headers={"Accept": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"data": {"cleared": True, "retained_run_count": 0}},
        )
        self.assertFalse(download.exists())
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "keep")
        self.assertEqual(load_configuration(self.state_directory), configuration)

    def test_repeated_clear_is_safe(self):
        self._create_download()

        first = self.client.post("/api/v1/downloads/clear")
        second = self.client.post("/api/v1/downloads/clear")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()["data"]["cleared"])

    def test_clear_is_refused_while_generation_holds_the_lease(self):
        manager = self.app.extensions["flickornas"]["generation_operations"]
        manager.store.acquire("active-generation")
        try:
            response = self.client.post("/api/v1/downloads/clear")
        finally:
            manager.store.release("active-generation")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"]["code"], "downloads_busy")
        self.assertEqual(
            response.get_json()["error"]["message_key"],
            "errors.downloads.operation_busy",
        )

    def test_clear_script_guards_double_submit_and_recovers_from_failure(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "flickornas_standings"
            / "web"
            / "static"
            / "js"
            / "available-files.js"
        ).read_text(encoding="utf-8")

        self.assertIn("if (clearing)", source)
        self.assertIn("confirmButton.disabled = true", source)
        self.assertIn("confirmButton.disabled = false", source)
        self.assertIn('method: "POST"', source)
        self.assertIn('fileList.classList.add("d-none")', source)
        self.assertIn('emptyState.classList.remove("d-none")', source)
        self.assertNotIn("location.reload", source)

    def test_clear_browser_behavior(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is not installed")

        completed = subprocess.run(
            [node, "tests/browser/available-files.mjs"],
            cwd=Path(__file__).resolve().parents[1],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
