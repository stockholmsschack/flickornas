from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from flickornas_standings.active_configuration import (
    ActiveConfiguration,
    DEFAULT_CONTRIBUTOR_EMAIL,
    DEFAULT_CONTRIBUTOR_NAME,
    load_configuration,
    save_configuration,
)
from flickornas_standings.web import create_app
from flickornas_standings.member_system_client import (
    CanonicalTournament,
    ProcessableTournamentGroup,
    TournamentGroupId,
    TournamentId,
)


class ContributorEditorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.state_directory = root / "state"
        self.saved = save_configuration(
            self.state_directory,
            ActiveConfiguration(
                default_tournament_ids=(100,),
                contributor={
                    "name": "Current feedback contact",
                    "email": "current@example.com",
                },
            ),
        )
        member_system_client = Mock()
        member_system_client.canonical_tournament.return_value = (
            CanonicalTournament(
                tournament_id=TournamentId(100),
                name="Tournament",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 1),
                processable_groups=(
                    ProcessableTournamentGroup(
                        group_id=TournamentGroupId(1000),
                        name="Flickor",
                        klass="F",
                    ),
                ),
            )
        )
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "contributor-editor-tests",
                "STATE_DIRECTORY": self.state_directory,
                "OUTPUT_DIRECTORY": root / "output",
                "MEMBER_SYSTEM_CLIENT": member_system_client,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_configuration_page_adds_localized_third_tab(self):
        english = self.client.get("/configuration?lang=en").get_data(
            as_text=True
        )
        swedish = self.client.get("/configuration?lang=sv").get_data(
            as_text=True
        )

        self.assertIn('id="contributor-tab"', english)
        self.assertIn('aria-selected="false"', english)
        self.assertIn('id="contributor-panel"', english)
        self.assertIn("Feedback contact", english)
        self.assertIn("Kontakt för synpunkter", swedish)
        for body in (english, swedish):
            self.assertIn(f'placeholder="{DEFAULT_CONTRIBUTOR_NAME}"', body)
            self.assertIn(f'placeholder="{DEFAULT_CONTRIBUTOR_EMAIL}"', body)
            self.assertIn('value="Current feedback contact"', body)
            self.assertIn('value="current@example.com"', body)
            self.assertIn("data-save-contributor", body)
            self.assertIn("data-clear-contributor-name", body)
            self.assertIn("data-clear-contributor-email", body)
            self.assertIn("justify-content-end", body)
            self.assertIn(
                'data-save-endpoint="/api/v1/configuration/contributor"',
                body,
            )
            self.assertIn(
                'src="/static/js/contributor-editor.js"',
                body,
            )

    def test_blank_values_save_and_return_swedish_defaults(self):
        response = self.client.post(
            "/api/v1/configuration/contributor",
            json={"revision": self.saved.revision, "name": " ", "email": ""},
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertTrue(data["changed"])
        self.assertEqual(
            data["contributor"],
            {
                "name": DEFAULT_CONTRIBUTOR_NAME,
                "email": DEFAULT_CONTRIBUTOR_EMAIL,
            },
        )
        self.assertEqual(
            dict(load_configuration(self.state_directory).contributor),
            data["contributor"],
        )

    def test_unchanged_values_do_not_advance_revision(self):
        response = self.client.post(
            "/api/v1/configuration/contributor",
            json={
                "revision": self.saved.revision,
                "name": " Current feedback contact ",
                "email": " current@example.com ",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["data"]["changed"])
        self.assertEqual(
            load_configuration(self.state_directory).revision,
            self.saved.revision,
        )

    def test_invalid_email_and_stale_revision_are_rejected(self):
        invalid = self.client.post(
            "/api/v1/configuration/contributor",
            json={
                "revision": self.saved.revision,
                "name": "Name",
                "email": "invalid",
            },
        )
        stale = self.client.post(
            "/api/v1/configuration/contributor",
            json={
                "revision": 0,
                "name": "Name",
                "email": "valid@example.com",
            },
        )

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(
            invalid.get_json()["error"]["code"],
            "invalid_input",
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(
            stale.get_json()["error"]["code"],
            "stale_configuration",
        )
        self.assertEqual(load_configuration(self.state_directory), self.saved)

    def test_editor_guards_pristine_invalid_and_submitting_states(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "flickornas_standings"
            / "web"
            / "static"
            / "js"
            / "contributor-editor.js"
        ).read_text(encoding="utf-8")

        self.assertIn("saving || !valid || !changed", source)
        self.assertIn("form.checkValidity()", source)
        self.assertIn("nameInput.value.trim() || defaults.name", source)
        self.assertIn("emailInput.value.trim() || defaults.email", source)
        self.assertIn("clearNameButton.disabled", source)
        self.assertIn("clearEmailButton.disabled", source)
        self.assertIn('new Event("input", { bubbles: true })', source)
        self.assertIn(
            '"flickornas:configuration-revision-changed"',
            source,
        )


if __name__ == "__main__":
    unittest.main()
