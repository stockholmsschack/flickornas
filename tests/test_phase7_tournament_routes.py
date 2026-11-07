from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from flickornas_standings.web import create_app
from flickornas_standings.member_system_client import (
    CanonicalTournament,
    ProcessableTournamentGroup,
    TournamentGroupId,
    TournamentGroupSearchHit,
    TournamentId,
    TournamentResolutionError,
    UpstreamRetryExhausted,
)


class TournamentRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.member_system_client = Mock()
        self.app = create_app(
            {
                "TESTING": True,
                "STATE_DIRECTORY": root / "state",
                "OUTPUT_DIRECTORY": root / "output",
                "MEMBER_SYSTEM_CLIENT": self.member_system_client,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_search_decodes_text_and_groups_rows_by_tournament_id(self):
        self.member_system_client.tournament_group_search.return_value = [
            TournamentGroupSearchHit(
                matching_group_id=TournamentGroupId(8101),
                tournament_id=TournamentId(6336),
                matching_group_name="Flickor 2014",
                tournament_name="Flick-DM Stockholm",
                latest_updated_game="2026-03-08T14:30:00Z",
            ),
            TournamentGroupSearchHit(
                matching_group_id=TournamentGroupId(8102),
                tournament_id=TournamentId(6336),
                matching_group_name="Flickor 2012",
                tournament_name="Flick-DM Stockholm",
            ),
            TournamentGroupSearchHit(
                matching_group_id=TournamentGroupId(9201),
                tournament_id=TournamentId(7447),
                matching_group_name="Klass F 10",
                tournament_name="Flick-SM",
            ),
        ]

        response = self.client.get(
            "/api/v1/tournaments/search?q=Flick-DM%20Stockholm%2FFinal"
        )

        self.assertEqual(response.status_code, 200)
        self.member_system_client.tournament_group_search.assert_called_once_with(
            "Flick-DM Stockholm/Final"
        )
        self.assertEqual(
            response.get_json(),
            {
                "data": {
                    "state": "results",
                    "query": "Flick-DM Stockholm/Final",
                    "tournaments": [
                        {
                            "tournament_id": 7447,
                            "name": "Flick-SM",
                            "matching_groups": [
                                {
                                    "group_id": 9201,
                                    "name": "Klass F 10",
                                    "latest_updated_game": None,
                                }
                            ],
                        },
                        {
                            "tournament_id": 6336,
                            "name": "Flick-DM Stockholm",
                            "matching_groups": [
                                {
                                    "group_id": 8101,
                                    "name": "Flickor 2014",
                                    "latest_updated_game": (
                                        "2026-03-08T14:30:00Z"
                                    ),
                                },
                                {
                                    "group_id": 8102,
                                    "name": "Flickor 2012",
                                    "latest_updated_game": None,
                                },
                            ],
                        },
                    ],
                }
            },
        )

    def test_empty_search_has_a_distinct_success_state(self):
        self.member_system_client.tournament_group_search.return_value = []

        response = self.client.get("/api/v1/tournaments/search?q=saknas")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "data": {
                    "state": "no_matches",
                    "query": "saknas",
                    "tournaments": [],
                }
            },
        )

    def test_search_sorts_tournaments_by_descending_tournament_id(self):
        self.member_system_client.tournament_group_search.return_value = [
            TournamentGroupSearchHit(
                matching_group_id=TournamentGroupId(9201),
                tournament_id=TournamentId(5225),
                matching_group_name="Klass F 10",
                tournament_name="Wasa JGP 2024",
            ),
            TournamentGroupSearchHit(
                matching_group_id=TournamentGroupId(8101),
                tournament_id=TournamentId(6336),
                matching_group_name="Flickor 2014",
                tournament_name="Wasa JGP 2025",
                latest_updated_game="2025-11-02T12:00:00Z",
            ),
            TournamentGroupSearchHit(
                matching_group_id=TournamentGroupId(7301),
                tournament_id=TournamentId(7447),
                matching_group_name="Flickor 2012",
                tournament_name="Wasa JGP 2026",
            ),
            TournamentGroupSearchHit(
                matching_group_id=TournamentGroupId(7302),
                tournament_id=TournamentId(7447),
                matching_group_name="Flickor 2010",
                tournament_name="Wasa JGP 2026",
            ),
        ]

        response = self.client.get("/api/v1/tournaments/search?q=Flick")

        self.assertEqual(response.status_code, 200)
        tournaments = response.get_json()["data"]["tournaments"]
        self.assertEqual(
            [tournament["tournament_id"] for tournament in tournaments],
            [7447, 6336, 5225],
        )

    def test_search_rejects_missing_or_blank_text_without_calling_upstream(self):
        for path in (
            "/api/v1/tournaments/search",
            "/api/v1/tournaments/search?q=%20%20",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error"]["code"], "invalid_input")

        self.member_system_client.tournament_group_search.assert_not_called()

    def test_search_reports_upstream_failure(self):
        self.member_system_client.tournament_group_search.side_effect = (
            UpstreamRetryExhausted("searching tournament groups", "timed out")
        )

        response = self.client.get("/api/v1/tournaments/search?q=Flick")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["error"]["code"], "upstream_failure")

    def test_canonical_lookup_returns_verified_tournament(self):
        self.member_system_client.canonical_tournament.return_value = (
            CanonicalTournament(
                tournament_id=TournamentId(6336),
                name="Flick-DM Stockholm",
                start_date=date(2026, 3, 7),
                end_date=date(2026, 3, 8),
                processable_groups=(
                    ProcessableTournamentGroup(
                        group_id=TournamentGroupId(8101),
                        name="Flickor 2014",
                        klass="2014",
                    ),
                ),
            )
        )

        response = self.client.get("/api/v1/tournaments/6336")

        self.assertEqual(response.status_code, 200)
        self.member_system_client.canonical_tournament.assert_called_once_with(6336)
        self.assertEqual(
            response.get_json(),
            {
                "data": {
                    "tournament": {
                        "tournament_id": 6336,
                        "name": "Flick-DM Stockholm",
                        "start_date": "2026-03-07",
                        "end_date": "2026-03-08",
                        "processable_groups": [
                            {
                                "group_id": 8101,
                                "name": "Flickor 2014",
                                "klass": "2014",
                            }
                        ],
                    }
                }
            },
        )

    def test_canonical_lookup_rejects_invalid_input_without_calling_upstream(self):
        for tournament_id in ("abc", "0", "-1", "01"):
            with self.subTest(tournament_id=tournament_id):
                response = self.client.get(
                    f"/api/v1/tournaments/{tournament_id}"
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error"]["code"], "invalid_input")

        self.member_system_client.canonical_tournament.assert_not_called()

    def test_canonical_lookup_reports_unresolvable_tournament(self):
        self.member_system_client.canonical_tournament.side_effect = (
            TournamentResolutionError(999, "not found")
        )

        response = self.client.get("/api/v1/tournaments/999")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.get_json(),
            {
                "error": {
                    "code": "tournament_unresolvable",
                    "message_key": "errors.tournament_lookup.unresolvable",
                    "details": {"tournament_id": 999},
                }
            },
        )

    def test_canonical_lookup_reports_upstream_failure(self):
        self.member_system_client.canonical_tournament.side_effect = (
            UpstreamRetryExhausted("resolving canonical tournament 6336", "timed out")
        )

        response = self.client.get("/api/v1/tournaments/6336")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["error"]["code"], "upstream_failure")


if __name__ == "__main__":
    unittest.main()
