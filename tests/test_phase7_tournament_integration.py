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
    CanonicalTournament,
    ProcessableTournamentGroup,
    TournamentGroupId,
    TournamentGroupSearchHit,
    TournamentId,
    TournamentResolutionError,
    UpstreamRetryExhausted,
)


def _tournament(
    tournament_id: int,
    name: str,
    start_date: date,
    group_id: int,
) -> CanonicalTournament:
    return CanonicalTournament(
        tournament_id=TournamentId(tournament_id),
        name=name,
        start_date=start_date,
        end_date=start_date,
        processable_groups=(
            ProcessableTournamentGroup(
                group_id=TournamentGroupId(group_id),
                name="Flickor",
                klass="F",
            ),
        ),
    )


class InjectedMemberClient:
    def __init__(self):
        self.search_unavailable = False
        self.lookup_unavailable = False
        self.search_queries: list[str] = []
        self.lookup_ids: list[int] = []
        self.tournaments = {
            100: _tournament(
                100,
                "Saved tournament",
                date(2025, 12, 1),
                9100,
            ),
            200: _tournament(
                200,
                "January tournament",
                date(2026, 1, 10),
                9200,
            ),
            300: _tournament(
                300,
                "March tournament",
                date(2026, 3, 1),
                9300,
            ),
        }

    def tournament_group_search(
        self,
        search_text: str,
    ) -> list[TournamentGroupSearchHit]:
        self.search_queries.append(search_text)
        if self.search_unavailable:
            raise UpstreamRetryExhausted(
                "searching tournament groups",
                "offline",
            )
        return [
            TournamentGroupSearchHit(
                matching_group_id=TournamentGroupId(9301),
                tournament_id=TournamentId(300),
                matching_group_name="Flickor A",
                tournament_name="March tournament",
            ),
            TournamentGroupSearchHit(
                matching_group_id=TournamentGroupId(9302),
                tournament_id=TournamentId(300),
                matching_group_name="Flickor B",
                tournament_name="March tournament",
            ),
            TournamentGroupSearchHit(
                matching_group_id=TournamentGroupId(9201),
                tournament_id=TournamentId(200),
                matching_group_name="Flickor",
                tournament_name="January tournament",
            ),
        ]

    def canonical_tournament(
        self,
        tournament_id: int,
    ) -> CanonicalTournament:
        self.lookup_ids.append(tournament_id)
        if self.lookup_unavailable:
            raise UpstreamRetryExhausted(
                f"resolving canonical tournament {tournament_id}",
                "offline",
            )
        try:
            return self.tournaments[tournament_id]
        except KeyError as error:
            raise TournamentResolutionError(
                tournament_id,
                "not a tournament id",
            ) from error


class TournamentConfigurationJourneyTests(unittest.TestCase):
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
            ),
        )
        self.member_client = InjectedMemberClient()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "tournament-integration-tests",
                "STATE_DIRECTORY": self.state_directory,
                "OUTPUT_DIRECTORY": root / "output",
                "MEMBER_SYSTEM_CLIENT": self.member_client,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_complete_verified_configuration_journey(self):
        search = self.client.get("/api/v1/tournaments/search?q=was")

        self.assertEqual(search.status_code, 200)
        self.assertEqual(self.member_client.search_queries, ["was"])
        search_results = search.get_json()["data"]["tournaments"]
        self.assertEqual(
            [result["tournament_id"] for result in search_results],
            [300, 200],
        )
        self.assertEqual(
            [
                group["group_id"]
                for group in search_results[0]["matching_groups"]
            ],
            [9301, 9302],
        )

        selected_from_search = self.client.get("/api/v1/tournaments/300")
        selected_from_pasted_id = self.client.get("/api/v1/tournaments/200")

        self.assertEqual(selected_from_search.status_code, 200)
        self.assertEqual(selected_from_pasted_id.status_code, 200)
        searched_tournament = selected_from_search.get_json()["data"][
            "tournament"
        ]
        pasted_tournament = selected_from_pasted_id.get_json()["data"][
            "tournament"
        ]
        self.assertEqual(
            searched_tournament["tournament_id"],
            300,
        )
        self.assertEqual(
            pasted_tournament["tournament_id"],
            200,
        )
        self.assertEqual(self.member_client.lookup_ids, [300, 200])

        draft = self.client.put(
            "/api/v1/configuration/tournaments/draft",
            json={
                "revision": self.saved.revision,
                "tournaments": [
                    searched_tournament,
                    pasted_tournament,
                ],
            },
        )
        self.assertEqual(draft.status_code, 200)

        chronologically_ordered_draft = self.client.get("/configuration")
        draft_page = chronologically_ordered_draft.get_data(as_text=True)
        self.assertLess(
            draft_page.index("January tournament"),
            draft_page.index("March tournament"),
        )

        removed = self.client.put(
            "/api/v1/configuration/tournaments/draft",
            json={
                "revision": self.saved.revision,
                "tournaments": [pasted_tournament],
            },
        )
        self.assertEqual(removed.status_code, 200)
        removed_page = self.client.get("/configuration").get_data(as_text=True)
        self.assertIn("January tournament", removed_page)
        self.assertNotIn("March tournament", removed_page)

        save = self.client.post(
            "/api/v1/configuration/tournaments",
            json={
                "revision": self.saved.revision,
                "tournament_ids": [300, 200],
            },
        )

        self.assertEqual(save.status_code, 200)
        saved_data = save.get_json()["data"]
        self.assertEqual(saved_data["tournament_ids"], [200, 300])
        self.assertTrue(saved_data["changed"])
        self.assertEqual(
            load_configuration(self.state_directory).default_tournament_ids,
            (200, 300),
        )

        reloaded_page = self.client.get("/configuration").get_data(
            as_text=True
        )
        self.assertLess(
            reloaded_page.index("January tournament"),
            reloaded_page.index("March tournament"),
        )

        stale_save = self.client.post(
            "/api/v1/configuration/tournaments",
            json={
                "revision": self.saved.revision,
                "tournament_ids": [300],
            },
        )
        self.assertEqual(stale_save.status_code, 409)
        self.assertEqual(
            stale_save.get_json()["error"]["code"],
            "stale_configuration",
        )

        current_revision = saved_data["revision"]
        group_lookup = self.client.get("/api/v1/tournaments/9301")
        group_save = self.client.post(
            "/api/v1/configuration/tournaments",
            json={
                "revision": current_revision,
                "tournament_ids": [9301],
            },
        )
        unverified_save = self.client.post(
            "/api/v1/configuration/tournaments",
            json={
                "revision": current_revision,
                "tournament_ids": [9999],
            },
        )
        self.assertEqual(group_lookup.status_code, 422)
        self.assertEqual(group_save.status_code, 422)
        self.assertEqual(unverified_save.status_code, 422)
        self.assertEqual(
            load_configuration(self.state_directory).default_tournament_ids,
            (200, 300),
        )

        self.member_client.search_unavailable = True
        failed_search = self.client.get(
            "/api/v1/tournaments/search?q=offline"
        )
        self.assertEqual(failed_search.status_code, 502)

        lookup_count = len(self.member_client.lookup_ids)
        unchanged_save = self.client.post(
            "/api/v1/configuration/tournaments",
            json={
                "revision": current_revision,
                "tournament_ids": [200, 300],
            },
        )
        self.assertEqual(unchanged_save.status_code, 200)
        self.assertFalse(unchanged_save.get_json()["data"]["changed"])
        self.assertEqual(len(self.member_client.lookup_ids), lookup_count)

        self.member_client.lookup_unavailable = True
        unavailable_changed_save = self.client.post(
            "/api/v1/configuration/tournaments",
            json={
                "revision": current_revision,
                "tournament_ids": [300],
            },
        )
        self.assertEqual(unavailable_changed_save.status_code, 502)
        self.assertEqual(
            load_configuration(self.state_directory).default_tournament_ids,
            (200, 300),
        )


if __name__ == "__main__":
    unittest.main()
