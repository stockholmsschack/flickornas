from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from openpyxl import load_workbook

from compare_typst import compare_typst
from flickornas_standings.generation_core import (
    DIAGNOSTIC_FILENAMES,
    GenerationDiagnostics,
    TournamentInput,
    generate_standings,
    load_archived_inputs,
    serialize_standings_json,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_ARTIFACTS = PROJECT_ROOT / "reference-artifacts"


def _record(
    player_id: int,
    first_name: str,
    *,
    place: int,
    points: float,
) -> dict:
    return {
        "points": points,
        "secPoints": 10.0 - place,
        "place": place,
        "contenderId": player_id,
        "teamNumber": -1,
        "wonGames": 1,
        "drawGames": 0,
        "lostGames": 0,
        "groupId": 99,
        "klass": "a",
        "scaled_pts": points / 3,
        "playerInfo": {
            "firstName": first_name,
            "lastName": "Player",
            "birthdate": "2012",
            "sex": 1,
        },
    }


def _eligibility_result():
    return generate_standings(
        **_fixture_arguments(),
    )


class GoldenCoreTests(unittest.TestCase):
    def test_extracted_core_regenerates_accepted_typst(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(
                REFERENCE_ARTIFACTS / "2026-intermediate-inputs.zip"
            ) as archive:
                archive.extractall(root)
            tournaments, players, stats = load_archived_inputs(root)
            result = generate_standings(
                effective_year=2026,
                tournaments=tournaments,
                player_list=players,
                tournament_stats=stats,
                contributor={
                    "name": "Ganesh Srinivasson",
                    "email": "bganesh@gmail.com",
                },
            )
            generated = root / "generated.typ"
            generated.write_text(result.artifacts.typst_source)
            compare_typst(
                REFERENCE_ARTIFACTS / "2026-standings-golden.typ",
                generated,
            )


class EligibilityOrderingTests(unittest.TestCase):
    def test_non_local_affects_points_but_is_removed_before_renumbering(self):
        result = _eligibility_result()
        validation = result.standings.validation_rows
        published = json.loads(result.artifacts.standings_json)["standings"]

        visitor = validation.filter(
            validation["contenderId"] == 200
        ).to_dicts()[0]
        local_one = next(row for row in published if row["name"].startswith("Local One"))
        local_two = next(row for row in published if row["name"].startswith("Local Two"))

        self.assertEqual(visitor["STD 1"], 25)
        self.assertEqual(local_one["tournaments"], {"42": 11})
        self.assertEqual(local_two["tournaments"], {"42": 5})
        self.assertEqual(
            [row["placement"] for row in published],
            [1, 2],
        )
        self.assertNotIn("Visitor Player", [row["name"] for row in published])

    def test_validation_workbook_retains_and_highlights_non_local(self):
        result = _eligibility_result()
        workbook = load_workbook(
            BytesIO(result.artifacts.validation_workbook)
        )
        worksheet = workbook["Ladies Standings"]
        headers = [cell.value for cell in worksheet[2]]
        contender_column = headers.index("contenderId") + 1
        visitor_row = next(
            row
            for row in range(3, worksheet.max_row + 1)
            if worksheet.cell(row, contender_column).value == 200
        )

        highlighted_cells = worksheet[visitor_row]
        self.assertTrue(
            all(
                cell.fill.fill_type == "solid"
                and cell.fill.fgColor.rgb in {"FFFFFF00", "FFFF00"}
                for cell in highlighted_cells
            )
        )


class ArtifactDerivationTests(unittest.TestCase):
    def test_one_result_produces_every_artifact_and_diagnostic(self):
        result = generate_standings(
            **{
                **_fixture_arguments(),
                "diagnostics": GenerationDiagnostics(
                    walkovers={"Fixture Tournament": ("Walkover Player",)},
                    no_matches_played={
                        "Fixture Tournament": ("No Match Player",)
                    },
                    dropouts={"Fixture Tournament": ("Local One Player",)},
                    round_count_mismatches=("group 99: expected 3, got 2",),
                ),
            }
        )

        self.assertTrue(result.artifacts.validation_workbook.startswith(b"PK"))
        self.assertTrue(result.artifacts.standings_workbook.startswith(b"PK"))
        self.assertIn("Flickornas Ställning", result.artifacts.typst_source)
        self.assertEqual(
            tuple(result.artifacts.diagnostic_reports),
            DIAGNOSTIC_FILENAMES,
        )
        self.assertIn(
            "Walkover Player",
            result.artifacts.diagnostic_reports["walkovers.txt"],
        )
        self.assertIn(
            "No Match Player",
            result.artifacts.diagnostic_reports["no_matches_played.txt"],
        )
        self.assertIn(
            "group 99",
            result.artifacts.diagnostic_reports[
                "round_count_mismatches.txt"
            ],
        )
        self.assertIn(
            "Local One Player",
            result.artifacts.diagnostic_reports["dropouts.txt"],
        )


class PublicJsonAllowlistTests(unittest.TestCase):
    def test_generated_json_contains_only_public_fields(self):
        rows = json.loads(_eligibility_result().artifacts.standings_json)["standings"]
        self.assertTrue(rows)
        self.assertEqual(
            set(rows[0]),
            {
                "placement",
                "member_id",
                "name",
                "birth_year",
                "club",
                "tournaments",
                "total_points",
            },
        )

    def test_every_internal_field_is_rejected(self):
        public_row = {
            "placement": 1,
            "member_id": 100,
            "name": "Player",
            "birth_year": 2012,
            "club": "Club",
            "tournaments": {"42": 25},
            "total_points": 25,
        }
        internal_fields = (
            "contenderId",
            "klass",
            "klass_1",
            "p_1",
            "kvp_1",
            "local",
            "played",
            "playerInfo.birthdate",
            "internal_id",
            "class_processing",
            "raw_tournament_points",
            "quality_points",
            "locality_flag",
            "validation_metadata",
            "full_birth_date",
        )
        for field in internal_fields:
            with self.subTest(field=field):
                row = deepcopy(public_row)
                row[field] = "private"
                with self.assertRaisesRegex(
                    ValueError,
                    "non-allowlisted fields",
                ):
                    serialize_standings_json([row], tournament_ids=[42])

    def test_allowed_names_cannot_hide_private_values(self):
        public_row = {
            "placement": 1,
            "member_id": 100,
            "name": "Player",
            "birth_year": 2012,
            "club": "Club",
            "tournaments": {"42": 25},
            "total_points": 25,
        }

        full_birth_date = deepcopy(public_row)
        full_birth_date["birth_year"] = "2012-04-03"
        with self.assertRaisesRegex(ValueError, "four-digit year"):
            serialize_standings_json([full_birth_date], tournament_ids=[42])

        raw_tournament_data = deepcopy(public_row)
        raw_tournament_data["tournaments"] = {
            "42": {"sequence_points": 25, "raw_points": 3}
        }
        with self.assertRaisesRegex(
            ValueError,
            "only sequence points",
        ):
            serialize_standings_json([raw_tournament_data], tournament_ids=[42])


def _fixture_arguments() -> dict:
    tournament = TournamentInput(
        identifier="42",
        source_name="20260401-42.json",
        records=(
            _record(200, "Visitor", place=1, points=3),
            _record(100, "Local One", place=2, points=2),
            _record(101, "Local Two", place=3, points=1),
        ),
    )
    return {
        "effective_year": 2026,
        "tournaments": (tournament,),
        "player_list": {
            "100": {
                "klubb": "Stockholm One",
                "local": True,
                "name": "Local One Player",
            },
            "101": {
                "klubb": "Stockholm Two",
                "local": True,
                "name": "Local Two Player",
            },
            "200": {
                "klubb": "Visiting Club",
                "local": False,
                "name": "Visitor Player",
            },
        },
        "tournament_stats": {
            "42": {"name": "Fixture Tournament", "jdm": False}
        },
        "contributor": {
            "name": "Fixture",
            "email": "fixture@example.com",
        },
    }


if __name__ == "__main__":
    unittest.main()
