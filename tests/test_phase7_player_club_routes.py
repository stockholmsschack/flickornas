from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from flickornas_standings.web import create_app
from flickornas_standings.member_system_client import (
    CanonicalClub,
    ClubId,
    PlayerId,
    PlayerInfo,
    UpstreamRetryExhausted,
)


class PlayerAndClubRouteTests(unittest.TestCase):
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

    def test_player_search_returns_identity_without_selecting_a_club(self):
        self.member_system_client.player_name_search.return_value = [
            PlayerInfo(
                player_id=PlayerId(123),
                first_name="My",
                last_name="Ek Lund",
                birth_year=2014,
                current_club_id=ClubId(99),
                current_club_name="Annan klubb",
                country="SWE",
                fide_id=1712345,
            )
        ]

        response = self.client.get(
            "/api/v1/players/search"
            "?first_name=%20My%20&last_name=Ek%20Lund"
        )

        self.assertEqual(response.status_code, 200)
        self.member_system_client.player_name_search.assert_called_once_with(
            "My",
            "Ek Lund",
        )
        self.member_system_client.district_clubs.assert_not_called()
        self.assertEqual(
            response.get_json(),
            {
                "data": {
                    "state": "results",
                    "query": {
                        "first_name": "My",
                        "last_name": "Ek Lund",
                    },
                    "players": [
                        {
                            "player_id": 123,
                            "first_name": "My",
                            "last_name": "Ek Lund",
                            "birth_year": 2014,
                            "current_club": {
                                "club_id": 99,
                                "name": "Annan klubb",
                            },
                            "country": "SWE",
                            "fide_id": 1712345,
                        }
                    ],
                }
            },
        )

    def test_player_search_returns_distinct_no_matches_state(self):
        self.member_system_client.player_name_search.return_value = []

        response = self.client.get(
            "/api/v1/players/search?first_name=My&last_name=Ek"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "data": {
                    "state": "no_matches",
                    "query": {"first_name": "My", "last_name": "Ek"},
                    "players": [],
                }
            },
        )

    def test_player_search_rejects_missing_or_blank_names(self):
        for path in (
            "/api/v1/players/search",
            "/api/v1/players/search?first_name=My",
            "/api/v1/players/search?last_name=Ek",
            "/api/v1/players/search?first_name=%20&last_name=Ek",
            "/api/v1/players/search?first_name=My&last_name=%20",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.get_json()["error"]["code"],
                    "invalid_input",
                )

        self.member_system_client.player_name_search.assert_not_called()
        self.member_system_client.district_clubs.assert_not_called()

    def test_player_search_reports_upstream_failure(self):
        self.member_system_client.player_name_search.side_effect = (
            UpstreamRetryExhausted("searching players by name", "timed out")
        )

        response = self.client.get(
            "/api/v1/players/search?first_name=My&last_name=Ek"
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.get_json()["error"]["code"],
            "upstream_failure",
        )
        self.member_system_client.district_clubs.assert_not_called()

    def test_arbitrary_player_id_is_not_an_adapter_route(self):
        response = self.client.get("/api/v1/players/123?date=2026-05-30")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.member_system_client.mock_calls, [])

    def test_club_list_returns_canonical_values_without_player_state(self):
        self.member_system_client.district_clubs.return_value = [
            CanonicalClub(ClubId(10), "Stockholms SK"),
            CanonicalClub(ClubId(20), "Farsta SK"),
        ]

        response = self.client.get("/api/v1/clubs")

        self.assertEqual(response.status_code, 200)
        self.member_system_client.district_clubs.assert_called_once_with(5821)
        self.member_system_client.player_name_search.assert_not_called()
        self.assertEqual(
            response.get_json(),
            {
                "data": {
                    "state": "results",
                    "clubs": [
                        {"club_id": 10, "name": "Stockholms SK"},
                        {"club_id": 20, "name": "Farsta SK"},
                    ],
                }
            },
        )

        repeated = self.client.get("/api/v1/clubs")
        self.assertEqual(repeated.status_code, 200)
        self.member_system_client.district_clubs.assert_called_once_with(5821)

    def test_club_list_returns_distinct_no_matches_state(self):
        self.member_system_client.district_clubs.return_value = []

        response = self.client.get("/api/v1/clubs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"data": {"state": "no_matches", "clubs": []}},
        )
        self.member_system_client.player_name_search.assert_not_called()

    def test_club_list_reports_upstream_failure_without_player_dependency(self):
        self.member_system_client.district_clubs.side_effect = (
            UpstreamRetryExhausted("fetching district club list", "timed out")
        )

        response = self.client.get("/api/v1/clubs")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.get_json()["error"]["code"],
            "upstream_failure",
        )
        self.member_system_client.player_name_search.assert_not_called()
