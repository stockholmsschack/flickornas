from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from flickornas_standings.active_configuration import (
    ACTIVE_CONFIGURATION_FILENAME,
    ActiveConfiguration,
    ConfigurationValidationError,
    LayoutConfiguration,
    StaleConfigurationError,
    load_configuration,
    save_configuration,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _configuration() -> ActiveConfiguration:
    return ActiveConfiguration(
        default_tournament_ids=(11, 22),
        known_local_players={"123": "Local Club"},
        known_local_player_names={"123": "Ada Lovelace"},
        contributor={
            "name": "Test Contributor",
            "email": "test@example.com",
        },
        layout=LayoutConfiguration(
            landscape_starts_at=12,
            base_side_margin_cm=0.9,
            margin_reduction_starts_after=6,
            margin_reduction_per_tournament_cm=0.04,
            minimum_side_margin_cm=0.55,
        ),
        club_display_names={
            "Kista FKUM Schack Sektion": "Kista FKUM",
        },
    )


class ActiveConfigurationTests(unittest.TestCase):
    def test_retired_default_orientation_is_ignored_and_removed_on_save(self):
        with tempfile.TemporaryDirectory() as directory:
            state_directory = Path(directory)
            saved = save_configuration(state_directory, _configuration())
            path = state_directory / ACTIVE_CONFIGURATION_FILENAME
            path.write_text(path.read_text().replace(
                "[layout]\n", '[layout]\ndefault_orientation = "landscape"\n'
            ))

            loaded = load_configuration(state_directory)
            self.assertEqual(loaded, saved)
            save_configuration(state_directory, loaded)
            self.assertNotIn("default_orientation", path.read_text())

    def test_module_does_not_load_configuration_at_import_time(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, "-c", "import flickornas_standings.active_configuration"],
                cwd=directory,
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_configuration_round_trips_every_persisted_setting(self):
        with tempfile.TemporaryDirectory() as directory:
            state_directory = Path(directory) / "state"

            saved = save_configuration(state_directory, _configuration())
            loaded = load_configuration(state_directory)

            self.assertEqual(saved, loaded)
            self.assertEqual(loaded.revision, 1)
            self.assertEqual(loaded.default_tournament_ids, (11, 22))
            self.assertEqual(
                loaded.known_local_players,
                {"123": "Local Club"},
            )
            self.assertEqual(
                loaded.known_local_player_names,
                {"123": "Ada Lovelace"},
            )
            self.assertEqual(
                loaded.club_display_names,
                {"Kista FKUM Schack Sektion": "Kista FKUM"},
            )
            document = (
                state_directory / ACTIVE_CONFIGURATION_FILENAME
            ).read_text()
            self.assertIn("tournament_ids = [11, 22]", document)
            self.assertNotIn("JGP_tournaments", document)
            self.assertNotIn("year", document)
            self.assertIn('[known_local_player_names]', document)
            self.assertIn('"123" = "Ada Lovelace"', document)

    def test_stale_save_cannot_overwrite_newer_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            state_directory = Path(directory)
            first_view = save_configuration(state_directory, _configuration())
            second_view = load_configuration(state_directory)
            updated = save_configuration(
                state_directory,
                replace(first_view, default_tournament_ids=(33,)),
            )

            with self.assertRaisesRegex(
                StaleConfigurationError,
                "revision 1 is stale",
            ):
                save_configuration(
                    state_directory,
                    replace(second_view, default_tournament_ids=(44,)),
                )

            self.assertEqual(updated.revision, 2)
            self.assertEqual(
                load_configuration(state_directory).default_tournament_ids,
                (33,),
            )

    def test_interrupted_replacement_leaves_previous_document_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            state_directory = Path(directory)
            original = save_configuration(state_directory, _configuration())

            with (
                patch(
                    "flickornas_standings.active_configuration.os.replace",
                    side_effect=OSError("interrupted"),
                ),
                self.assertRaisesRegex(OSError, "interrupted"),
            ):
                save_configuration(
                    state_directory,
                    replace(original, default_tournament_ids=(33,)),
                )

            self.assertEqual(load_configuration(state_directory), original)
            self.assertFalse(
                any(
                    path.name.startswith(f".{ACTIVE_CONFIGURATION_FILENAME}.")
                    for path in state_directory.iterdir()
                )
            )

    def test_validation_collects_all_problems_before_writing(self):
        invalid = ActiveConfiguration(
            default_tournament_ids=(0, 0),
            known_local_players={"bad": ""},
            known_local_player_names={"999": ""},
            contributor={"name": "", "email": ""},
            layout=LayoutConfiguration(
                landscape_starts_at=-1,
                base_side_margin_cm=0,
                margin_reduction_starts_after=-1,
                margin_reduction_per_tournament_cm=-1,
                minimum_side_margin_cm=2,
            ),
            club_display_names={"": ""},
        )
        with tempfile.TemporaryDirectory() as directory:
            state_directory = Path(directory) / "state"
            with self.assertRaises(ConfigurationValidationError) as raised:
                save_configuration(state_directory, invalid)

            self.assertGreaterEqual(len(raised.exception.problems), 10)
            self.assertFalse(state_directory.exists())

    def test_old_or_unknown_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            state_directory = Path(directory)
            (state_directory / ACTIVE_CONFIGURATION_FILENAME).write_text(
                "revision = 1\n"
                "JGP_tournaments = [11]\n"
                "tournament_year = 2026\n"
            )

            with self.assertRaises(ConfigurationValidationError) as raised:
                load_configuration(state_directory)

        self.assertIn("JGP_tournaments", str(raised.exception))
        self.assertIn("tournament_year", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
