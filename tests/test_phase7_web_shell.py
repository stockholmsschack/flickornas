from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from flask import abort

from flickornas_standings.active_configuration import ActiveConfiguration, save_configuration
from flickornas_standings.web import create_app
from flickornas_standings.web.__main__ import main
from flickornas_standings.web.operations import (
    LAST_EVENT_ID_HEADER,
    OPERATION_EVENT_KINDS,
    OperationEvent,
)
from flickornas_standings.member_system_client import (
    CanonicalTournament,
    ProcessableTournamentGroup,
    TournamentGroupId,
    TournamentId,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "flickornas_standings" / "web"


def _configuration() -> ActiveConfiguration:
    return ActiveConfiguration(
        default_tournament_ids=(11, 22),
        contributor={
            "name": "Test Contributor",
            "email": "test@example.com",
        },
    )


class WebShellTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.state_directory = self.root / "state"
        self.output_directory = self.root / "output"
        self.member_system_client = Mock()
        self.member_system_client.canonical_tournament.side_effect = (
            lambda tournament_id: CanonicalTournament(
                tournament_id=TournamentId(tournament_id),
                name=f"Tournament {tournament_id}",
                start_date=date(2026, 1, tournament_id),
                end_date=date(2026, 1, tournament_id),
                processable_groups=(
                    ProcessableTournamentGroup(
                        group_id=TournamentGroupId(tournament_id + 100),
                        name="Flickor",
                        klass="F",
                    ),
                ),
            )
        )
        self.app = create_app(
            {
                "TESTING": True,
                "STATE_DIRECTORY": self.state_directory,
                "OUTPUT_DIRECTORY": self.output_directory,
                "MEMBER_SYSTEM_CLIENT": self.member_system_client,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_empty_page_shells_are_server_rendered_in_swedish(self):
        for path, expected in (
            ("/", "Översikt"),
            ("/configuration", "Konfiguration"),
            ("/downloads", "Inga filer är tillgängliga."),
            ("/reports", "Inga rapporter är tillgängliga."),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, response.get_data(as_text=True))
                self.assertIn('<html lang="sv">', response.get_data(as_text=True))

    def test_language_choice_is_persisted_and_shared_with_javascript(self):
        response = self.client.get("/?lang=en")
        body = response.get_data(as_text=True)

        self.assertIn('<html lang="en">', body)
        self.assertIn("Generate and manage Flickornas standings", body)
        self.assertIn('"nav.home": "Overview"', body)
        self.assertIn("flickornas_locale=en", response.headers["Set-Cookie"])
        # The switch offers the other language by its code and flag.
        self.assertIn('<input type="hidden" name="lang" value="sv">', body)
        self.assertIn('lang="sv"\n                    title="Svenska"', body)
        self.assertIn("images/flags/se.svg", body)

        persisted = self.client.get("/downloads")
        self.assertIn(
            "No files available.",
            persisted.get_data(as_text=True),
        )

    def test_configuration_editing_and_available_files_are_separate(self):
        saved = save_configuration(self.state_directory, _configuration())
        files = self.output_directory / "runs" / "internal-directory"
        files.mkdir(parents=True)
        (files / "standings.pdf").write_bytes(b"%PDF-test")

        configuration_response = self.client.get("/configuration?lang=en")
        configuration_body = configuration_response.get_data(as_text=True)
        self.assertNotIn(">Revision</dt>", configuration_body)
        self.assertIn(
            f'data-configuration-revision="{saved.revision}"',
            configuration_body,
        )
        self.assertIn("11, 22", configuration_body)
        self.assertIn("data-configuration-summary", configuration_body)
        for tab_id, panel_id in (
            ("tournament-addition-tab", "tournament-addition-panel"),
            ("player-addition-tab", "player-addition-panel"),
            ("contributor-tab", "contributor-panel"),
            ("club-display-names-tab", "club-display-names-panel"),
            ("rules-file-tab", "rules-file-panel"),
        ):
            with self.subTest(tab_id=tab_id):
                self.assertIn(
                    f'data-configuration-tab-link="{tab_id}"',
                    configuration_body,
                )
                self.assertIn(f'href="#{panel_id}"', configuration_body)
        self.assertIn(
            'src="/static/js/configuration-tab-navigation.js"',
            configuration_body,
        )
        self.assertNotIn("Save tournaments", configuration_body)
        self.assertNotIn("data-save-tournaments", configuration_body)
        self.assertIn(
            'data-save-endpoint="/api/v1/configuration/tournaments"',
            configuration_body,
        )

        files_response = self.client.get("/downloads?lang=en")
        files_body = files_response.get_data(as_text=True)
        self.assertIn("Standings PDF", files_body)
        self.assertIn("Download", files_body)
        self.assertNotIn(">internal-directory<", files_body)

        swedish_body = self.client.get(
            "/downloads?lang=sv"
        ).get_data(as_text=True)
        self.assertIn("Ställning som PDF", swedish_body)
        self.assertIn("Ladda ner", swedish_body)

    def test_legacy_runs_page_redirects_without_exposing_run_details(self):
        response = self.client.get("/runs?lang=en")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/downloads?lang=en")
        self.assertEqual(
            self.client.get("/runs/internal-directory/pdf").status_code,
            404,
        )

    def test_bootstrap_lit_and_application_assets_are_local(self):
        response = self.client.get("/")
        body = response.get_data(as_text=True)

        self.assertIn('href="/static/css/bootstrap.min.css"', body)
        self.assertIn('src="/static/js/bootstrap.bundle.min.js"', body)
        self.assertNotIn("cdn.", body.lower())
        self.assertNotIn("get_flashed_messages", body)

        for path in (
            "/static/css/bootstrap.min.css",
            "/static/js/bootstrap.bundle.min.js",
            "/static/js/lit-html.js",
            "/static/js/locale.js",
        ):
            with self.subTest(path=path):
                asset = self.client.get(path)
                try:
                    self.assertEqual(asset.status_code, 200)
                    self.assertGreater(len(asset.data), 20)
                finally:
                    asset.close()

    def test_web_package_has_no_portal_auth_or_flash_path(self):
        source_files = (
            list(WEB_ROOT.glob("*.py"))
            + list((WEB_ROOT / "templates").glob("*.jinja2"))
        )
        source = "\n".join(
            path.read_text(encoding="utf-8") for path in source_files
        )

        self.assertNotIn("get_flashed_messages", source)
        self.assertNotIn("flask_login", source)
        self.assertNotIn("REQUIRE_AUTH", source)
        self.assertNotIn("cdn.", source.lower())

    def test_api_errors_use_the_json_error_envelope(self):
        def missing():
            abort(404, "gone")

        self.app.view_functions["flickornas.district_clubs"] = missing
        response = self.client.get("/api/v1/clubs")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json(),
            {
                "error": {
                    "code": "http_404",
                    "message_key": "errors.http",
                    "details": {"description": "gone"},
                }
            },
        )

    def test_a_path_outside_flickornas_endpoints_keeps_flasks_html_error(self):
        for path in ("/not-found", "/api/v1/not-found"):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.mimetype, "text/html")

    def test_operation_event_contract_is_localizable_and_replayable(self):
        event = OperationEvent(
            event_id=3,
            operation_id="operation-1",
            kind="progress",
            message_key="operations.fetching",
            parameters={"tournament_id": 22},
            progress={"current": 1, "total": 2, "unit": "tournaments"},
        )

        event_lines = event.as_sse().splitlines()
        payload = json.loads(event_lines[2].removeprefix("data: "))
        self.assertEqual(event_lines[:2], ["id: 3", "event: progress"])
        self.assertEqual(payload["message_key"], "operations.fetching")
        self.assertFalse(payload["terminal"])
        self.assertEqual(
            OPERATION_EVENT_KINDS,
            ("accepted", "stage", "progress", "completed", "failed"),
        )
        self.assertEqual(LAST_EVENT_ID_HEADER, "Last-Event-ID")

    def test_standalone_entry_point_binds_to_loopback_by_default(self):
        application = Mock()
        with patch(
            "flickornas_standings.web.__main__.create_app",
            return_value=application,
        ):
            main([])

        application.run.assert_called_once_with(
            host="127.0.0.1",
            port=7001,
            debug=False,
        )

    def test_debug_entry_point_reloads_locale_catalogues(self):
        application = Mock()
        with patch(
            "flickornas_standings.web.__main__.create_app",
            return_value=application,
        ):
            main(["--debug"])

        run_options = application.run.call_args.kwargs
        self.assertTrue(run_options["debug"])
        self.assertEqual(
            {path.name for path in run_options["extra_files"]},
            {"en.json", "sv.json"},
        )


if __name__ == "__main__":
    unittest.main()
