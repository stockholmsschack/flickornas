from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import tempfile
import unittest

from flickornas_standings.active_configuration import ActiveConfiguration, save_configuration
from flickornas_standings.web import create_app
from flickornas_standings.web.generation_operations import (
    GenerationBusyError,
    GenerationOperation,
    OperationStore,
    OperationTransition,
)
from flickornas_standings.member_system_client import (
    CanonicalTournament,
    ProcessableTournamentGroup,
    TournamentGroupId,
    TournamentId,
)


class ImmediateExecutor:
    def submit(self, function, *args):
        function(*args)
        return SimpleNamespace()


class DeferredExecutor:
    def __init__(self) -> None:
        self.pending = []

    def submit(self, function, *args):
        self.pending.append((function, args))
        return SimpleNamespace()

    def run_next(self) -> None:
        function, args = self.pending.pop(0)
        function(*args)


class RejectingExecutor:
    def submit(self, _function, *_args):
        raise RuntimeError("executor unavailable")


class OperationMemberClient:
    def canonical_tournament(self, tournament_id: int) -> CanonicalTournament:
        return CanonicalTournament(
            tournament_id=TournamentId(tournament_id),
            name="January tournament",
            start_date=date(2026, 1, 10),
            end_date=date(2026, 1, 10),
            processable_groups=(
                ProcessableTournamentGroup(
                    group_id=TournamentGroupId(tournament_id + 1000),
                    name="Flickor",
                    klass="F",
                ),
            ),
        )


class RecordingRunner:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls = 0
        self.inputs = []
        self.keyword_arguments = []

    def __call__(self, *arguments, progress, **keyword_arguments):
        self.calls += 1
        self.inputs.append(arguments[1])
        self.keyword_arguments.append(keyword_arguments)
        progress.begin_phase("Fetching tournaments", 2, "tournaments")
        progress.start("Fetching tournament 200")
        progress.complete()
        if self.failure is not None:
            raise self.failure
        progress.start("Publishing generation")
        progress.complete()
        partial = "-partial" if arguments[1].is_partial else ""
        return SimpleNamespace(
            run_id=f"run-{self.calls}",
            pdf_path=Path(
                f"flickornas-standings{partial}-20260701T120000Z.pdf"
            ),
        )


class GenerationOperationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.state_directory = self.root / "state"
        self.output_directory = self.root / "output"
        save_configuration(
            self.state_directory,
            ActiveConfiguration(
                default_tournament_ids=(200,),
                contributor={
                    "name": "Test Contributor",
                    "email": "test@example.com",
                },
            ),
        )
        self.member_client = OperationMemberClient()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def app(self, executor, runner, **configuration):
        return create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "generation-operation-tests",
                "STATE_DIRECTORY": self.state_directory,
                "OUTPUT_DIRECTORY": self.output_directory,
                "MEMBER_SYSTEM_CLIENT": self.member_client,
                "CLOCK": lambda: datetime(2026, 7, 1, 12, tzinfo=UTC),
                "GENERATION_EXECUTOR": executor,
                "GENERATION_RUNNER": runner,
                **configuration,
            }
        )

    def start(self, client):
        return client.post(
            "/api/v1/generation/operations",
            json={"year": None, "tournament_ids": None, "layout": "auto"},
        )

    def test_one_core_pass_persists_one_recoverable_terminal_outcome(self):
        runner = RecordingRunner()
        client = self.app(ImmediateExecutor(), runner).test_client()

        started = self.start(client)

        self.assertEqual(started.status_code, 202)
        accepted = started.get_json()["data"]
        self.assertEqual(accepted["state"], "accepted")
        self.assertEqual(accepted["latest_event_id"], 1)
        self.assertEqual(
            accepted["topic"],
            "https://stockholmsschack.se/flickornas/operations/"
            + accepted["operation_id"],
        )

        status = client.get(accepted["status_url"])
        operation = status.get_json()["data"]
        self.assertEqual(status.status_code, 200)
        self.assertEqual(operation["state"], "completed")
        self.assertEqual(operation["configuration_revision"], accepted["configuration_revision"])
        self.assertIsInstance(operation["configuration_revision"], int)
        self.assertTrue(operation["terminal"])
        self.assertEqual(operation["run_id"], "run-1")
        self.assertEqual(
            operation["links"]["pdf"],
            "http://flickornas.localhost:5000/downloads/"
            "run-1/flickornas-standings-20260701T120000Z.pdf",
        )
        self.assertEqual(
            operation["links"]["files"],
            "/downloads",
        )
        self.assertEqual(runner.calls, 1)
        event_ids = [event["event_id"] for event in operation["events"]]
        self.assertEqual(event_ids, list(range(1, len(event_ids) + 1)))
        self.assertEqual(
            [
                event["kind"]
                for event in operation["events"]
                if event["kind"] in {"completed", "failed"}
            ],
            ["completed"],
        )
        self.assertFalse(
            (self.state_directory / "operations" / "generation.lease").exists()
        )

        restarted_client = self.app(
            ImmediateExecutor(),
            RecordingRunner(),
        ).test_client()
        recovered = restarted_client.get(accepted["status_url"])
        self.assertEqual(recovered.get_json()["data"], operation)

    def test_path_only_file_origin_is_applied_once(self):
        client = self.app(
            ImmediateExecutor(),
            RecordingRunner(),
            FILES_PUBLIC_ORIGIN="/files/flickornas",
        ).test_client()

        status_url = self.start(client).get_json()["data"]["status_url"]

        self.assertEqual(
            client.get(status_url).get_json()["data"]["links"]["pdf"],
            "/files/flickornas/downloads/run-1/flickornas-standings-20260701T120000Z.pdf",
        )

    def test_saved_pre_7_6_links_are_upgraded_when_recovered(self):
        operations = self.state_directory / "operations"
        operations.mkdir(parents=True)
        operation_id = "1" * 32
        (operations / f"{operation_id}.json").write_text(
            """{
                "operation_id":"11111111111111111111111111111111",
                "topic":"topic",
                "status_url":"/status",
                "state":"completed",
                "effective_year":2025,
                "tournament_ids":[200],
                "is_partial":true,
                "layout":"auto",
                "latest_event_id":1,
                "terminal":true,
                "run_id":"old-run",
                "links":{"pdf":"/runs/old-run/pdf","runs":"/runs"},
                "events":[]
            }""",
            encoding="utf-8",
        )
        client = self.app(ImmediateExecutor(), RecordingRunner()).test_client()

        recovered = client.get(
            f"/api/v1/generation/operations/{operation_id}"
        ).get_json()["data"]

        self.assertEqual(
            recovered["links"],
            {
                "files": "/downloads",
                "pdf": "http://flickornas.localhost:5000/downloads/"
                "old-run/standings-partial.pdf",
            },
        )

    def test_flask_does_not_transfer_completed_pdf_contents(self):
        client = self.app(ImmediateExecutor(), RecordingRunner()).test_client()

        response = client.get("/downloads/downloadable-run/standings.pdf")

        self.assertEqual(response.status_code, 404)

    def test_concurrent_request_gets_active_operation_without_queueing(self):
        executor = DeferredExecutor()
        runner = RecordingRunner()
        client = self.app(executor, runner).test_client()

        first = self.start(client)
        second = self.start(client)

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 409)
        busy = second.get_json()["error"]
        self.assertEqual(busy["code"], "generation_busy")
        self.assertEqual(
            busy["details"]["active_operation_id"],
            first.get_json()["data"]["operation_id"],
        )
        self.assertEqual(len(executor.pending), 1)
        self.assertEqual(runner.calls, 0)

        executor.run_next()
        self.assertEqual(runner.calls, 1)
        self.assertEqual(
            client.get(first.get_json()["data"]["status_url"])
            .get_json()["data"]["state"],
            "completed",
        )

    def test_explicit_browser_inputs_start_a_partial_generation(self):
        runner = RecordingRunner()
        client = self.app(ImmediateExecutor(), runner).test_client()

        started = client.post(
            "/api/v1/generation/operations",
            json={
                "year": 2025,
                "tournament_ids": [200],
                "layout": "landscape",
            },
        )

        self.assertEqual(started.status_code, 202)
        accepted = started.get_json()["data"]
        completed = client.get(accepted["status_url"]).get_json()["data"]
        self.assertTrue(completed["is_partial"])
        self.assertEqual(completed["effective_year"], 2025)
        self.assertEqual(completed["tournament_ids"], [200])
        self.assertEqual(completed["layout"], "landscape")
        self.assertEqual(completed["state"], "completed")
        self.assertEqual(runner.calls, 1)

    def test_ui_locale_is_not_a_generation_input(self):
        runner = RecordingRunner()
        client = self.app(ImmediateExecutor(), runner).test_client()

        client.get("/?lang=en")
        english = self.start(client)
        client.get("/?lang=sv")
        swedish = self.start(client)

        self.assertEqual(english.status_code, 202)
        self.assertEqual(swedish.status_code, 202)
        self.assertEqual(runner.inputs[0], runner.inputs[1])
        for keyword_arguments in runner.keyword_arguments:
            self.assertNotIn("locale", keyword_arguments)
            self.assertNotIn("language", keyword_arguments)

    def test_failure_is_terminal_and_releases_lease_for_the_next_run(self):
        runner = RecordingRunner(RuntimeError("fixture renderer failed"))
        client = self.app(ImmediateExecutor(), runner).test_client()

        failed_start = self.start(client)
        failed = client.get(
            failed_start.get_json()["data"]["status_url"]
        ).get_json()["data"]

        self.assertEqual(failed["state"], "failed")
        self.assertTrue(failed["terminal"])
        self.assertEqual(failed["failure_stage"], "Fetching tournament 200")
        self.assertEqual(failed["events"][-1]["kind"], "failed")

        next_start = self.start(client)
        self.assertEqual(next_start.status_code, 202)
        self.assertNotEqual(
            next_start.get_json()["data"]["operation_id"],
            failed["operation_id"],
        )

    def test_scheduling_failure_is_durable_and_does_not_strand_lease(self):
        client = self.app(RejectingExecutor(), RecordingRunner()).test_client()

        response = self.start(client)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json()["error"]["code"],
            "generation_start_failed",
        )
        records = list((self.state_directory / "operations").glob("*.json"))
        self.assertEqual(len(records), 1)
        operation_id = records[0].stem
        status = client.get(
            f"/api/v1/generation/operations/{operation_id}"
        ).get_json()["data"]
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["failure_stage"], "scheduling")
        self.assertFalse(
            (self.state_directory / "operations" / "generation.lease").exists()
        )

    def test_another_process_keeps_its_lease_while_alive_and_loses_it_when_it_dies(self):
        for finished in (False, True):
            with self.subTest(finished=finished):
                store = OperationStore(self.state_directory)
                operation_id = ("c" if finished else "a") * 32
                store.create(GenerationOperation(
                    operation_id, "topic", "", "accepted", 2026, (), False, "auto", 1, False,
                    events=(OperationTransition(1, "accepted", "operations.accepted"),),
                ))
                if finished:
                    store.transition(operation_id, kind="completed", message_key="operations.completed")
                hold = (
                    "import sys, time; from flickornas_standings.web.generation_operations import OperationStore; "
                    "OperationStore(sys.argv[1]).acquire(sys.argv[2]); print('held', flush=True); time.sleep(60)"
                )
                owner = subprocess.Popen(
                    [sys.executable, "-c", hold, str(self.state_directory), operation_id],
                    stdout=subprocess.PIPE, text=True,
                )
                try:
                    self.assertEqual(owner.stdout.readline(), "held\n")
                    with self.assertRaisesRegex(GenerationBusyError, operation_id):
                        store.acquire("b" * 32)
                    self.assertEqual(store.load(operation_id).state, "completed" if finished else "accepted")
                finally:
                    owner.kill()
                    owner.communicate()

                store.acquire("b" * 32)
                self.assertEqual(store.load(operation_id).state, "completed" if finished else "failed")
                store.release("b" * 32)

    def test_invalid_request_creates_neither_operation_nor_lease(self):
        runner = RecordingRunner()
        client = self.app(ImmediateExecutor(), runner).test_client()

        response = client.post(
            "/api/v1/generation/operations",
            json={"year": "invalid", "tournament_ids": [], "layout": "wide"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(runner.calls, 0)
        operations = self.state_directory / "operations"
        self.assertFalse(operations.exists())

    def test_unknown_status_is_a_structured_not_found(self):
        client = self.app(ImmediateExecutor(), RecordingRunner()).test_client()
        response = client.get(
            "/api/v1/generation/operations/00000000000000000000000000000000"
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json()["error"]["code"],
            "operation_not_found",
        )


if __name__ == "__main__":
    unittest.main()
