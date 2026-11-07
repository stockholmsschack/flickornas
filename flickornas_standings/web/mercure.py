"""Best-effort publication of generation transitions through Mercure."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from concurrent.futures import Executor, ThreadPoolExecutor
import hashlib
import hmac
import json
import threading
from typing import Any

import requests

from .generation_operations import OperationTransition, TOPIC_PREFIX


class DisabledOperationPublisher:
    """Keep generation independent of an unavailable Mercure deployment."""

    def publish(self, *_args: Any, **_kwargs: Any) -> None:
        return


class MercurePublisher:
    """Send bounded, fire-and-forget Mercure updates."""

    _DIGESTS = {
        "HS256": hashlib.sha256,
        "HS384": hashlib.sha384,
        "HS512": hashlib.sha512,
    }

    def __init__(
        self,
        hub_url: str,
        jwt_secret: str,
        *,
        algorithm: str = "HS256",
        executor: Executor | None = None,
        session: requests.Session | None = None,
        queue_limit: int = 64,
    ) -> None:
        if algorithm not in self._DIGESTS:
            raise ValueError(f"unsupported Mercure JWT algorithm: {algorithm}")
        if not jwt_secret:
            raise ValueError("Mercure publisher JWT secret must not be empty")
        self.hub_url = hub_url
        self.jwt_secret = jwt_secret
        self.algorithm = algorithm
        self._executor = executor or ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="flickornas-mercure",
        )
        self._session = session or requests.Session()
        self._capacity = threading.BoundedSemaphore(queue_limit)

    def publish(
        self,
        topic: str,
        operation_id: str,
        status_url: str,
        transition: OperationTransition,
        operation_data: dict[str, Any],
    ) -> None:
        self._validate_topic(topic, operation_id)
        update = {
            "kind": transition.kind,
            "event_id": transition.event_id,
            "data": {
                "operation_id": operation_id,
                "status_url": status_url,
                "state": operation_data["state"],
                "terminal": operation_data["terminal"],
                "message_key": transition.message_key,
                "parameters": transition.parameters,
                "progress": transition.progress,
                "run_id": operation_data.get("run_id"),
                "links": operation_data.get("links", {}),
                "failure_stage": operation_data.get("failure_stage"),
            },
        }
        form = {
            "topic": topic,
            "id": str(transition.event_id),
            "data": json.dumps(
                update,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
        token = self._publisher_token(topic)
        if not self._capacity.acquire(blocking=False):
            return
        try:
            self._executor.submit(self._send, form, token)
        except Exception:
            self._capacity.release()

    def _send(self, form: dict[str, str], token: str) -> None:
        try:
            response = self._session.post(
                self.hub_url,
                data=form,
                headers={"Authorization": f"Bearer {token}"},
                timeout=(0.3, 1.0),
            )
            response.raise_for_status()
        except Exception:
            # Operation files are authoritative; notification loss is expected.
            pass
        finally:
            self._capacity.release()

    def _publisher_token(self, topic: str) -> str:
        header = {"alg": self.algorithm, "typ": "JWT"}
        claims = {"mercure": {"publish": [topic]}}
        encoded_header = _base64_json(header)
        encoded_claims = _base64_json(claims)
        signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
        signature = hmac.new(
            self.jwt_secret.encode("utf-8"),
            signing_input,
            self._DIGESTS[self.algorithm],
        ).digest()
        return f"{encoded_header}.{encoded_claims}.{_base64_url(signature)}"

    @staticmethod
    def _validate_topic(topic: str, operation_id: str) -> None:
        expected = f"{TOPIC_PREFIX}/{operation_id}"
        if topic != expected:
            raise ValueError("Mercure topic is outside the operation namespace")


def _base64_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return _base64_url(encoded)


def _base64_url(value: bytes) -> str:
    return urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
