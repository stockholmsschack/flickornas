"""Serialize operation events for SSE delivery and replay."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from types import MappingProxyType
from typing import Any, Literal, Mapping


OperationEventKind = Literal[
    "accepted",
    "stage",
    "progress",
    "completed",
    "failed",
]
OPERATION_EVENT_KINDS: tuple[OperationEventKind, ...] = (
    "accepted",
    "stage",
    "progress",
    "completed",
    "failed",
)
TERMINAL_EVENT_KINDS = frozenset({"completed", "failed"})
LAST_EVENT_ID_HEADER = "Last-Event-ID"


@dataclass(frozen=True)
class OperationEvent:
    """One immutable event retained for reconnect replay by numeric id."""

    event_id: int
    operation_id: str
    kind: OperationEventKind
    message_key: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    progress: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event_id < 1:
            raise ValueError("operation event ids start at 1")
        if self.kind not in OPERATION_EVENT_KINDS:
            raise ValueError(f"unsupported operation event kind: {self.kind}")
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(self.parameters)),
        )
        object.__setattr__(
            self,
            "progress",
            MappingProxyType(dict(self.progress)),
        )

    @property
    def terminal(self) -> bool:
        return self.kind in TERMINAL_EVENT_KINDS

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "message_key": self.message_key,
            "parameters": dict(self.parameters),
            "progress": dict(self.progress),
            "terminal": self.terminal,
        }

    def as_sse(self) -> str:
        """Serialize using id/event/data fields understood by EventSource."""
        payload = json.dumps(
            self.as_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return f"id: {self.event_id}\nevent: {self.kind}\ndata: {payload}\n\n"
