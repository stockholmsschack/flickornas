from __future__ import annotations

from dataclasses import replace
from datetime import date
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flickornas_standings.active_configuration import ActiveConfiguration
from flickornas_standings.generation_orchestrator import (
    GenerationInputs,
    GenerationStageError,
    GenerationValidationError,
    run_generation,
)
from flickornas_standings.member_system_client import (
    CanonicalClub,
    CanonicalTournament,
    ClubId,
    ProcessableTournamentGroup,
    TournamentGroupId,
    TournamentId,
)


def _metadata(
    tournament_id: int,
    *,
    start: str,
    end: str,
) -> dict:
    return {
        "name": f"Tournament {tournament_id}",
        "start": start,
        "end": end,
        "rootClasses": [
            {
                "groups": [
                    {
                        "id": tournament_id * 10,
                        "name": "Klass A",
                        "nrofrounds": 2,
                        "pointSystem": "GAME",
                    }
                ]
            }
        ],
    }


def _table(group_id: int, *, female: bool = True) -> list[dict]:
    return [
        {
            "points": 2,
            "secPoints": 3,
            "place": 1,
            "contenderId": 100,
            "teamNumber": -1,
            "wonGames": 2,
            "drawGames": 0,
            "lostGames": 0,
            "groupId": group_id,
            "playerInfo": {
                "firstName": "Local",
                "lastName": "Player",
                "birthdate": "2012",
                "sex": 1 if female else 0,
                "clubId": 10,
                "club": "Stockholm Club",
            },
        },
        {
            "points": 0,
            "secPoints": 1,
            "place": 2,
            "contenderId": 200,
            "teamNumber": -1,
            "wonGames": 0,
            "drawGames": 0,
            "lostGames": 2,
            "groupId": group_id,
            "playerInfo": {
                "firstName": "Visitor",
                "lastName": "Player",
                "birthdate": "2011",
                "sex": 1 if female else 0,
                "clubId": 20,
                "club": "Visitor Club",
            },
        },
    ]


def _rounds() -> list[dict]:
    return [
        {
            "roundNr": 1,
            "games": [{"whiteId": 100, "blackId": 200, "result": 1}],
        },
        {
            "roundNr": 2,
            "games": [{"whiteId": 200, "blackId": 100, "result": -1}],
        },
    ]


class FixtureClient:
    def __init__(self, *, female: bool = True) -> None:
        self.calls = []
        self.female = female
        self.metadata = {
            11: _metadata(
                11,
                start="2026-02-01",
                end="2026-02-02",
            ),
            22: _metadata(
                22,
                start="2026-04-01",
                end="2026-11-08",
            ),
        }

    def canonical_tournament(self, tournament_id: int) -> CanonicalTournament:
        self.calls.append(("canonical", tournament_id))
        document = self.metadata[tournament_id]
        group = document["rootClasses"][0]["groups"][0]
        return CanonicalTournament(
            tournament_id=TournamentId(tournament_id),
            name=document["name"],
            start_date=date.fromisoformat(document["start"]),
            end_date=date.fromisoformat(document["end"]),
            processable_groups=(
                ProcessableTournamentGroup(
                    group_id=TournamentGroupId(group["id"]),
                    name=group["name"],
                    klass="a",
                    registered_rounds=group["nrofrounds"],
                ),
            ),
        )

    def district_rating_list(self, district_id: int, request_date: date):
        self.calls.append(("ratings", district_id, request_date))
        return [{"id": 100}]

    def district_clubs(self, district_id: int):
        self.calls.append(("clubs", district_id))
        return [CanonicalClub(club_id=ClubId(10), name="Stockholms SK")]

    def group_table(self, group_id: int):
        self.calls.append(("table", group_id))
        return _table(group_id, female=self.female)

    def group_round_results(self, group_id: int):
        self.calls.append(("rounds", group_id))
        return _rounds()


def _configuration() -> ActiveConfiguration:
    return ActiveConfiguration(
        default_tournament_ids=(11, 22),
        contributor={"name": "Fixture", "email": "fixture@example.com"},
    )


def _inputs() -> GenerationInputs:
    return GenerationInputs(effective_year=2026, tournament_ids=(11, 22))


class SinglePassGenerationTests(unittest.TestCase):
    def test_one_action_runs_every_stage_in_memory(self):
        client = FixtureClient()

        result = run_generation(_configuration(), _inputs(), client)

        self.assertEqual(
            client.calls,
            [
                ("canonical", 11),
                ("canonical", 22),
                ("ratings", 5821, date(2026, 11, 8)),
                ("clubs", 5821),
                ("table", 110),
                ("rounds", 110),
                ("table", 220),
                ("rounds", 220),
            ],
        )
        self.assertEqual(result.standings.tournament_ids, ("11", "22"))
        self.assertTrue(result.artifacts.validation_workbook.startswith(b"PK"))
        self.assertTrue(result.artifacts.standings_workbook.startswith(b"PK"))
        self.assertIn("Flickornas Ställning", result.artifacts.typst_source)
        self.assertEqual(
            [row["name"] for row in json.loads(result.artifacts.standings_json)["standings"]],
            ["Local Player"],
        )

    def test_generation_needs_no_intermediate_files_or_working_directory_state(self):
        original_directory = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                result = run_generation(
                    _configuration(),
                    _inputs(),
                    FixtureClient(),
                )
                self.assertTrue(result.artifacts.typst_source)
                self.assertEqual(list(Path(directory).iterdir()), [])
            finally:
                os.chdir(original_directory)

    def test_known_local_override_is_applied_before_eligibility_resolution(self):
        configuration = replace(
            _configuration(),
            known_local_players={"200": "Override Club"},
        )

        result = run_generation(configuration, _inputs(), FixtureClient())
        rows = json.loads(result.artifacts.standings_json)["standings"]

        self.assertEqual(
            {row["name"] for row in rows},
            {"Local Player", "Visitor Player"},
        )
        visitor = next(row for row in rows if row["name"] == "Visitor Player")
        self.assertEqual(visitor["club"], "Override Club")

    def test_known_local_override_for_nonparticipant_is_inert(self):
        configuration = replace(
            _configuration(),
            known_local_players={"999": "Override Club"},
        )

        result = run_generation(configuration, _inputs(), FixtureClient())
        rows = json.loads(result.artifacts.standings_json)["standings"]

        self.assertEqual(
            [row["name"] for row in rows],
            ["Local Player"],
        )

    def test_no_show_dropout_is_retained_in_both_diagnostics(self):
        client = FixtureClient()
        client.group_round_results = lambda _group_id: [
            {
                "roundNr": round_number,
                "games": [
                    {"whiteId": 100, "blackId": 200, "result": 2}
                ],
            }
            for round_number in (1, 2)
        ]

        diagnostics = run_generation(
            _configuration(),
            _inputs(),
            client,
        ).standings.diagnostics

        finding = "Visitor Player (200)"
        self.assertIn(finding, diagnostics.walkovers["Tournament 11"])
        self.assertIn(finding, diagnostics.dropouts["Tournament 11"])

    def test_partial_run_uses_only_the_selected_tournament(self):
        client = FixtureClient()
        inputs = GenerationInputs(
            effective_year=2026,
            tournament_ids=(11,),
            is_partial=True,
        )

        result = run_generation(_configuration(), inputs, client)

        self.assertEqual(result.standings.effective_year, 2026)
        self.assertEqual(result.standings.tournament_ids, ("11",))
        self.assertEqual(
            client.calls,
            [
                ("canonical", 11),
                ("ratings", 5821, date(2026, 2, 2)),
                ("clubs", 5821),
                ("table", 110),
                ("rounds", 110),
            ],
        )
        rows = json.loads(result.artifacts.standings_json)["standings"]
        self.assertEqual(set(rows[0]["tournaments"]), {"11"})


class FailureBoundaryTests(unittest.TestCase):
    def test_default_generation_rejects_stale_mixed_and_future_tournaments(self):
        cases = (
            (("2025-02-01", "2025-04-01"), "previous year"),
            (("2025-02-01", "2026-04-01"), "multiple calendar years"),
            (("2027-02-01", "2027-04-01"), "future calendar year"),
        )
        for start_dates, expected_problem in cases:
            with self.subTest(expected_problem=expected_problem):
                client = FixtureClient()
                client.metadata[11]["start"] = start_dates[0]
                client.metadata[22]["start"] = start_dates[1]

                with self.assertRaisesRegex(
                    GenerationValidationError,
                    expected_problem,
                ):
                    run_generation(_configuration(), _inputs(), client)

                self.assertEqual(
                    client.calls,
                    [("canonical", 11), ("canonical", 22)],
                )

    def test_generation_inputs_are_immutable(self):
        tournament_ids = [11, 22]
        inputs = GenerationInputs(
            effective_year=2026,
            tournament_ids=tournament_ids,
        )
        tournament_ids.append(33)

        self.assertEqual(inputs.tournament_ids, (11, 22))
        with self.assertRaises(AttributeError):
            inputs.effective_year = 2027

    def test_validation_reports_all_problems_before_fetching(self):
        client = FixtureClient()
        configuration = ActiveConfiguration(
            default_tournament_ids=(0, 0),
            contributor={"name": "", "email": ""},
            known_local_players={"bad": ""},
        )
        inputs = GenerationInputs(
            effective_year=26,
            tournament_ids=(0, 0),
        )

        with self.assertRaises(GenerationValidationError) as raised:
            run_generation(configuration, inputs, client)

        self.assertGreaterEqual(len(raised.exception.problems), 6)
        self.assertEqual(raised.exception.stage, "validation")
        self.assertEqual(client.calls, [])

    def test_fetch_failure_names_stage_and_returns_no_result(self):
        client = FixtureClient()

        def fail(_tournament_id):
            raise RuntimeError("fixture unavailable")

        client.canonical_tournament = fail
        with self.assertRaisesRegex(
            GenerationStageError,
            r"during fetching: fixture unavailable",
        ) as raised:
            run_generation(_configuration(), _inputs(), client)

        self.assertEqual(raised.exception.stage, "fetching")

    def test_all_tournament_ids_resolve_before_calculation_or_other_fetches(self):
        client = FixtureClient()
        del client.metadata[22]

        with (
            patch("flickornas_standings.generation_orchestrator.collate_standings") as calculate,
            self.assertRaises(GenerationStageError),
        ):
            run_generation(_configuration(), _inputs(), client)

        self.assertEqual(client.calls, [("canonical", 11), ("canonical", 22)])
        calculate.assert_not_called()

    def test_calculation_failure_names_stage(self):
        with self.assertRaisesRegex(
            GenerationStageError,
            r"during calculation: no female player standings",
        ) as raised:
            run_generation(
                _configuration(),
                _inputs(),
                FixtureClient(female=False),
            )

        self.assertEqual(raised.exception.stage, "calculation")

    def test_artifact_failure_names_stage(self):
        with patch(
                "flickornas_standings.generation_orchestrator.build_generation_result",
            side_effect=RuntimeError("workbook failed"),
        ):
            with self.assertRaisesRegex(
                GenerationStageError,
                r"during artifact production: workbook failed",
            ) as raised:
                run_generation(_configuration(), _inputs(), FixtureClient())

        self.assertEqual(raised.exception.stage, "artifact production")


if __name__ == "__main__":
    unittest.main()
