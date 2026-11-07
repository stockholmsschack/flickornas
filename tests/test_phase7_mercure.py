from __future__ import annotations

from base64 import urlsafe_b64decode
from concurrent.futures import Executor
from datetime import UTC, date, datetime
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from flickornas_standings.active_configuration import ActiveConfiguration, save_configuration
from flickornas_standings.web import create_app
from flickornas_standings.web.generation_operations import OperationTransition, TOPIC_PREFIX
from flickornas_standings.web.mercure import MercurePublisher
from flickornas_standings.member_system_client import (
    CanonicalTournament,
    ProcessableTournamentGroup,
    TournamentGroupId,
    TournamentId,
)


class ImmediateExecutor(Executor):
    def submit(self, function, *args, **kwargs):
        function(*args, **kwargs)
        return SimpleNamespace()


class FakeResponse:
    def raise_for_status(self) -> None:
        return


class RecordingSession:
    def __init__(self) -> None:
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


class FailingPublisher:
    def publish(self, *_args, **_kwargs):
        raise RuntimeError("Mercure is unavailable")


class MemberClient:
    def canonical_tournament(self, tournament_id: int) -> CanonicalTournament:
        return CanonicalTournament(
            tournament_id=TournamentId(tournament_id),
            name="Mercure test tournament",
            start_date=date(2026, 4, 4),
            end_date=date(2026, 4, 4),
            processable_groups=(
                ProcessableTournamentGroup(
                    group_id=TournamentGroupId(tournament_id + 1000),
                    name="Flickor",
                    klass="F",
                ),
            ),
        )


class RecordingRunner:
    def __call__(self, *_args, progress, **_kwargs):
        progress.begin_phase("Fetching tournaments", 1, "tournaments")
        progress.complete()
        return SimpleNamespace(
            run_id="mercure-run",
            pdf_path=Path("standings-20260701T120000Z.pdf"),
        )


def decode_segment(segment: str):
    padding = "=" * (-len(segment) % 4)
    return json.loads(urlsafe_b64decode(segment + padding))


class MercurePublisherContractTests(unittest.TestCase):
    def setUp(self):
        self.session = RecordingSession()
        self.publisher = MercurePublisher(
            "http://127.0.0.1:5000/.well-known/mercure",
            "publisher-secret",
            executor=ImmediateExecutor(),
            session=self.session,
        )
        self.operation_id = "a" * 32
        self.topic = f"{TOPIC_PREFIX}/{self.operation_id}"
        self.transition = OperationTransition(
            event_id=7,
            kind="progress",
            message_key="operations.progress",
            parameters={"stage": "Fetching tournaments"},
            progress={"completed": 2, "total": 4, "unit": "tournaments"},
        )

    def test_posts_exact_topic_event_id_and_machine_readable_payload(self):
        self.publisher.publish(
            self.topic,
            self.operation_id,
            f"/api/v1/generation/operations/{self.operation_id}",
            self.transition,
            {
                "state": "running",
                "terminal": False,
                "run_id": None,
                "links": {},
                "failure_stage": None,
            },
        )

        self.assertEqual(len(self.session.calls), 1)
        url, request = self.session.calls[0]
        self.assertEqual(
            url,
            "http://127.0.0.1:5000/.well-known/mercure",
        )
        self.assertEqual(request["data"]["topic"], self.topic)
        self.assertEqual(request["data"]["id"], "7")
        payload = json.loads(request["data"]["data"])
        self.assertEqual(payload["kind"], "progress")
        self.assertEqual(payload["event_id"], 7)
        self.assertEqual(payload["data"]["progress"]["completed"], 2)
        self.assertNotIn("publisher-secret", request["data"]["data"])

    def test_bearer_jwt_grants_only_the_exact_flickornas_topic(self):
        self.publisher.publish(
            self.topic,
            self.operation_id,
            "/status",
            self.transition,
            {"state": "running", "terminal": False},
        )

        authorization = self.session.calls[0][1]["headers"]["Authorization"]
        self.assertTrue(authorization.startswith("Bearer "))
        token = authorization.removeprefix("Bearer ")
        header, claims, _signature = token.split(".")
        self.assertEqual(decode_segment(header)["alg"], "HS256")
        self.assertEqual(
            decode_segment(claims)["mercure"]["publish"],
            [self.topic],
        )

    def test_rejects_a_playtime_or_sibling_operation_topic(self):
        for topic in (
            "https://example.com/tournament/10/roster",
            f"{TOPIC_PREFIX}/{'b' * 32}",
        ):
            with self.subTest(topic=topic):
                with self.assertRaises(ValueError):
                    self.publisher.publish(
                        topic,
                        self.operation_id,
                        "/status",
                        self.transition,
                        {"state": "running", "terminal": False},
                    )
        self.assertEqual(self.session.calls, [])

    def test_browser_reconciles_initial_new_and_error_notifications(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is not installed")
        completed = subprocess.run(
            [node, "tests/browser/operation-stream.mjs"],
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


class BestEffortOperationTests(unittest.TestCase):
    def test_publish_failure_does_not_fail_or_duplicate_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save_configuration(
                root / "state",
                ActiveConfiguration(
                    default_tournament_ids=(200,),
                    contributor={"name": "Test", "email": "test@example.com"},
                ),
            )
            app = create_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": "mercure-test",
                    "STATE_DIRECTORY": root / "state",
                    "OUTPUT_DIRECTORY": root / "output",
                    "MEMBER_SYSTEM_CLIENT": MemberClient(),
                    "CLOCK": lambda: datetime(2026, 7, 1, 12, tzinfo=UTC),
                    "GENERATION_EXECUTOR": ImmediateExecutor(),
                    "GENERATION_RUNNER": RecordingRunner(),
                    "MERCURE_PUBLISHER": FailingPublisher(),
                    "MERCURE_PUBLIC_URL": "/local-mercure",
                    "MERCURE_JWT_SECRET": "must-not-reach-browser",
                }
            )
            client = app.test_client()

            page = client.get("/configuration?lang=en")
            self.assertIn('data-mercure-hub="/local-mercure"', page.text)
            self.assertNotIn("must-not-reach-browser", page.text)

            started = client.post(
                "/api/v1/generation/operations",
                json={"year": None, "tournament_ids": None, "layout": "auto"},
            )

            self.assertEqual(started.status_code, 202)
            operation = client.get(
                started.get_json()["data"]["status_url"]
            ).get_json()["data"]
            self.assertEqual(operation["state"], "completed")
            self.assertEqual(
                [event["kind"] for event in operation["events"]].count(
                    "completed"
                ),
                1,
            )


if __name__ == "__main__":
    unittest.main()
