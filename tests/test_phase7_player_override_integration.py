from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest

from flickornas_standings.active_configuration import (
    ActiveConfiguration,
    load_configuration,
    save_configuration,
)
from flickornas_standings.web import create_app
from flickornas_standings.member_system_client import (
    CanonicalClub,
    CanonicalTournament,
    ClubId,
    PlayerId,
    PlayerInfo,
    ProcessableTournamentGroup,
    TournamentGroupId,
    TournamentId,
    UpstreamRetryExhausted,
)


def _player(
    player_id: int,
    first_name: str,
    last_name: str,
    current_club_id: int,
    current_club_name: str,
) -> PlayerInfo:
    return PlayerInfo(
        player_id=PlayerId(player_id),
        first_name=first_name,
        last_name=last_name,
        birth_year=2014,
        current_club_id=ClubId(current_club_id),
        current_club_name=current_club_name,
        country="SWE",
        fide_id=1_700_000 + player_id,
    )


class InjectedPlayerMemberClient:
    def __init__(self):
        self.player_search_unavailable = False
        self.club_list_unavailable = False
        self.player_searches: list[tuple[str, str]] = []
        self.club_list_requests: list[int] = []
        self.players = (
            _player(42, "My", "Ek", 90, "Current Club"),
            _player(84, "My", "Ek", 91, "Other Current Club"),
        )
        self.clubs = (
            CanonicalClub(ClubId(10), "Wasa SK"),
            CanonicalClub(ClubId(20), "Stockholms SK"),
        )

    def player_name_search(
        self,
        first_name: str,
        last_name: str,
    ) -> list[PlayerInfo]:
        self.player_searches.append((first_name, last_name))
        if self.player_search_unavailable:
            raise UpstreamRetryExhausted(
                "searching players by name",
                "offline",
            )
        return list(self.players)

    def district_clubs(self, district_id: int) -> list[CanonicalClub]:
        self.club_list_requests.append(district_id)
        if self.club_list_unavailable:
            raise UpstreamRetryExhausted(
                "fetching district club list",
                "offline",
            )
        return list(self.clubs)

    def canonical_tournament(
        self,
        tournament_id: int,
    ) -> CanonicalTournament:
        return CanonicalTournament(
            tournament_id=TournamentId(tournament_id),
            name="Configured tournament",
            start_date=date(2026, 1, 10),
            end_date=date(2026, 1, 10),
            processable_groups=(
                ProcessableTournamentGroup(
                    group_id=TournamentGroupId(1000 + tournament_id),
                    name="Flickor",
                    klass="F",
                ),
            ),
        )


class PlayerOverrideConfigurationJourneyTests(unittest.TestCase):
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
                known_local_players={"7": "Saved Club"},
                club_display_names={"Long Club": "Short Club"},
            ),
        )
        self.member_client = InjectedPlayerMemberClient()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "player-override-integration-tests",
                "STATE_DIRECTORY": self.state_directory,
                "OUTPUT_DIRECTORY": root / "output",
                "MEMBER_SYSTEM_CLIENT": self.member_client,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_complete_verified_player_override_journey(self):
        search = self.client.get(
            "/api/v1/players/search"
            "?first_name=My&last_name=Ek"
        )

        self.assertEqual(search.status_code, 200)
        self.assertEqual(self.member_client.player_searches, [("My", "Ek")])
        self.assertEqual(self.member_client.club_list_requests, [])
        players = search.get_json()["data"]["players"]
        self.assertEqual(
            [player["player_id"] for player in players],
            [42, 84],
        )
        self.assertEqual(
            [player["current_club"]["name"] for player in players],
            ["Current Club", "Other Current Club"],
        )

        clubs_response = self.client.get("/api/v1/clubs")

        self.assertEqual(clubs_response.status_code, 200)
        clubs = clubs_response.get_json()["data"]["clubs"]
        self.assertEqual(
            clubs,
            [
                {"club_id": 10, "name": "Wasa SK"},
                {"club_id": 20, "name": "Stockholms SK"},
            ],
        )
        self.assertEqual(self.member_client.player_searches, [("My", "Ek")])

        selected_player = players[1]
        draft_override = {
            "player_id": selected_player["player_id"],
            "first_name": selected_player["first_name"],
            "last_name": selected_player["last_name"],
            "club_id": clubs[0]["club_id"],
            "club_name": clubs[0]["name"],
        }
        draft = self.client.put(
            "/api/v1/configuration/player-overrides/draft",
            json={
                "revision": self.saved.revision,
                "overrides": [draft_override],
            },
        )
        self.assertEqual(draft.status_code, 200)

        english = self.client.get("/configuration?lang=en")
        swedish = self.client.get("/configuration?lang=sv")
        for page in (english, swedish):
            body = page.get_data(as_text=True)
            self.assertIn('"player_id": 84', body)
            self.assertIn('"first_name": "My"', body)
            self.assertIn('"last_name": "Ek"', body)
            self.assertIn('"club_name": "Wasa SK"', body)
        self.assertIn("Known local players", english.get_data(as_text=True))
        self.assertIn("Kända lokala spelare", swedish.get_data(as_text=True))

        added = self.client.post(
            "/api/v1/configuration/player-overrides",
            json={
                "revision": self.saved.revision,
                "known_local_players": {
                    "7": "Saved Club",
                    "84": "Wasa SK",
                },
                "known_local_player_names": {"84": "My Ek"},
            },
        )

        self.assertEqual(added.status_code, 200)
        added_data = added.get_json()["data"]
        self.assertTrue(added_data["changed"])
        self.assertEqual(
            added_data["known_local_players"],
            {"7": "Saved Club", "84": "Wasa SK"},
        )
        added_revision = added_data["revision"]
        persisted = load_configuration(self.state_directory)
        self.assertEqual(
            persisted.known_local_players,
            {"7": "Saved Club", "84": "Wasa SK"},
        )
        self.assertEqual(
            persisted.default_tournament_ids,
            self.saved.default_tournament_ids,
        )
        self.assertEqual(persisted.contributor, self.saved.contributor)
        self.assertEqual(
            persisted.club_display_names,
            self.saved.club_display_names,
        )

        reloaded = self.client.get("/configuration").get_data(as_text=True)
        self.assertIn('"player_id": 84', reloaded)
        self.assertIn('"club_name": "Wasa SK"', reloaded)
        self.assertIn('"display_name": "My Ek"', reloaded)

        replaced = self.client.post(
            "/api/v1/configuration/player-overrides",
            json={
                "revision": added_revision,
                "known_local_players": {
                    "7": "Saved Club",
                    "84": "Stockholms SK",
                },
            },
        )

        self.assertEqual(replaced.status_code, 200)
        replaced_data = replaced.get_json()["data"]
        self.assertEqual(
            replaced_data["known_local_players"],
            {"7": "Saved Club", "84": "Stockholms SK"},
        )
        replacement_revision = replaced_data["revision"]
        self.assertEqual(
            load_configuration(
                self.state_directory
            ).known_local_players,
            {"7": "Saved Club", "84": "Stockholms SK"},
        )

        club_requests_before_idempotent_save = len(
            self.member_client.club_list_requests
        )
        unchanged = self.client.post(
            "/api/v1/configuration/player-overrides",
            json={
                "revision": replacement_revision,
                "known_local_players": {
                    "7": "Saved Club",
                    "84": "Stockholms SK",
                },
            },
        )
        self.assertEqual(unchanged.status_code, 200)
        self.assertFalse(unchanged.get_json()["data"]["changed"])
        self.assertEqual(
            unchanged.get_json()["data"]["revision"],
            replacement_revision,
        )
        self.assertEqual(
            len(self.member_client.club_list_requests),
            club_requests_before_idempotent_save,
        )

        stale = self.client.post(
            "/api/v1/configuration/player-overrides",
            json={
                "revision": added_revision,
                "known_local_players": {"84": "Wasa SK"},
            },
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(
            stale.get_json()["error"]["code"],
            "stale_configuration",
        )

        self.member_client.player_search_unavailable = True
        failed_search = self.client.get(
            "/api/v1/players/search?first_name=My&last_name=Ek"
        )
        self.assertEqual(failed_search.status_code, 502)

        self.member_client.club_list_unavailable = True
        club_requests_before_cached_read = len(
            self.member_client.club_list_requests
        )
        cached_club_list = self.client.get("/api/v1/clubs")
        self.assertEqual(cached_club_list.status_code, 200)
        self.assertEqual(
            len(self.member_client.club_list_requests),
            club_requests_before_cached_read,
        )

        unchanged_while_offline = self.client.post(
            "/api/v1/configuration/player-overrides",
            json={
                "revision": replacement_revision,
                "known_local_players": {
                    "7": "Saved Club",
                    "84": "Stockholms SK",
                },
            },
        )
        self.assertEqual(unchanged_while_offline.status_code, 200)
        self.assertFalse(
            unchanged_while_offline.get_json()["data"]["changed"]
        )

        cached_change = self.client.post(
            "/api/v1/configuration/player-overrides",
            json={
                "revision": replacement_revision,
                "known_local_players": {
                    "7": "Saved Club",
                    "84": "Wasa SK",
                },
            },
        )
        self.assertEqual(cached_change.status_code, 200)
        self.assertTrue(cached_change.get_json()["data"]["changed"])
        cached_revision = cached_change.get_json()["data"]["revision"]
        self.assertEqual(
            len(self.member_client.club_list_requests),
            club_requests_before_cached_read,
        )
        self.assertEqual(
            load_configuration(
                self.state_directory
            ).known_local_players,
            {"7": "Saved Club", "84": "Wasa SK"},
        )

        removed = self.client.post(
            "/api/v1/configuration/player-overrides",
            json={
                "revision": cached_revision,
                "known_local_players": {"7": "Saved Club"},
            },
        )
        self.assertEqual(removed.status_code, 200)
        self.assertTrue(removed.get_json()["data"]["changed"])
        self.assertEqual(
            load_configuration(
                self.state_directory
            ).known_local_players,
            {"7": "Saved Club"},
        )


if __name__ == "__main__":
    unittest.main()
