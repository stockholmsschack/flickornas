"""Durable, exclusive background generation operations."""

from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
import fcntl
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Callable, Protocol
from uuid import uuid4

from ..active_configuration import ActiveConfiguration
from ..atomic_write import atomic_create_text, atomic_replace_text
from ..artifact_publication import (
    PublishedGeneration,
    clear_downloads as clear_generated_downloads,
    generate_and_publish,
)
from ..generation_orchestrator import (
    GenerationStageError,
    KlassNamingError,
    ResolvedGenerationRequest,
)
from ..generation_progress import ProgressReporter
from ..member_system_client import MemberSystemClient

from .klass_naming import klass_naming_problems
from .available_files import generation_download_links, public_file_url


OPERATIONS_DIRECTORY = "operations"
LEASE_FILENAME = "generation.lease"
TOPIC_PREFIX = "https://stockholmsschack.se/flickornas/operations"


class TransitionPublisher(Protocol):
    def publish(
        self,
        topic: str,
        operation_id: str,
        status_url: str,
        transition: "OperationTransition",
        operation_data: dict[str, Any],
    ) -> None: ...


class GenerationBusyError(RuntimeError):
    """Raised when another generation owns the application lease."""

    def __init__(self, operation_id: str) -> None:
        self.operation_id = operation_id
        super().__init__(f"generation operation {operation_id} is active")


@dataclass(frozen=True)
class OperationTransition:
    event_id: int
    kind: str
    message_key: str
    parameters: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationOperation:
    operation_id: str
    topic: str
    status_url: str
    state: str
    effective_year: int
    tournament_ids: tuple[int, ...]
    is_partial: bool
    layout: str
    latest_event_id: int
    terminal: bool
    configuration_revision: int | None = None
    run_id: str | None = None
    links: dict[str, str] = field(default_factory=dict)
    failure_stage: str | None = None
    events: tuple[OperationTransition, ...] = ()
    actor: str | None = None

    def as_dict(self) -> dict[str, Any]:
        document = asdict(self)
        document["tournament_ids"] = list(self.tournament_ids)
        return document


class OperationStore:
    """Atomically persist operation state and the cross-request lease."""

    def __init__(
        self,
        state_directory: Path,
        publisher: TransitionPublisher | None = None,
        public_file_origin: str = "",
        url_prefix: str = "",
    ) -> None:
        self.directory = Path(state_directory) / OPERATIONS_DIRECTORY
        self._publisher = publisher
        self._public_file_origin = public_file_origin
        self._url_prefix = url_prefix
        self._lease_path = self.directory / LEASE_FILENAME
        self._held: dict[str, int] = {}
        self._lock = threading.RLock()

    def status_url(self, operation_id: str) -> str:
        return f"{self._url_prefix}/api/v1/generation/operations/{operation_id}"

    def acquire(self, operation_id: str) -> None:
        """Take the lease, recovering it first from an owner that is no longer running."""
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.directory, prefix=".lease-")
        try:
            # The kernel releases this lock if the owner process exits.
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.write(descriptor, f"{operation_id}\n".encode())
            os.fsync(descriptor)
            with self._lock:
                try:
                    os.link(temporary, self._lease_path)
                except FileExistsError:
                    self.recover()
                    os.link(temporary, self._lease_path)
                self._held[operation_id] = descriptor
        except FileExistsError as error:
            os.close(descriptor)
            raise GenerationBusyError(self._lease_owner() or "unknown") from error
        except BaseException:
            os.close(descriptor)
            raise
        finally:
            os.unlink(temporary)

    def recover(self) -> None:
        """Fail the operation of a lease that nobody holds, then remove the lease."""
        try:
            descriptor = os.open(self._lease_path, os.O_RDONLY)
        except FileNotFoundError:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Check whether another process replaced the lease before we acquired the lock.
            if os.fstat(descriptor).st_ino != os.stat(self._lease_path).st_ino:
                return
            operation_id = self._lease_owner()
            try:
                self.transition(
                    operation_id,
                    kind="failed",
                    message_key="operations.failed",
                    parameters={"stage": "interrupted"},
                    state="failed",
                    failure_stage="interrupted",
                )
            except (FileNotFoundError, RuntimeError):
                pass  # a cleanup lease, or an operation that already finished
            self._lease_path.unlink()
        except (BlockingIOError, FileNotFoundError):
            pass  # the owner is alive, or the lease was just released
        finally:
            os.close(descriptor)

    def release(self, operation_id: str) -> None:
        with self._lock:
            descriptor = self._held.pop(operation_id, None)
            if descriptor is not None:
                self._lease_path.unlink(missing_ok=True)
                os.close(descriptor)

    def _lease_owner(self) -> str:
        try:
            return self._lease_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def create(self, operation: GenerationOperation) -> None:
        with self._lock:
            path = self._path(operation.operation_id)
            self._write(path, operation.as_dict(), replace_existing=False)
        self._publish(operation, operation.events[-1])

    def load(self, operation_id: str) -> GenerationOperation:
        if not operation_id or any(
            character not in "0123456789abcdef" for character in operation_id
        ):
            raise FileNotFoundError(operation_id)
        try:
            document = json.loads(
                self._path(operation_id).read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise FileNotFoundError(operation_id) from error
        # The record may predate the current mount prefix.
        operation = _operation_from_dict(document, self._public_file_origin)
        links = operation.links
        if "files" in links:
            links = {**links, "files": f"{self._url_prefix}/downloads"}
        return replace(operation, status_url=self.status_url(operation_id), links=links)

    def transition(
        self,
        operation_id: str,
        *,
        kind: str,
        message_key: str,
        parameters: dict[str, Any] | None = None,
        progress: dict[str, Any] | None = None,
        state: str | None = None,
        run_id: str | None = None,
        links: dict[str, str] | None = None,
        failure_stage: str | None = None,
    ) -> GenerationOperation:
        with self._lock:
            current = self.load(operation_id)
            if current.terminal:
                raise RuntimeError(
                    f"operation {operation_id} already has a terminal state"
                )
            transition = OperationTransition(
                event_id=current.latest_event_id + 1,
                kind=kind,
                message_key=message_key,
                parameters=dict(parameters or {}),
                progress=dict(progress or {}),
            )
            terminal = kind in {"completed", "failed"}
            updated = replace(
                current,
                state=state or (kind if terminal else "running"),
                latest_event_id=transition.event_id,
                terminal=terminal,
                run_id=run_id,
                links=dict(links or {}),
                failure_stage=failure_stage,
                events=(*current.events, transition),
            )
            self._write(
                self._path(operation_id),
                updated.as_dict(),
                replace_existing=True,
            )
        self._publish(updated, transition)
        return updated

    def _publish(
        self,
        operation: GenerationOperation,
        transition: OperationTransition,
    ) -> None:
        if self._publisher is None:
            return
        try:
            self._publisher.publish(
                operation.topic,
                operation.operation_id,
                operation.status_url,
                transition,
                operation.as_dict(),
            )
        except Exception:
            # The durable operation record remains authoritative when SSE fails.
            pass

    def _path(self, operation_id: str) -> Path:
        return self.directory / f"{operation_id}.json"

    def _write(
        self,
        path: Path,
        document: dict[str, Any],
        *,
        replace_existing: bool,
    ) -> None:
        content = json.dumps(
            document,
            ensure_ascii=False,
            separators=(",", ":"),
        ) + "\n"
        if replace_existing:
            atomic_replace_text(path, content)
        else:
            atomic_create_text(path, content)


class OperationProgress(ProgressReporter):
    def __init__(self, store: OperationStore, operation_id: str) -> None:
        self.store = store
        self.operation_id = operation_id
        self.current_stage = "starting"
        self.total = 0
        self.completed = 0
        self.unit = "steps"

    def begin_phase(self, description: str, total: int, unit: str) -> None:
        self.current_stage = description
        self.total = total
        self.completed = 0
        self.unit = unit
        self.store.transition(
            self.operation_id,
            kind="stage",
            message_key="operations.stage",
            parameters={"stage": description},
            progress=self._progress(),
        )

    def start(self, operation: str) -> None:
        self.current_stage = operation
        self.store.transition(
            self.operation_id,
            kind="stage",
            message_key="operations.stage",
            parameters={"stage": operation},
            progress=self._progress(),
        )

    def complete(self) -> None:
        if self.total:
            self.completed = min(self.completed + 1, self.total)
        self.store.transition(
            self.operation_id,
            kind="progress",
            message_key="operations.progress",
            parameters={"stage": self.current_stage},
            progress=self._progress(),
        )

    def _progress(self) -> dict[str, Any]:
        return {
            "completed": self.completed,
            "total": self.total,
            "unit": self.unit,
        }


GenerationRunner = Callable[..., PublishedGeneration]


class GenerationOperationManager:
    """Own the bounded executor and one active generation lease."""

    def __init__(
        self,
        state_directory: Path,
        output_directory: Path,
        *,
        executor: Executor | None = None,
        runner: GenerationRunner | None = None,
        renderer: Any = None,
        publisher: TransitionPublisher | None = None,
        public_file_origin: str = "",
        url_prefix: str = "",
    ) -> None:
        self.store = OperationStore(
            state_directory,
            publisher,
            public_file_origin,
            url_prefix,
        )
        self.output_directory = Path(output_directory)
        self.public_file_origin = public_file_origin
        self.url_prefix = url_prefix
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="flickornas-generation",
        )
        self._runner = runner or generate_and_publish
        self._runner_accepts_resolved_request = runner is None
        self._renderer = renderer
        self.store.recover()

    def start(
        self,
        configuration: ActiveConfiguration,
        request: ResolvedGenerationRequest,
        client: MemberSystemClient,
        actor: str | None = None,
    ) -> GenerationOperation:
        inputs = request.inputs
        operation_id = uuid4().hex
        self.store.acquire(operation_id)
        accepted = OperationTransition(
            event_id=1,
            kind="accepted",
            message_key="operations.accepted",
        )
        operation = GenerationOperation(
            operation_id=operation_id,
            topic=f"{TOPIC_PREFIX}/{operation_id}",
            status_url=self.store.status_url(operation_id),
            state="accepted",
            effective_year=inputs.effective_year,
            tournament_ids=inputs.tournament_ids,
            is_partial=inputs.is_partial,
            layout=inputs.layout,
            configuration_revision=configuration.revision,
            latest_event_id=1,
            terminal=False,
            events=(accepted,),
            actor=actor,
        )
        created = False
        try:
            self.store.create(operation)
            created = True
            self._executor.submit(
                self._run,
                operation_id,
                configuration,
                request,
                client,
            )
        except Exception as error:
            if created:
                try:
                    self.store.transition(
                        operation_id,
                        kind="failed",
                        message_key="operations.failed",
                        parameters={
                            "stage": "scheduling",
                            "detail": str(error),
                        },
                        state="failed",
                        failure_stage="scheduling",
                    )
                except Exception:
                    pass
            self.store.release(operation_id)
            raise
        return operation

    def clear_downloads(self) -> int:
        """Clear generated files while excluding concurrent generation."""
        cleanup_id = f"downloads-{uuid4().hex}"
        self.store.acquire(cleanup_id)
        try:
            return clear_generated_downloads(
                self.output_directory,
                self.store.directory.parent,
            )
        finally:
            self.store.release(cleanup_id)

    def _run(
        self,
        operation_id: str,
        configuration: ActiveConfiguration,
        request: ResolvedGenerationRequest,
        client: MemberSystemClient,
    ) -> None:
        inputs = request.inputs
        progress = OperationProgress(self.store, operation_id)
        try:
            published = self._runner(
                configuration,
                request if self._runner_accepts_resolved_request else inputs,
                client,
                self.output_directory,
                state_directory=self.store.directory.parent,
                renderer=self._renderer,
                progress=progress,
            )
            self.store.transition(
                operation_id,
                kind="completed",
                message_key="operations.completed",
                parameters={"run_id": published.run_id},
                state="completed",
                run_id=published.run_id,
                links=generation_download_links(
                    published.run_id,
                    inputs.is_partial,
                    pdf_filename=published.pdf_path.name,
                    public_origin=self.public_file_origin,
                    url_prefix=self.url_prefix,
                ),
            )
        except Exception as error:
            stage = (
                error.stage
                if isinstance(error, GenerationStageError)
                else progress.current_stage
            )
            parameters = {"stage": stage, "detail": str(error)}
            if isinstance(error, KlassNamingError):
                parameters = {
                    "stage": "validation",
                    "problems": klass_naming_problems(error.klass_problems),
                }
            self.store.transition(
                operation_id,
                kind="failed",
                message_key="operations.failed",
                parameters=parameters,
                state="failed",
                failure_stage=stage,
            )
        finally:
            self.store.release(operation_id)


def _operation_from_dict(
    document: dict[str, Any],
    public_file_origin: str = "",
) -> GenerationOperation:
    events = tuple(
        OperationTransition(
            event_id=int(event["event_id"]),
            kind=str(event["kind"]),
            message_key=str(event["message_key"]),
            parameters=dict(event.get("parameters", {})),
            progress=dict(event.get("progress", {})),
        )
        for event in document.get("events", [])
    )
    run_id = document.get("run_id")
    links = dict(document.get("links", {}))
    if run_id is not None and links.get("pdf", "").startswith("/runs/"):
        links = generation_download_links(
            str(run_id),
            bool(document["is_partial"]),
            public_origin=public_file_origin,
        )
    elif links:
        # Links saved before file origins existed start at /downloads.
        links = {
            name: public_file_url(public_file_origin, url)
            if url == "/downloads" or url.startswith("/downloads/")
            else url
            for name, url in links.items()
        }
    return GenerationOperation(
        operation_id=str(document["operation_id"]),
        topic=str(document["topic"]),
        status_url=str(document["status_url"]),
        state=str(document["state"]),
        effective_year=int(document["effective_year"]),
        tournament_ids=tuple(int(value) for value in document["tournament_ids"]),
        is_partial=bool(document["is_partial"]),
        layout=str(document["layout"]),
        configuration_revision=document.get("configuration_revision"),
        latest_event_id=int(document["latest_event_id"]),
        terminal=bool(document["terminal"]),
        run_id=run_id,
        links=links,
        failure_stage=document.get("failure_stage"),
        events=events,
        actor=document.get("actor"),
    )
