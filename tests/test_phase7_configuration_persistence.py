from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

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
    ProcessableTournamentGroup,
    TournamentGroupId,
    TournamentId,
    TournamentResolutionError,
    UpstreamRetryExhausted,
)


def _configuration() -> ActiveConfiguration:
    return ActiveConfiguration(
        default_tournament_ids=(100, 200),
        contributor={
            "name": "Test Contributor",
            "email": "test@example.com",
        },
        known_local_players={"123": "Local Club"},
        club_display_names={"Long Club": "Club"},
    )


def _tournament(
    tournament_id: int,
    name: str,
    start_date: date,
) -> CanonicalTournament:
    return CanonicalTournament(
        tournament_id=TournamentId(tournament_id),
        name=name,
        start_date=start_date,
        end_date=start_date,
        processable_groups=(
            ProcessableTournamentGroup(
                group_id=TournamentGroupId(tournament_id + 1000),
                name="Flickor",
                klass="F",
            ),
        ),
    )


class ConfigurationPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.state_directory = root / "state"
        self.saved = save_configuration(
            self.state_directory,
            _configuration(),
        )
        self.member_system_client = Mock()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "configuration-persistence-tests",
                "STATE_DIRECTORY": self.state_directory,
                "OUTPUT_DIRECTORY": root / "output",
                "MEMBER_SYSTEM_CLIENT": self.member_system_client,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_changed_selection_is_reverified_sorted_and_atomically_saved(self):
        tournaments = {
            300: _tournament(300, "March later ID", date(2026, 3, 1)),
            250: _tournament(250, "January", date(2026, 1, 10)),
            100: _tournament(100, "March earlier ID", date(2026, 3, 1)),
        }
        self.member_system_client.canonical_tournament.side_effect = (
            lambda tournament_id: tournaments[tournament_id]
        )

        response = self.client.post(
            "/api/v1/configuration/tournaments",
            json={
                "revision": self.saved.revision,
                "tournament_ids": [300, 250, 100],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["data"],
            {
                "revision": self.saved.revision + 1,
                "tournament_ids": [250, 100, 300],
                "changed": True,
            },
        )
        loaded = load_configuration(self.state_directory)
        self.assertEqual(loaded.default_tournament_ids, (250, 100, 300))
        self.assertEqual(loaded.contributor, self.saved.contributor)
        self.assertEqual(
            loaded.known_local_players,
            self.saved.known_local_players,
        )
        self.assertEqual(
            loaded.club_display_names,
            self.saved.club_display_names,
        )

    def test_unchanged_selection_saves_without_upstream_or_revision_change(self):
        self.member_system_client.canonical_tournament.side_effect = (
            UpstreamRetryExhausted("resolving tournaments", "offline")
        )

        response = self.client.post(
            "/api/v1/configuration/tournaments",
            json={
                "revision": self.saved.revision,
                "tournament_ids": [100, 200],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["data"]["changed"])
        self.assertEqual(
            load_configuration(self.state_directory).revision,
            self.saved.revision,
        )
        self.member_system_client.canonical_tournament.assert_not_called()

    def test_stale_save_is_refused_before_upstream_resolution(self):
        response = self.client.post(
            "/api/v1/configuration/tournaments",
            json={"revision": 0, "tournament_ids": [300]},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["error"]["code"],
            "stale_configuration",
        )
        self.member_system_client.canonical_tournament.assert_not_called()
        self.assertEqual(
            load_configuration(self.state_directory),
            self.saved,
        )

    def test_unresolvable_changed_id_blocks_save(self):
        self.member_system_client.canonical_tournament.side_effect = (
            TournamentResolutionError(1100, "group id is not a tournament")
        )

        response = self.client.post(
            "/api/v1/configuration/tournaments",
            json={
                "revision": self.saved.revision,
                "tournament_ids": [1100],
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.get_json()["error"]["code"],
            "tournament_unresolvable",
        )
        self.assertEqual(
            load_configuration(self.state_directory),
            self.saved,
        )

    def test_draft_survives_language_switch_in_flask_session(self):
        draft = [
            {
                "tournament_id": 300,
                "name": "Draft tournament",
                "start_date": "2026-03-01",
                "end_date": "2026-03-02",
            }
        ]
        draft_response = self.client.put(
            "/api/v1/configuration/tournaments/draft",
            json={
                "revision": self.saved.revision,
                "tournaments": draft,
            },
        )
        self.assertEqual(draft_response.status_code, 200)

        english = self.client.get("/configuration?lang=en")
        swedish = self.client.get("/configuration?lang=sv")

        self.assertIn("Draft tournament", english.get_data(as_text=True))
        self.assertIn("Draft tournament", swedish.get_data(as_text=True))
        self.assertIn("Find tournaments", english.get_data(as_text=True))
        self.assertIn("Hitta turneringar", swedish.get_data(as_text=True))
        self.member_system_client.canonical_tournament.assert_not_called()

    def test_invalid_or_duplicate_ids_do_not_reach_upstream(self):
        for tournament_ids in ([], [0], [300, 300], [True]):
            with self.subTest(tournament_ids=tournament_ids):
                response = self.client.post(
                    "/api/v1/configuration/tournaments",
                    json={
                        "revision": self.saved.revision,
                        "tournament_ids": tournament_ids,
                    },
                )
                self.assertEqual(response.status_code, 400)

        self.member_system_client.canonical_tournament.assert_not_called()

    def test_changed_player_overrides_revalidate_clubs_and_preserve_fields(self):
        self.member_system_client.district_clubs.return_value = [
            CanonicalClub(ClubId(10), "Wasa SK"),
            CanonicalClub(ClubId(20), "Stockholms SK"),
        ]

        response = self.client.post(
            "/api/v1/configuration/player-overrides",
            json={
                "revision": self.saved.revision,
                "known_local_players": {
                    "123": "Wasa SK",
                    "456": "Stockholms SK",
                },
                "known_local_player_names": {
                    "123": "Saved Player",
                    "456": "New Player",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["data"]["changed"])
        loaded = load_configuration(self.state_directory)
        self.assertEqual(
            loaded.known_local_players,
            {"123": "Wasa SK", "456": "Stockholms SK"},
        )
        self.assertEqual(
            loaded.known_local_player_names,
            {"123": "Saved Player", "456": "New Player"},
        )
        self.assertEqual(
            loaded.default_tournament_ids,
            self.saved.default_tournament_ids,
        )
        self.assertEqual(loaded.contributor, self.saved.contributor)
        self.assertEqual(
            loaded.club_display_names,
            self.saved.club_display_names,
        )

    def test_unchanged_player_overrides_do_not_require_club_service(self):
        self.member_system_client.district_clubs.side_effect = (
            UpstreamRetryExhausted("fetching clubs", "offline")
        )

        response = self.client.post(
            "/api/v1/configuration/player-overrides",
            json={
                "revision": self.saved.revision,
                "known_local_players": {"123": "Local Club"},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["data"]["changed"])
        self.member_system_client.district_clubs.assert_not_called()

    def test_player_name_is_saved_without_an_upstream_lookup(self):
        response = self.client.post(
            "/api/v1/configuration/player-overrides",
            json={
                "revision": self.saved.revision,
                "known_local_players": {"123": "Local Club"},
                "known_local_player_names": {"123": "Ada Lovelace"},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["data"]["changed"])
        self.assertEqual(
            load_configuration(
                self.state_directory
            ).known_local_player_names,
            {"123": "Ada Lovelace"},
        )
        self.member_system_client.district_clubs.assert_not_called()

    def test_player_override_removal_does_not_require_club_service(self):
        response = self.client.post(
            "/api/v1/configuration/player-overrides",
            json={
                "revision": self.saved.revision,
                "known_local_players": {},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            load_configuration(self.state_directory).known_local_players,
            {},
        )
        self.member_system_client.district_clubs.assert_not_called()

    def test_noncanonical_changed_club_blocks_player_override_save(self):
        self.member_system_client.district_clubs.return_value = [
            CanonicalClub(ClubId(10), "Wasa SK"),
        ]

        response = self.client.post(
            "/api/v1/configuration/player-overrides",
            json={
                "revision": self.saved.revision,
                "known_local_players": {"123": "Invented Club"},
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.get_json()["error"]["code"],
            "noncanonical_club",
        )
        self.assertEqual(load_configuration(self.state_directory), self.saved)

    def test_stale_player_override_save_is_refused_before_club_lookup(self):
        response = self.client.post(
            "/api/v1/configuration/player-overrides",
            json={
                "revision": 0,
                "known_local_players": {"123": "Wasa SK"},
            },
        )

        self.assertEqual(response.status_code, 409)
        self.member_system_client.district_clubs.assert_not_called()

    def test_player_override_draft_survives_language_switch(self):
        tournament_draft = [
            {
                "tournament_id": 100,
                "name": "Tournament",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
            }
        ]
        self.client.put(
            "/api/v1/configuration/tournaments/draft",
            json={
                "revision": self.saved.revision,
                "tournaments": tournament_draft,
            },
        )
        draft = [
            {
                "player_id": 456,
                "first_name": "My",
                "last_name": "Ek",
                "club_id": 10,
                "club_name": "Wasa SK",
            }
        ]
        response = self.client.put(
            "/api/v1/configuration/player-overrides/draft",
            json={
                "revision": self.saved.revision,
                "overrides": draft,
            },
        )
        self.assertEqual(response.status_code, 200)

        english = self.client.get("/configuration?lang=en")
        swedish = self.client.get("/configuration?lang=sv")

        for page in (english, swedish):
            body = page.get_data(as_text=True)
            self.assertIn('"first_name": "My"', body)
            self.assertIn('"last_name": "Ek"', body)
            self.assertIn('"club_name": "Wasa SK"', body)
        self.member_system_client.district_clubs.assert_not_called()

    def test_stale_player_override_draft_is_discarded(self):
        self.client.put(
            "/api/v1/configuration/tournaments/draft",
            json={
                "revision": self.saved.revision,
                "tournaments": [
                    {
                        "tournament_id": 100,
                        "name": "Tournament",
                        "start_date": "2026-01-01",
                        "end_date": "2026-01-02",
                    }
                ],
            },
        )
        self.client.put(
            "/api/v1/configuration/player-overrides/draft",
            json={
                "revision": self.saved.revision - 1,
                "overrides": [
                    {
                        "player_id": 456,
                        "first_name": "My",
                        "last_name": "Ek",
                        "club_id": 10,
                        "club_name": "Wasa SK",
                    }
                ],
            },
        )

        body = self.client.get("/configuration").get_data(as_text=True)

        self.assertNotIn('"first_name": "My"', body)
        self.assertIn('"player_id": 123', body)
        with self.client.session_transaction() as flask_session:
            self.assertNotIn(
                "flickornas.player_override_draft",
                flask_session,
            )

    def test_invalid_player_override_payload_does_not_reach_upstream(self):
        invalid_values = (
            [],
            {"0": "Wasa SK"},
            {"01": "Wasa SK"},
            {"123": ""},
        )
        for known_local_players in invalid_values:
            with self.subTest(known_local_players=known_local_players):
                response = self.client.post(
                    "/api/v1/configuration/player-overrides",
                    json={
                        "revision": self.saved.revision,
                        "known_local_players": known_local_players,
                    },
                )
                self.assertEqual(response.status_code, 400)

        self.member_system_client.district_clubs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
