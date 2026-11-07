from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from flickornas_standings.active_configuration import (
    ActiveConfiguration,
    load_configuration,
    save_configuration,
)
from flickornas_standings.web import create_app
from flickornas_standings.member_system_client import CanonicalClub, ClubId, UpstreamRetryExhausted


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ClubDisplayNameEditorTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.state_directory = root / "state"
        self.saved = save_configuration(
            self.state_directory,
            ActiveConfiguration(
                default_tournament_ids=(100,),
                contributor={
                    "name": "Test Contributor",
                    "email": "test@example.com",
                },
                club_display_names={"Stockholms Schacksällskap": "SSS"},
            ),
        )
        self.member_system_client = Mock()
        self.member_system_client.canonical_tournament.side_effect = (
            UpstreamRetryExhausted("resolving tournament", "offline")
        )
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "club-display-name-tests",
                "STATE_DIRECTORY": self.state_directory,
                "OUTPUT_DIRECTORY": root / "output",
                "MEMBER_SYSTEM_CLIENT": self.member_system_client,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_configuration_page_adds_editor_tab_and_saved_aliases(self):
        response = self.client.get("/configuration?lang=en")
        body = response.get_data(as_text=True)

        self.assertIn('id="club-display-names-tab"', body)
        self.assertIn('aria-selected="false"', body)
        self.assertIn('id="club-display-names-panel"', body)
        self.assertIn("Shorten club names", body)
        self.assertLess(
            body.index("Add a shortened club name"),
            body.index("Shortened club names"),
        )
        self.assertIn(
            '"Stockholms Schacks\\u00e4llskap": "SSS"',
            body,
        )
        self.assertIn('data-club-display-name-selector', body)
        self.assertEqual(
            body.count('data-clubs-endpoint="/api/v1/clubs"'),
            2,
        )
        self.assertIn(
            'data-save-endpoint="/api/v1/configuration/club-display-names"',
            body,
        )
        self.assertIn(
            'src="/static/js/club-display-name-editor.js"',
            body,
        )

        swedish = self.client.get("/configuration?lang=sv").get_data(
            as_text=True
        )
        self.assertIn("Förkorta klubbnamn", swedish)

    def test_existing_alias_can_be_edited_without_club_lookup(self):
        response = self.client.post(
            "/api/v1/configuration/club-display-names",
            json={
                "revision": self.saved.revision,
                "action": "upsert",
                "canonical_name": "Stockholms Schacksällskap",
                "display_name": "Stockholms SS",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["data"]["changed"])
        self.assertEqual(
            load_configuration(self.state_directory).club_display_names,
            {"Stockholms Schacksällskap": "Stockholms SS"},
        )
        self.member_system_client.district_clubs.assert_not_called()

    def test_alias_can_be_removed_without_club_lookup(self):
        response = self.client.post(
            "/api/v1/configuration/club-display-names",
            json={
                "revision": self.saved.revision,
                "action": "remove",
                "canonical_name": "Stockholms Schacksällskap",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["data"]["club_display_names"],
            {},
        )
        self.assertEqual(
            load_configuration(self.state_directory).club_display_names,
            {},
        )
        self.member_system_client.district_clubs.assert_not_called()

    def test_new_alias_is_verified_against_stockholm_clubs(self):
        self.member_system_client.district_clubs.return_value = [
            CanonicalClub(ClubId(10), "Wasa SK"),
        ]

        response = self.client.post(
            "/api/v1/configuration/club-display-names",
            json={
                "revision": self.saved.revision,
                "action": "upsert",
                "canonical_name": "Wasa SK",
                "display_name": "Wasa",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["data"]["club_display_names"],
            {
                "Stockholms Schacksällskap": "SSS",
                "Wasa SK": "Wasa",
            },
        )
        self.member_system_client.district_clubs.assert_called_once_with(5821)

    def test_two_adds_reuse_the_club_list_loaded_for_the_selector(self):
        self.member_system_client.district_clubs.return_value = [
            CanonicalClub(ClubId(10), "Wasa SK"),
            CanonicalClub(ClubId(20), "Farsta SK"),
        ]
        club_response = self.client.get("/api/v1/clubs")
        selected_clubs = club_response.get_json()["data"]["clubs"]

        first = self.client.post(
            "/api/v1/configuration/club-display-names",
            json={
                "revision": self.saved.revision,
                "action": "upsert",
                "canonical_name": selected_clubs[0]["name"],
                "display_name": "Wasa",
            },
        )
        second = self.client.post(
            "/api/v1/configuration/club-display-names",
            json={
                "revision": first.get_json()["data"]["revision"],
                "action": "upsert",
                "canonical_name": selected_clubs[1]["name"],
                "display_name": "Farsta",
            },
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.member_system_client.district_clubs.assert_called_once_with(5821)

    def test_invalid_new_club_and_stale_revision_are_rejected(self):
        self.member_system_client.district_clubs.return_value = [
            CanonicalClub(ClubId(10), "Wasa SK"),
        ]
        invalid = self.client.post(
            "/api/v1/configuration/club-display-names",
            json={
                "revision": self.saved.revision,
                "action": "upsert",
                "canonical_name": "Invented Club",
                "display_name": "Invented",
            },
        )
        stale = self.client.post(
            "/api/v1/configuration/club-display-names",
            json={
                "revision": 0,
                "action": "remove",
                "canonical_name": "Stockholms Schacksällskap",
            },
        )

        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(
            invalid.get_json()["error"]["code"],
            "noncanonical_club",
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(
            load_configuration(self.state_directory),
            self.saved,
        )

    def test_editor_guards_actions_and_reuses_club_request(self):
        editor_source = (
            PROJECT_ROOT
            / "flickornas_standings/web/static/js/club-display-name-editor.js"
        ).read_text(encoding="utf-8")
        selector_source = (
            PROJECT_ROOT / "flickornas_standings/web/static/js/club-selector.js"
        ).read_text(encoding="utf-8")

        self.assertIn("mountClubSelector", editor_source)
        self.assertIn("loadClubs(root.dataset.clubsEndpoint)", editor_source)
        self.assertIn("editingCanonicalName", editor_source)
        self.assertIn("data-edited-club-display-name", editor_source)
        self.assertIn("operation === null", editor_source)
        self.assertIn("club_display_names.short_name_required", editor_source)
        self.assertIn("club_display_names.already_configured", editor_source)
        self.assertIn("newDisplayName.focus()", editor_source)
        self.assertIn("const clubLoads = new Map();", selector_source)
        self.assertIn("clubLoads.has(endpoint)", selector_source)
        self.assertIn('club_selection.clear_label', selector_source)
        self.assertIn('class="club-search-results', selector_source)

        node = shutil.which("node")
        if node is None:
            return
        completed = subprocess.run(
            [node, "--check", "flickornas_standings/web/static/js/club-display-name-editor.js"],
            cwd=PROJECT_ROOT,
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
