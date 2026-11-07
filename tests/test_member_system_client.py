from datetime import date
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

import requests

from flickornas_standings.member_system_client import (
    CanonicalClub,
    ClubId,
    MemberSystemClient,
    PlayerId,
    PlayerInfo,
    TournamentResolutionError,
    UpstreamDataError,
    UpstreamRetryExhausted,
)


FIXTURES = Path(__file__).parent / "fixtures" / "member_system"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self.payload = payload
        self.json_error = json_error

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class MemberSystemClientPolicyTests(unittest.TestCase):
    def make_client(self, effects, **kwargs):
        session = Mock()
        session.get.side_effect = effects
        client = MemberSystemClient(
            session=session,
            max_attempts=kwargs.pop("max_attempts", 3),
            backoff_seconds=0,
            **kwargs,
        )
        return client, session

    def test_connection_and_response_timeouts_are_always_supplied(self):
        client, session = self.make_client(
            [FakeResponse(payload=fixture("rating-list.json"))],
            connect_timeout=1.5,
            response_timeout=8.0,
        )

        client.district_rating_list(5821, date(2026, 5, 30))

        session.get.assert_called_once_with(
            "https://member.schack.se/public/api/v1/ratinglist/district/5821/"
            "date/2026-05-30/ratingtype/1/category/0",
            timeout=(1.5, 8.0),
        )

    def test_timeout_is_retried_then_succeeds(self):
        client, session = self.make_client(
            [
                requests.Timeout("slow"),
                FakeResponse(payload=fixture("clubs.json")),
            ]
        )

        clubs = client.district_clubs(5821)

        self.assertEqual(clubs[0].club_id, 10)
        self.assertEqual(session.get.call_count, 2)

    def test_network_retry_exhaustion_names_the_stage_and_attempts(self):
        client, session = self.make_client(
            [requests.ConnectionError("offline")] * 3
        )

        with self.assertRaisesRegex(
            UpstreamRetryExhausted,
            r"fetching district club list.*exhausted 3 attempts",
        ):
            client.district_clubs(5821)

        self.assertEqual(session.get.call_count, 3)

    def test_429_and_5xx_are_retried(self):
        client, session = self.make_client(
            [
                FakeResponse(status_code=429),
                FakeResponse(status_code=503),
                FakeResponse(payload=fixture("clubs.json")),
            ]
        )

        client.district_clubs(5821)

        self.assertEqual(session.get.call_count, 3)

    def test_retryable_status_exhaustion_is_actionable(self):
        client, _ = self.make_client([FakeResponse(status_code=503)] * 3)

        with self.assertRaisesRegex(
            UpstreamRetryExhausted,
            r"fetching district club list.*HTTP 503.*exhausted 3 attempts",
        ):
            client.district_clubs(5821)

    def test_404_is_not_retried(self):
        client, session = self.make_client([FakeResponse(status_code=404)])

        with self.assertRaisesRegex(
            TournamentResolutionError,
            r"tournament 999 cannot be resolved: not found",
        ):
            client.canonical_tournament(999)

        self.assertEqual(session.get.call_count, 1)

    def test_invalid_json_is_not_retried(self):
        client, session = self.make_client(
            [FakeResponse(json_error=ValueError("bad json"))]
        )

        with self.assertRaisesRegex(
            UpstreamDataError,
            r"fetching district club list.*not valid JSON",
        ):
            client.district_clubs(5821)

        self.assertEqual(session.get.call_count, 1)

    def test_malformed_shape_names_contract_stage(self):
        client, session = self.make_client(
            [FakeResponse(payload=[{"name": "Missing id"}])]
        )

        with self.assertRaisesRegex(
            UpstreamDataError,
            r"fetching district club list.*missing required field.*id",
        ):
            client.district_clubs(5821)

        self.assertEqual(session.get.call_count, 1)


class MemberSystemClientContractTests(unittest.TestCase):
    def make_client(self, payload):
        session = Mock()
        session.get.return_value = FakeResponse(payload=payload)
        return MemberSystemClient(
            session=session, max_attempts=1, backoff_seconds=0
        ), session

    def test_all_member_system_contracts_have_validated_methods(self):
        calls = [
            (
                "district rating list",
                "rating-list.json",
                lambda client: client.district_rating_list(
                    5821, date(2026, 5, 30)
                ),
            ),
            (
                "district club list",
                "clubs.json",
                lambda client: client.district_clubs(5821),
            ),
            (
                "group table",
                "group-table.json",
                lambda client: client.group_table(7001),
            ),
            (
                "round results",
                "round-results.json",
                lambda client: client.group_round_results(7001),
            ),
            (
                "tournament search",
                "tournament-search.json",
                lambda client: client.tournament_group_search("Flick DM"),
            ),
            (
                "player search",
                "player-search.json",
                lambda client: client.player_name_search("Ada", "Lovelace"),
            ),
        ]

        for label, fixture_name, invoke in calls:
            with self.subTest(contract=label):
                client, _ = self.make_client(fixture(fixture_name))
                self.assertTrue(invoke(client))

    def test_district_clubs_are_canonical_typed_values(self):
        client, session = self.make_client(fixture("clubs.json"))

        clubs = client.district_clubs(5821)

        self.assertEqual(
            clubs,
            [
                CanonicalClub(
                    club_id=ClubId(10),
                    name="Stockholms SK",
                ),
                CanonicalClub(
                    club_id=ClubId(20),
                    name="Farsta SK",
                ),
            ],
        )
        self.assertTrue(
            session.get.call_args.args[0].endswith(
                "/organisation/district/clubs/5821"
            )
        )

    def test_empty_district_club_list_is_successful(self):
        client, _ = self.make_client(fixture("clubs-empty.json"))

        self.assertEqual(client.district_clubs(5821), [])

    def test_malformed_district_club_is_rejected(self):
        client, _ = self.make_client(fixture("clubs-malformed.json"))

        with self.assertRaisesRegex(
            UpstreamDataError,
            r"fetching district club list.*club name.*non-empty string",
        ):
            client.district_clubs(5821)

    def test_player_search_returns_validated_identity_and_encodes_names(self):
        client, session = self.make_client(fixture("player-search.json"))

        players = client.player_name_search("My", "Ek Lund")

        self.assertEqual(
            players,
            [
                PlayerInfo(
                    player_id=PlayerId(123),
                    first_name="Ada",
                    last_name="Lovelace",
                    birth_year=2015,
                    current_club_id=ClubId(10),
                    current_club_name="Stockholms SK",
                    country="SWE",
                    fide_id=1700000,
                )
            ],
        )
        self.assertTrue(
            session.get.call_args.args[0].endswith(
                "/player/fornamn/My/efternamn/Ek%20Lund"
            )
        )

    def test_empty_player_search_is_successful(self):
        client, _ = self.make_client(fixture("player-search-empty.json"))

        self.assertEqual(client.player_name_search("My", "Ek"), [])

    def test_malformed_player_search_result_is_rejected(self):
        client, _ = self.make_client(
            fixture("player-search-malformed.json")
        )

        with self.assertRaisesRegex(
            UpstreamDataError,
            r"searching players by name.*missing required field.*lastName",
        ):
            client.player_name_search("My", "Ek")

    def test_failed_player_search_preserves_upstream_failure(self):
        session = Mock()
        session.get.side_effect = [
            FakeResponse(status_code=503),
            FakeResponse(status_code=503),
        ]
        client = MemberSystemClient(
            session=session,
            max_attempts=2,
            backoff_seconds=0,
        )

        with self.assertRaisesRegex(
            UpstreamRetryExhausted,
            r"searching players by name.*HTTP 503.*exhausted 2 attempts",
        ):
            client.player_name_search("My", "Ek")

    def test_player_birthdate_is_normalized_from_iso_date_time(self):
        payload = fixture("player-search.json")
        payload[0]["birthdate"] = "2015-04-12T00:00:00Z"
        client, _ = self.make_client(payload)

        player = client.player_name_search("Ada", "Lovelace")[0]

        self.assertEqual(player.birth_year, 2015)

    def test_current_player_club_does_not_constrain_canonical_club_list(self):
        player_client, _ = self.make_client(fixture("player-search.json"))
        club_client, _ = self.make_client(fixture("clubs.json"))

        player = player_client.player_name_search("Ada", "Lovelace")[0]
        clubs = club_client.district_clubs(5821)

        self.assertEqual(player.current_club_id, 10)
        self.assertIn(
            CanonicalClub(club_id=ClubId(20), name="Farsta SK"),
            clubs,
        )

    def test_search_path_segments_are_url_encoded(self):
        client, session = self.make_client(fixture("tournament-search.json"))

        results = client.tournament_group_search("Flick DM/Final")

        called_url = session.get.call_args.args[0]
        self.assertTrue(called_url.endswith("/Flick%20DM%2FFinal"))
        self.assertEqual(results[0].matching_group_id, 7001)
        self.assertEqual(results[0].tournament_id, 6336)
        self.assertEqual(results[0].matching_group_name, "Klass A")
        self.assertEqual(
            results[0].tournament_name,
            "Flickornas testturnering",
        )

    def test_empty_tournament_search_is_a_successful_empty_result(self):
        client, _ = self.make_client(fixture("tournament-search-empty.json"))

        self.assertEqual(client.tournament_group_search("saknas"), [])

    def test_malformed_tournament_search_result_is_rejected(self):
        client, _ = self.make_client(
            fixture("tournament-search-malformed.json")
        )

        with self.assertRaisesRegex(
            UpstreamDataError,
            r"searching tournament groups.*missing required field.*tournamentname",
        ):
            client.tournament_group_search("Flick")

    def test_failed_tournament_search_preserves_upstream_failure(self):
        session = Mock()
        session.get.side_effect = [
            FakeResponse(status_code=503),
            FakeResponse(status_code=503),
        ]
        client = MemberSystemClient(
            session=session,
            max_attempts=2,
            backoff_seconds=0,
        )

        with self.assertRaisesRegex(
            UpstreamRetryExhausted,
            r"searching tournament groups.*HTTP 503.*exhausted 2 attempts",
        ):
            client.tournament_group_search("Flick")

    def test_canonical_tournament_validates_and_identifies_processable_groups(
        self,
    ):
        client, _ = self.make_client(fixture("tournament-6336.json"))

        tournament = client.canonical_tournament(6336)

        self.assertEqual(tournament.tournament_id, 6336)
        self.assertEqual(tournament.name, "Flickornas testturnering")
        self.assertEqual(tournament.start_date, date(2026, 1, 10))
        self.assertEqual(tournament.end_date, date(2026, 1, 10))
        self.assertEqual(
            [
                (group.group_id, group.name, group.klass)
                for group in tournament.processable_groups
            ],
            [(7001, "Klass A", "a")],
        )

    def test_unknown_canonical_tournament_is_unresolvable(self):
        client, session = self.make_client(None)
        session.get.return_value = FakeResponse(status_code=404)

        with self.assertRaisesRegex(
            TournamentResolutionError,
            r"tournament 999 cannot be resolved: not found",
        ):
            client.canonical_tournament(999)

        self.assertEqual(session.get.call_count, 1)

    def test_canonical_tournament_without_processable_group_is_rejected(self):
        client, _ = self.make_client(
            fixture("tournament-no-processable-groups.json")
        )

        with self.assertRaisesRegex(
            TournamentResolutionError,
            r"tournament 6444.*no processable Flickornas group",
        ):
            client.canonical_tournament(6444)

    def test_canonical_compatibility_matches_generation_root_class_scope(self):
        client, _ = self.make_client(
            fixture("tournament-compatible-secondary-root.json")
        )

        with self.assertRaisesRegex(
            TournamentResolutionError,
            r"tournament 6555.*no processable Flickornas group",
        ):
            client.canonical_tournament(6555)

    def test_malformed_canonical_tournament_is_rejected(self):
        malformed = fixture("tournament-6336.json")
        malformed["end"] = "not-a-date"
        client, _ = self.make_client(malformed)

        with self.assertRaisesRegex(
            UpstreamDataError,
            r"resolving canonical tournament 6336.*tournament end.*ISO date",
        ):
            client.canonical_tournament(6336)

    def test_canonical_tournament_rejects_a_malformed_group(self):
        malformed = fixture("tournament-6336.json")
        del malformed["rootClasses"][0]["groups"][0]["name"]
        client, _ = self.make_client(malformed)

        with self.assertRaisesRegex(
            UpstreamDataError,
            r"resolving canonical tournament 6336.*tournament group.*name",
        ):
            client.canonical_tournament(6336)

    def test_failed_canonical_lookup_preserves_upstream_failure(self):
        session = Mock()
        session.get.return_value = FakeResponse(status_code=503)
        client = MemberSystemClient(
            session=session,
            max_attempts=1,
            backoff_seconds=0,
        )

        with self.assertRaisesRegex(
            UpstreamRetryExhausted,
            r"resolving canonical tournament 6336.*HTTP 503",
        ):
            client.canonical_tournament(6336)

    def test_latest_canonical_end_date_drives_rating_list_request(self):
        early = fixture("tournament-6336.json")
        early["id"] = 11
        early["end"] = "2026-04-02"
        late = fixture("tournament-6336.json")
        late["id"] = 22
        late["end"] = "2026-11-08"
        payloads = [early, late, fixture("rating-list.json")]
        session = Mock()
        session.get.side_effect = [
            FakeResponse(payload=payload) for payload in payloads
        ]
        client = MemberSystemClient(
            session=session, max_attempts=1, backoff_seconds=0
        )
        tournaments = [
            client.canonical_tournament(tournament_id)
            for tournament_id in (11, 22)
        ]
        rating_date = max(tournament.end_date for tournament in tournaments)
        client.district_rating_list(5821, rating_date)

        self.assertEqual(rating_date, date(2026, 11, 8))
        rating_url = session.get.call_args_list[-1].args[0]
        self.assertIn("/date/2026-11-08/", rating_url)


if __name__ == "__main__":
    unittest.main()
