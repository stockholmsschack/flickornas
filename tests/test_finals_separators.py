from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import polars as pl

from flickornas_standings.active_configuration import (
    ActiveConfiguration,
    ConfigurationValidationError,
    load_configuration,
    save_configuration,
    validate_active_configuration,
)
from flickornas_standings.web import create_app
from flickornas_standings.generation_core import _polars_to_typst
from flickornas_standings.member_system_client import (
    CanonicalTournament,
    ProcessableTournamentGroup,
    TournamentGroupId,
    TournamentId,
)

HLINE = "  table.hline(stroke: 1pt + black),"


class FinalsSeparatorConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.state_directory = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_separators_round_trip_and_default_to_none(self):
        saved = save_configuration(
            self.state_directory,
            ActiveConfiguration(
                default_tournament_ids=(100,),
                contributor={"name": "Name", "email": "a@example.com"},
            ),
        )
        self.assertEqual(saved.finals_separators, ())

        saved = save_configuration(
            self.state_directory,
            replace(saved, finals_separators=(8, 16, 24)),
        )

        self.assertEqual(
            load_configuration(self.state_directory).finals_separators,
            (8, 16, 24),
        )

    def test_rejects_non_positive_and_duplicate_separators(self):
        configuration = ActiveConfiguration(
            default_tournament_ids=(100,),
            contributor={"name": "Name", "email": "a@example.com"},
            finals_separators=(0, 3, 3),
        )

        with self.assertRaises(ConfigurationValidationError) as raised:
            validate_active_configuration(configuration)

        self.assertIn(
            "finals separators must be positive integers",
            raised.exception.problems,
        )
        self.assertIn(
            "finals separators must be unique",
            raised.exception.problems,
        )

    def test_malformed_separator_values_raise_configuration_errors(self):
        for value in ([], {}, True, "3", 1.5):
            with self.subTest(value=value):
                configuration = ActiveConfiguration(
                    default_tournament_ids=(100,),
                    contributor={"name": "Name", "email": "a@example.com"},
                    finals_separators=(value,),
                )

                with self.assertRaises(ConfigurationValidationError) as raised:
                    validate_active_configuration(configuration)

                self.assertIn(
                    "finals separators must be positive integers",
                    raised.exception.problems,
                )


class FinalsSeparatorTypstTests(unittest.TestCase):
    def test_bold_line_follows_each_configured_row(self):
        frame = pl.DataFrame(
            {
                r"\#": [1, 2, 3, 4],
                "Namn": ["A", "B", "C", "D"],
                "Klubb": ["K", "K", "K", "K"],
                "Född": [2015, 2015, 2015, 2015],
                "Poäng": [9, 8, 7, 6],
                "played": [1, 1, 1, 1],
            }
        )

        lines = _polars_to_typst(
            frame,
            1,
            finals_separators=(1, 3, 10),
        ).splitlines()

        self.assertEqual(lines.count(HLINE), 2)
        self.assertTrue(lines[lines.index(HLINE) - 1].startswith("  [1]"))
        second = len(lines) - 1 - lines[::-1].index(HLINE)
        self.assertTrue(lines[second - 1].startswith("  [3]"))

    def test_no_bold_lines_without_separators(self):
        frame = pl.DataFrame(
            {
                r"\#": [1],
                "Namn": ["A"],
                "Klubb": ["K"],
                "Född": [2015],
                "played": [1],
            }
        )

        self.assertNotIn("table.hline", _polars_to_typst(frame, 1))


class FinalsEditorRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.state_directory = root / "state"
        self.saved = save_configuration(
            self.state_directory,
            ActiveConfiguration(
                default_tournament_ids=(100,),
                contributor={"name": "Name", "email": "a@example.com"},
                finals_separators=(8, 16),
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
                "SECRET_KEY": "finals-editor-tests",
                "STATE_DIRECTORY": self.state_directory,
                "OUTPUT_DIRECTORY": root / "output",
                "MEMBER_SYSTEM_CLIENT": member_system_client,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_configuration_page_shows_finals_tab_and_linked_summary(self):
        english = self.client.get("/configuration?lang=en").get_data(
            as_text=True
        )
        swedish = self.client.get("/configuration?lang=sv").get_data(
            as_text=True
        )

        self.assertIn('id="finals-tab"', english)
        self.assertIn('id="finals-panel"', english)
        self.assertIn('data-configuration-tab-link="finals-tab"', english)
        self.assertIn("Separators", english)
        self.assertIn("Skiljelinjer", swedish)
        self.assertIn(
            'data-save-endpoint="/api/v1/configuration/finals"',
            english,
        )
        self.assertIn('src="/static/js/finals-editor.js"', english)
        self.assertIn("data-clear-all-finals-separators", english)
        self.assertIn("Clear all", english)
        self.assertIn("Rensa alla", swedish)
        summary = english.split("data-configuration-finals-summary>")[1]
        self.assertEqual(summary.split("</dd>")[0].strip(), "8, 16")

    def test_save_normalizes_and_advances_revision(self):
        response = self.client.post(
            "/api/v1/configuration/finals",
            json={
                "revision": self.saved.revision,
                "finals_separators": [24, 8, 16, 8],
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertTrue(data["changed"])
        self.assertEqual(data["finals_separators"], [8, 16, 24])
        self.assertEqual(data["revision"], self.saved.revision + 1)
        self.assertEqual(
            load_configuration(self.state_directory).finals_separators,
            (8, 16, 24),
        )

    def test_unchanged_separators_do_not_advance_revision(self):
        response = self.client.post(
            "/api/v1/configuration/finals",
            json={
                "revision": self.saved.revision,
                "finals_separators": [16, 8],
            },
        )

        data = response.get_json()["data"]
        self.assertFalse(data["changed"])
        self.assertEqual(data["revision"], self.saved.revision)

    def test_invalid_and_stale_requests_are_rejected(self):
        for separators in ([0], [1.5], ["3"], [True], "8"):
            with self.subTest(separators=separators):
                response = self.client.post(
                    "/api/v1/configuration/finals",
                    json={
                        "revision": self.saved.revision,
                        "finals_separators": separators,
                    },
                )
                self.assertEqual(response.status_code, 400)
        stale = self.client.post(
            "/api/v1/configuration/finals",
            json={"revision": 0, "finals_separators": [3]},
        )

        self.assertEqual(stale.status_code, 409)
        self.assertEqual(load_configuration(self.state_directory), self.saved)

    def test_empty_list_clears_all_separators(self):
        response = self.client.post(
            "/api/v1/configuration/finals",
            json={"revision": self.saved.revision, "finals_separators": []},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["finals_separators"], [])
        self.assertEqual(
            load_configuration(self.state_directory).finals_separators,
            (),
        )
        page = self.client.get("/configuration?lang=en").get_data(
            as_text=True
        )
        summary = page.split("data-configuration-finals-summary>")[1]
        self.assertEqual(summary.split("</dd>")[0].strip(), "None")

    def test_editor_guards_clear_controls(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "flickornas_standings"
            / "web"
            / "static"
            / "js"
            / "finals-editor.js"
        ).read_text(encoding="utf-8")

        self.assertIn("clearAllButton.disabled = saving || allClear", source)
        self.assertIn(
            'clearButton.disabled = saving || input.value === ""',
            source,
        )
        self.assertIn('"flickornas:calendar-rollover-completed"', source)


if __name__ == "__main__":
    unittest.main()
