from __future__ import annotations

from datetime import UTC, date, datetime
import json
from pathlib import Path
import tempfile
import unittest

from flickornas_standings.active_configuration import (
    ActiveConfiguration,
    LayoutConfiguration,
    load_configuration,
    save_configuration,
)
from flickornas_standings.web import create_app
from flickornas_standings.calendar_year import (
    DefaultTournamentYearError,
    TournamentYearState,
    assess_tournament_years,
    require_current_default_tournaments,
    stockholm_today,
)
from flickornas_standings.member_system_client import (
    CanonicalTournament,
    ProcessableTournamentGroup,
    TournamentGroupId,
    TournamentId,
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
                group_id=TournamentGroupId(1000 + tournament_id),
                name="Flickor",
                klass="F",
            ),
        ),
    )


class MutableClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def __call__(self) -> datetime:
        return self.instant


class RolloverMemberClient:
    def __init__(self) -> None:
        self.tournaments = {
            100: _tournament(100, "Saved 2026 tournament", date(2026, 10, 1)),
            200: _tournament(200, "January 2027 tournament", date(2027, 1, 9)),
            300: _tournament(300, "Saved 2025 tournament", date(2025, 11, 1)),
            400: _tournament(400, "Future tournament", date(2028, 2, 1)),
        }

    def canonical_tournament(self, tournament_id: int) -> CanonicalTournament:
        return self.tournaments[tournament_id]


class StockholmCalendarTests(unittest.TestCase):
    def test_year_changes_at_stockholm_midnight(self):
        self.assertEqual(
            stockholm_today(
                lambda: datetime(2026, 12, 31, 22, 59, tzinfo=UTC)
            ),
            date(2026, 12, 31),
        )
        self.assertEqual(
            stockholm_today(
                lambda: datetime(2026, 12, 31, 23, 0, tzinfo=UTC)
            ),
            date(2027, 1, 1),
        )

    def test_default_generation_requires_one_current_start_year(self):
        cases = (
            ((date(2026, 1, 1),), TournamentYearState.STALE),
            (
                (date(2026, 1, 1), date(2027, 1, 1)),
                TournamentYearState.MIXED,
            ),
            ((date(2028, 1, 1),), TournamentYearState.FUTURE),
        )
        for dates, expected_state in cases:
            with self.subTest(expected_state=expected_state):
                assessment = assess_tournament_years(dates, 2027)
                self.assertEqual(assessment.state, expected_state)
                with self.assertRaises(DefaultTournamentYearError):
                    require_current_default_tournaments(assessment)

        current = assess_tournament_years(
            (date(2027, 1, 1), date(2027, 11, 1)),
            2027,
        )
        require_current_default_tournaments(current)


class CalendarRolloverJourneyTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.state_directory = root / "state"
        self.layout = LayoutConfiguration(
            landscape_starts_at=12,
            base_side_margin_cm=0.9,
            margin_reduction_starts_after=6,
            margin_reduction_per_tournament_cm=0.04,
            minimum_side_margin_cm=0.55,
        )
        self.saved = save_configuration(
            self.state_directory,
            ActiveConfiguration(
                default_tournament_ids=(100,),
                contributor={
                    "name": "Test Contributor",
                    "email": "test@example.com",
                },
                known_local_players={"42": "Wasa SK"},
                layout=self.layout,
                club_display_names={"Stockholms Schacksällskap": "SSS"},
                finals_separators=(8, 16),
            ),
        )
        self.clock = MutableClock(
            datetime(2026, 12, 31, 22, 59, tzinfo=UTC)
        )
        self.member_client = RolloverMemberClient()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "calendar-rollover-tests",
                "STATE_DIRECTORY": self.state_directory,
                "OUTPUT_DIRECTORY": root / "output",
                "MEMBER_SYSTEM_CLIENT": self.member_client,
                "CLOCK": self.clock,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_open_page_crossing_new_year_uses_server_clock_again(self):
        december_page = self.client.get("/configuration?lang=en")
        self.assertNotIn(
            "Start 2027 season",
            december_page.get_data(as_text=True),
        )

        self.clock.instant = datetime(2026, 12, 31, 23, 0, tzinfo=UTC)
        january_page = self.client.get("/configuration?lang=en")
        self.assertIn(
            "Start 2027 season",
            january_page.get_data(as_text=True),
        )
        self.assertEqual(
            load_configuration(self.state_directory).club_display_names,
            self.saved.club_display_names,
        )
        self.assertIn(
            json.dumps(dict(self.saved.club_display_names)),
            january_page.get_data(as_text=True),
        )

        started = self.client.post(
            "/api/v1/configuration/tournaments/rollover",
            json={"revision": self.saved.revision},
        )
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.get_json()["data"]["rollover_year"], 2027)

    def test_rollover_replaces_only_tournaments_after_verified_save(self):
        self.clock.instant = datetime(2026, 12, 31, 23, 0, tzinfo=UTC)
        configuration_path = self.state_directory / "active-configuration.toml"
        before_start = configuration_path.read_bytes()

        started = self.client.post(
            "/api/v1/configuration/tournaments/rollover",
            json={"revision": self.saved.revision},
        )
        self.assertEqual(started.status_code, 200)
        self.assertEqual(configuration_path.read_bytes(), before_start)

        active_page = self.client.get("/configuration?lang=en").get_data(
            as_text=True
        )
        self.assertIn("Choose at least one verified 2027 tournament", active_page)
        self.assertIn("Cancel new season", active_page)
        self.assertNotIn("Saved 2026 tournament", active_page)
        self.assertIn('data-rollover-active="true"', active_page)
        self.assertRegex(
            active_page,
            r'<button(?=[^>]*data-generation-open)(?=[^>]*disabled)[^>]*>',
        )

        rejected_empty = self.client.post(
            "/api/v1/configuration/tournaments",
            json={"revision": self.saved.revision, "tournament_ids": []},
        )
        self.assertEqual(rejected_empty.status_code, 400)

        rejected_old = self.client.post(
            "/api/v1/configuration/tournaments",
            json={"revision": self.saved.revision, "tournament_ids": [100]},
        )
        self.assertEqual(rejected_old.status_code, 422)
        self.assertEqual(
            rejected_old.get_json()["error"]["code"],
            "invalid_rollover_tournament_year",
        )

        selected = self.member_client.tournaments[200]
        draft = self.client.put(
            "/api/v1/configuration/tournaments/draft",
            json={
                "revision": self.saved.revision,
                "tournaments": [
                    {
                        "tournament_id": 200,
                        "name": selected.name,
                        "start_date": selected.start_date.isoformat(),
                        "end_date": selected.end_date.isoformat(),
                    }
                ],
            },
        )
        self.assertEqual(draft.status_code, 200)

        saved_response = self.client.post(
            "/api/v1/configuration/tournaments",
            json={"revision": self.saved.revision, "tournament_ids": [200]},
        )
        self.assertEqual(saved_response.status_code, 200)
        self.assertTrue(saved_response.get_json()["data"]["rollover_completed"])

        persisted = load_configuration(self.state_directory)
        self.assertEqual(persisted.default_tournament_ids, (200,))
        self.assertEqual(persisted.known_local_players, {"42": "Wasa SK"})
        self.assertEqual(persisted.contributor, self.saved.contributor)
        self.assertEqual(persisted.layout, self.layout)
        self.assertEqual(
            persisted.club_display_names,
            {"Stockholms Schacksällskap": "SSS"},
        )
        self.assertEqual(persisted.finals_separators, ())

        # A fresh session loads the retained names from persisted configuration.
        reloaded_page = self.app.test_client().get(
            "/configuration?lang=en"
        ).get_data(as_text=True)
        self.assertIn(
            json.dumps(dict(self.saved.club_display_names)),
            reloaded_page,
        )

    def test_tournament_save_without_rollover_keeps_finals_separators(self):
        self.clock.instant = datetime(2027, 1, 10, 10, 0, tzinfo=UTC)

        saved_response = self.client.post(
            "/api/v1/configuration/tournaments",
            json={"revision": self.saved.revision, "tournament_ids": [200]},
        )

        self.assertEqual(saved_response.status_code, 200)
        self.assertNotIn(
            "rollover_completed",
            saved_response.get_json()["data"],
        )
        self.assertEqual(
            load_configuration(self.state_directory).finals_separators,
            (8, 16),
        )

    def test_cancel_and_stale_revision_leave_saved_configuration_unchanged(self):
        self.clock.instant = datetime(2026, 12, 31, 23, 0, tzinfo=UTC)
        configuration_path = self.state_directory / "active-configuration.toml"
        before = configuration_path.read_bytes()

        stale = self.client.post(
            "/api/v1/configuration/tournaments/rollover",
            json={"revision": self.saved.revision + 1},
        )
        self.assertEqual(stale.status_code, 409)

        self.client.post(
            "/api/v1/configuration/tournaments/rollover",
            json={"revision": self.saved.revision},
        )
        cancelled = self.client.delete(
            "/api/v1/configuration/tournaments/rollover",
            json={"revision": self.saved.revision},
        )
        self.assertEqual(cancelled.status_code, 200)
        self.assertTrue(cancelled.get_json()["data"]["cancelled"])
        self.assertEqual(configuration_path.read_bytes(), before)
        restored_page = self.client.get("/configuration?lang=en").get_data(
            as_text=True
        )
        self.assertIn("Saved 2026 tournament", restored_page)

    def test_mixed_and_future_tournament_defaults_are_not_saved(self):
        self.clock.instant = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
        before = load_configuration(self.state_directory)
        cases = (
            ([100, 200], "mixed_tournament_years"),
            ([400], "future_tournament_year"),
        )
        for tournament_ids, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                response = self.client.post(
                    "/api/v1/configuration/tournaments",
                    json={
                        "revision": self.saved.revision,
                        "tournament_ids": tournament_ids,
                    },
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(
                    response.get_json()["error"]["code"],
                    expected_code,
                )
                self.assertEqual(
                    load_configuration(self.state_directory),
                    before,
                )

    def test_rollover_action_remains_available_after_january(self):
        self.clock.instant = datetime(2027, 8, 1, 10, 0, tzinfo=UTC)

        page = self.client.get("/configuration?lang=sv").get_data(as_text=True)

        self.assertIn("Starta säsongen 2027", page)


if __name__ == "__main__":
    unittest.main()
