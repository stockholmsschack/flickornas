from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from flickornas_standings.active_configuration import ActiveConfiguration, save_configuration
from flickornas_standings.web import create_app
from flickornas_standings.member_system_client import (
    CanonicalTournament,
    ProcessableTournamentGroup,
    TournamentGroupId,
    TournamentId,
    TournamentResolutionError,
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


class MutableClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def __call__(self) -> datetime:
        return self.instant


class GenerationMemberClient:
    def __init__(self) -> None:
        self.lookup_ids: list[int] = []
        self.tournaments = {
            100: _tournament(100, "March", date(2026, 3, 1)),
            200: _tournament(200, "January", date(2026, 1, 10)),
            300: _tournament(300, "January 2027", date(2027, 1, 9)),
            400: _tournament(400, "Old tournament", date(2025, 11, 1)),
        }

    def canonical_tournament(self, tournament_id: int) -> CanonicalTournament:
        self.lookup_ids.append(tournament_id)
        try:
            return self.tournaments[tournament_id]
        except KeyError as error:
            raise TournamentResolutionError(
                tournament_id,
                "not found",
            ) from error


class GenerationFormTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.state_directory = self.root / "state"
        self.output_directory = self.root / "output"
        self.saved = save_configuration(
            self.state_directory,
            ActiveConfiguration(
                default_tournament_ids=(200, 100),
                contributor={
                    "name": "Test Contributor",
                    "email": "test@example.com",
                },
                known_local_players={"42": "Wasa SK"},
            ),
        )
        self.clock = MutableClock(
            datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
        )
        self.member_client = GenerationMemberClient()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "generation-form-tests",
                "STATE_DIRECTORY": self.state_directory,
                "OUTPUT_DIRECTORY": self.output_directory,
                "MEMBER_SYSTEM_CLIENT": self.member_client,
                "CLOCK": self.clock,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_configuration_page_contains_localized_generation_dialog(self):
        response = self.client.get("/configuration?lang=en")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Generate standings", body)
        self.assertIn('value="2026"', body)
        self.assertIn("Choose tournaments for this run", body)
        self.assertIn('data-tournament-consumer="run"', body)
        self.assertIn('src="/static/js/generation-form.js"', body)
        self.assertIn('data-generation-open', body)
        self.assertIn('data-has-selected-tournaments="true"', body)
        self.assertIn(
            'data-start-endpoint="/api/v1/generation/operations"',
            body,
        )
        self.assertIn('data-mercure-hub="/.well-known/mercure"', body)
        self.assertIn("data-generation-announcement", body)
        self.assertIn("data-generation-submit-hint", body)
        self.assertIn('"generation.again": "Generate again"', body)
        self.assertIn(
            'class="modal-footer generation-modal-actions"',
            body,
        )
        self.assertIn(
            'class="btn btn-secondary generation-modal-cancel"',
            body,
        )
        self.assertIn(
            'class="btn btn-primary generation-modal-primary"',
            body,
        )

        source = (
            Path(__file__).parent.parent
            / "flickornas_standings/web/static/js/generation-form.js"
        ).read_text(encoding="utf-8")
        self.assertIn("data-generate-again", source)
        self.assertIn("@click=${startGeneration}", source)

    def test_browser_recovers_only_non_terminal_operations(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is not installed")

        completed = subprocess.run(
            [node, "tests/browser/generation-operation-memory.mjs"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_browser_compares_completed_generation_inputs(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is not installed")

        completed = subprocess.run(
            [node, "tests/browser/generation-input-state.mjs"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )

    def test_non_local_operator_cannot_see_or_submit_tournament_override(self):
        page = self.client.get(
            "/configuration?lang=en",
            base_url="https://standings.example",
        )
        body = page.get_data(as_text=True)

        self.assertEqual(page.status_code, 200)
        self.assertNotIn('id="generation-explicit-tournaments"', body)
        self.assertNotIn('data-tournament-consumer="run"', body)
        self.assertIn('aria-readonly="true"', body)

        self.member_client.lookup_ids.clear()
        response = self.client.post(
            "/api/v1/generation/inputs",
            json={
                "year": 2025,
                "tournament_ids": [400],
                "layout": "auto",
            },
            base_url="https://standings.example",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["error"]["code"],
            "generation_tournament_selection_forbidden",
        )
        self.assertEqual(self.member_client.lookup_ids, [])

        default_response = self.client.post(
            "/api/v1/generation/inputs",
            json={"year": None, "tournament_ids": None, "layout": "auto"},
            base_url="https://standings.example",
        )
        self.assertEqual(default_response.status_code, 200)

    def test_host_admin_capability_allows_non_local_tournament_override(self):
        self.app.extensions["flickornas"]["settings"][
            "GENERATION_TOURNAMENT_SELECTION_AUTHORIZER"
        ] = lambda: True

        page = self.client.get(
            "/configuration?lang=en",
            base_url="https://standings.example",
        )
        response = self.client.post(
            "/api/v1/generation/inputs",
            json={
                "year": 2025,
                "tournament_ids": [400],
                "layout": "auto",
            },
            base_url="https://standings.example",
        )

        self.assertIn(
            'id="generation-explicit-tournaments"',
            page.get_data(as_text=True),
        )
        self.assertNotIn(
            'aria-readonly="true"',
            page.get_data(as_text=True),
        )
        self.assertEqual(response.status_code, 200)

    def test_localhost_subdomain_can_select_tournaments(self):
        response = self.client.get(
            "/configuration?lang=en",
            base_url="http://flickornas.localhost:5000",
        )

        self.assertIn(
            'id="generation-explicit-tournaments"',
            response.get_data(as_text=True),
        )

    def test_defaults_use_saved_configuration_not_tournament_draft(self):
        drafted = self.member_client.tournaments[300]
        self.client.put(
            "/api/v1/configuration/tournaments/draft",
            json={
                "revision": self.saved.revision,
                "tournaments": [
                    {
                        "tournament_id": 300,
                        "name": drafted.name,
                        "start_date": drafted.start_date.isoformat(),
                        "end_date": drafted.end_date.isoformat(),
                    }
                ],
            },
        )

        response = self.client.get("/api/v1/generation/defaults")
        self.assertEqual(response.get_json()["data"]["configuration_revision"], self.saved.revision)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [
                tournament["tournament_id"]
                for tournament in response.get_json()["data"]["tournaments"]
            ],
            [200, 100],
        )
        with self.client.session_transaction() as session:
            self.assertEqual(
                session["flickornas.tournament_draft"]["tournaments"][0][
                    "tournament_id"
                ],
                300,
            )

    def test_resolves_full_and_partial_inputs_with_publication_defaults(self):
        full = self.client.post(
            "/api/v1/generation/inputs",
            json={"year": None, "tournament_ids": None, "layout": "auto"},
        )
        partial = self.client.post(
            "/api/v1/generation/inputs",
            json={
                "year": 2025,
                "tournament_ids": [100, 400, 200],
                "layout": "landscape",
            },
        )

        self.assertEqual(full.status_code, 200)
        self.assertEqual(
            full.get_json()["data"],
            {
                "inputs": {
                    "effective_year": 2026,
                    "tournament_ids": [200, 100],
                    "is_partial": False,
                    "layout": "auto",
                },
                "tournaments": [
                    {
                        "tournament_id": 200,
                        "name": "January",
                        "start_date": "2026-01-10",
                        "end_date": "2026-01-10",
                    },
                    {
                        "tournament_id": 100,
                        "name": "March",
                        "start_date": "2026-03-01",
                        "end_date": "2026-03-01",
                    },
                ],
                "publication": {"pdf": True, "json": True},
            },
        )
        self.assertEqual(partial.status_code, 200)
        partial_data = partial.get_json()["data"]
        self.assertEqual(
            partial_data["inputs"],
            {
                "effective_year": 2025,
                "tournament_ids": [400, 200, 100],
                "is_partial": True,
                "layout": "landscape",
            },
        )
        self.assertEqual(
            partial_data["publication"],
            {"pdf": False, "json": False},
        )
        self.assertFalse(self.output_directory.exists())
        self.assertFalse((self.state_directory / "runs").exists())

    def test_reports_all_structural_problems_before_upstream_requests(self):
        self.member_client.lookup_ids.clear()

        response = self.client.post(
            "/api/v1/generation/inputs",
            json={
                "year": "twenty twenty-six",
                "tournament_ids": [],
                "layout": ["square"],
            },
        )

        self.assertEqual(response.status_code, 422)
        problem_keys = {
            problem["message_key"]
            for problem in response.get_json()["error"]["details"]["problems"]
        }
        self.assertEqual(
            problem_keys,
            {
                "errors.generation.year",
                "errors.generation.layout",
                "errors.generation.tournaments_required",
            },
        )
        self.assertEqual(self.member_client.lookup_ids, [])

    def test_non_current_year_requires_explicit_tournaments(self):
        self.member_client.lookup_ids.clear()

        response = self.client.post(
            "/api/v1/generation/inputs",
            json={"year": 2025, "tournament_ids": None, "layout": "auto"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.member_client.lookup_ids, [])
        self.assertEqual(
            response.get_json()["error"]["details"]["problems"][0][
                "message_key"
            ],
            "errors.generation.non_current_tournaments",
        )

    def test_untouched_year_is_resolved_again_after_stockholm_midnight(self):
        page = self.client.get("/configuration?lang=en")
        self.assertIn('value="2026"', page.get_data(as_text=True))

        self.clock.instant = datetime(2026, 12, 31, 23, 0, tzinfo=UTC)
        response = self.client.post(
            "/api/v1/generation/inputs",
            json={"year": None, "tournament_ids": [300], "layout": "auto"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["data"]["inputs"]["effective_year"],
            2027,
        )

    def test_default_generation_rejects_stale_configured_tournaments(self):
        stale_state = self.root / "stale-state"
        save_configuration(
            stale_state,
            ActiveConfiguration(
                default_tournament_ids=(400,),
                contributor={
                    "name": "Test Contributor",
                    "email": "test@example.com",
                },
            ),
        )
        stale_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "stale-generation-form-tests",
                "STATE_DIRECTORY": stale_state,
                "OUTPUT_DIRECTORY": self.root / "stale-output",
                "MEMBER_SYSTEM_CLIENT": self.member_client,
                "CLOCK": self.clock,
            }
        )

        response = stale_app.test_client().post(
            "/api/v1/generation/inputs",
            json={"year": None, "tournament_ids": None, "layout": "auto"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.get_json()["error"]["details"]["problems"][0][
                "message_key"
            ],
            "errors.generation.defaults_stale",
        )


if __name__ == "__main__":
    unittest.main()
