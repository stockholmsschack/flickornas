"""Opt-in checks for the local shared Caddy Mercure hub."""

from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

import requests

from flickornas_standings.web.available_files import list_available_files
from flickornas_standings.web.generation_operations import OperationTransition, TOPIC_PREFIX
from flickornas_standings.web.mercure import MercurePublisher


RUN_INTEGRATION = os.getenv("RUN_CADDY_MERCURE_INTEGRATION") == "1"
HUB_URL = "http://127.0.0.1:5000/.well-known/mercure"
LOCAL_SECRET = "!ChangeThisMercureHubJWTSecretKey!"


@unittest.skipUnless(
    RUN_INTEGRATION,
    "set RUN_CADDY_MERCURE_INTEGRATION=1 with local caddy_mercure running",
)
class SharedCaddyMercureIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.publisher = MercurePublisher(HUB_URL, LOCAL_SECRET)
        self.session = requests.Session()
        self.session.trust_env = False

    def publish(self, topic: str, event_id: str, data: dict) -> None:
        token = self.publisher._publisher_token(topic)
        response = self.session.post(
            HUB_URL,
            data={
                "topic": topic,
                "id": event_id,
                "data": json.dumps(data, separators=(",", ":")),
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=2,
        )
        response.raise_for_status()

    def replay_after(self, topic: str, event_id: str) -> dict:
        with self.session.get(
            HUB_URL,
            params={"topic": topic, "lastEventID": event_id},
            headers={
                "Accept": "text/event-stream",
                "Host": "flickornas.localhost:5000",
                "Last-Event-ID": event_id,
                "Origin": "http://flickornas.localhost:5000",
            },
            stream=True,
            timeout=(2, 3),
        ) as response:
            response.raise_for_status()
            received_id = None
            received_data = None
            for line in response.iter_lines(decode_unicode=True, chunk_size=1):
                if line.startswith("id:"):
                    received_id = line.removeprefix("id:").strip()
                elif line.startswith("data:"):
                    received_data = json.loads(
                        line.removeprefix("data:").strip()
                    )
                elif line == "" and received_data is not None:
                    return {"id": received_id, "data": received_data}
        self.fail("Mercure stream ended without replaying an update")

    def test_same_origin_reconnect_and_playtime_topic_coexistence(self):
        suffix = uuid4().hex
        operation_id = uuid4().hex
        flickornas_topic = f"{TOPIC_PREFIX}/{operation_id}"
        playtime_topic = f"https://example.com/tournament/{suffix}/roster"
        first_id = f"urn:uuid:{suffix}:1"
        second_id = f"urn:uuid:{suffix}:2"
        playtime_id = f"urn:uuid:{suffix}:playtime"

        self.publish(
            flickornas_topic,
            first_id,
            {"kind": "progress", "event_id": 1},
        )
        self.publish(
            playtime_topic,
            playtime_id,
            {"event": "roster_changed"},
        )
        self.publish(
            flickornas_topic,
            second_id,
            {"kind": "completed", "event_id": 2},
        )

        recovered = self.replay_after(flickornas_topic, first_id)
        self.assertEqual(recovered["id"], second_id)
        self.assertEqual(recovered["data"]["kind"], "completed")
        self.assertNotIn("event", recovered["data"])

        playtime = self.replay_after(playtime_topic, first_id)
        self.assertEqual(playtime["id"], playtime_id)
        self.assertEqual(playtime["data"]["event"], "roster_changed")

    def test_generated_download_is_served_by_caddy_as_an_attachment(self):
        download_root = Path(
            os.getenv("FLICKORNAS_DOWNLOAD_ROOT", "output/runs")
        )
        available = list_available_files(download_root.parent)
        pdf = next(
            (
                item
                for item in available
                if item.label_key == "available_files.names.pdf"
            ),
            None,
        )
        self.assertIsNotNone(pdf, "generate a PDF before running this check")

        response = self.session.get(
            f"http://127.0.0.1:5000{pdf.download_url}",
            headers={"Host": "flickornas.localhost:5000"},
            timeout=3,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertEqual(
            response.headers.get("Content-Disposition"),
            "attachment",
        )

    def test_caddy_download_route_rejects_parent_traversal(self):
        response = self.session.get(
            "http://127.0.0.1:5000/downloads/%2e%2e/Caddyfile",
            headers={"Host": "flickornas.localhost:5000"},
            timeout=3,
        )

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
