#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Persistent single-worker job manager for GPU-bound Studio tasks."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

JOBS_FILE = "jobs.json"
JOBS_VERSION = 1
JOB_STATUSES = (
    "queued",
    "running",
    "cancel_requested",
    "completed",
    "failed",
    "cancelled",
)
_TERMINAL = {"completed", "failed", "cancelled"}
_MAX_EVENTS_PER_JOB = 250


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


@dataclass
class JobEvent:
    seq: int
    timestamp: str
    event: str
    message: str
    progress: Optional[float] = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobRecord:
    id: str
    kind: str
    payload: dict[str, Any]
    status: str = "queued"
    progress: float = 0.0
    message: str = "Queued."
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=_utc_now)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    events: list[JobEvent] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "JobRecord":
        raw_events = payload.get("events") or []
        events = [
            item if isinstance(item, JobEvent) else JobEvent(**item)
            for item in raw_events
            if isinstance(item, (dict, JobEvent))
        ]
        allowed = cls.__dataclass_fields__.keys()
        values = {key: value for key, value in payload.items() if key in allowed}
        values["events"] = events
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload


@dataclass
class JobsManifest:
    version: int = JOBS_VERSION
    updated_at: str = field(default_factory=_utc_now)
    jobs: list[JobRecord] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "JobsManifest":
        return cls(
            version=int(payload.get("version", JOBS_VERSION)),
            updated_at=str(payload.get("updated_at") or _utc_now()),
            jobs=[JobRecord.from_dict(item) for item in payload.get("jobs", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "jobs": [job.to_dict() for job in self.jobs],
        }


class JobCancelled(RuntimeError):
    pass


class JobStore:
    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser()
        self.path = self.workspace / JOBS_FILE
        self.workspace.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save(JobsManifest())

    def load(self) -> JobsManifest:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return JobsManifest()
        if int(payload.get("version", JOBS_VERSION)) != JOBS_VERSION:
            return JobsManifest()
        return JobsManifest.from_dict(payload)

    def save(self, manifest: JobsManifest) -> Path:
        manifest.updated_at = _utc_now()
        _atomic_write(self.path, manifest.to_dict())
        return self.path

    @staticmethod
    def find(manifest: JobsManifest, job_id: str) -> JobRecord:
        for job in manifest.jobs:
            if job.id == job_id:
                return job
        raise KeyError(job_id)

    def recover_interrupted(self) -> JobsManifest:
        manifest = self.load()
        changed = False
        for job in manifest.jobs:
            if job.status in {"running", "cancel_requested"}:
                job.status = "queued"
                job.message = "Recovered after interrupted runtime; queued for retry."
                job.error = None
                job.started_at = None
                job.finished_at = None
                changed = True
        if changed:
            self.save(manifest)
        return manifest


class JobContext:
    def __init__(self, manager: "StudioJobManager", job_id: str, payload: dict[str, Any]):
        self.manager = manager
        self.job_id = job_id
        self.payload = payload

    def emit(
        self,
        message: str,
        *,
        progress: Optional[float] = None,
        event: str = "progress",
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        self.manager.emit(
            self.job_id,
            event=event,
            message=message,
            progress=progress,
            data=data,
        )

    def cancel_requested(self) -> bool:
        return self.manager.cancel_requested(self.job_id)

    def checkpoint(self) -> None:
        if self.cancel_requested():
            raise JobCancelled("Cancellation requested")


JobHandler = Callable[[JobContext], Optional[dict[str, Any]]]


class StudioJobManager:
    """Persistent FIFO job manager with exactly one active worker thread."""

    def __init__(self, workspace: str | Path) -> None:
        self.store = JobStore(workspace)
        self._handlers: dict[str, JobHandler] = {}
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._thread: Optional[threading.Thread] = None
        self._stop = False

    def register(self, kind: str, handler: JobHandler) -> None:
        name = str(kind).strip()
        if not name:
            raise ValueError("Job kind cannot be empty")
        with self._lock:
            self._handlers[name] = handler

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self.store.recover_interrupted()
            self._stop = False
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="omnivoice-studio-gpu-worker",
                daemon=True,
            )
            self._thread.start()
            self._condition.notify_all()

    def shutdown(self, timeout: float = 2.0) -> None:
        with self._condition:
            self._stop = True
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def submit(
        self,
        kind: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
    ) -> JobRecord:
        name = str(kind).strip()
        with self._condition:
            if name not in self._handlers:
                raise ValueError(f"No handler registered for job kind: {name}")
            manifest = self.store.load()
            if idempotency_key:
                for existing in manifest.jobs:
                    if existing.idempotency_key == idempotency_key:
                        return existing
            job = JobRecord(
                id=f"job_{uuid.uuid4().hex[:16]}",
                kind=name,
                payload=dict(payload or {}),
                idempotency_key=idempotency_key,
            )
            job.events.append(
                JobEvent(
                    seq=1,
                    timestamp=_utc_now(),
                    event="queued",
                    message="Queued.",
                    progress=0.0,
                )
            )
            manifest.jobs.append(job)
            self.store.save(manifest)
            self._condition.notify_all()
            return JobRecord.from_dict(job.to_dict())

    def list_jobs(self) -> list[JobRecord]:
        with self._lock:
            return [JobRecord.from_dict(job.to_dict()) for job in self.store.load().jobs]

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            manifest = self.store.load()
            job = self.store.find(manifest, job_id)
            return JobRecord.from_dict(job.to_dict())

    def cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            manifest = self.store.load()
            job = self.store.find(manifest, job_id)
            return job.status in {"cancel_requested", "cancelled"}

    def request_cancel(self, job_id: str) -> JobRecord:
        with self._condition:
            manifest = self.store.load()
            job = self.store.find(manifest, job_id)
            if job.status in _TERMINAL:
                return JobRecord.from_dict(job.to_dict())
            if job.status == "queued":
                job.status = "cancelled"
                job.finished_at = _utc_now()
                job.message = "Cancelled before start."
                self._append_event(job, "cancelled", job.message, job.progress, {})
            else:
                job.status = "cancel_requested"
                job.message = "Cancellation requested; waiting for a safe checkpoint."
                self._append_event(
                    job,
                    "cancel_requested",
                    job.message,
                    job.progress,
                    {},
                )
            self.store.save(manifest)
            self._condition.notify_all()
            return JobRecord.from_dict(job.to_dict())

    def events_after(self, job_id: str, seq: int = 0) -> list[JobEvent]:
        job = self.get(job_id)
        return [event for event in job.events if event.seq > int(seq)]

    def emit(
        self,
        job_id: str,
        *,
        event: str,
        message: str,
        progress: Optional[float] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        with self._condition:
            manifest = self.store.load()
            job = self.store.find(manifest, job_id)
            if progress is not None:
                job.progress = max(0.0, min(1.0, float(progress)))
            job.message = str(message)
            self._append_event(job, event, job.message, job.progress, data or {})
            self.store.save(manifest)
            self._condition.notify_all()

    @staticmethod
    def _append_event(
        job: JobRecord,
        event: str,
        message: str,
        progress: Optional[float],
        data: dict[str, Any],
    ) -> None:
        seq = (job.events[-1].seq + 1) if job.events else 1
        job.events.append(
            JobEvent(
                seq=seq,
                timestamp=_utc_now(),
                event=str(event),
                message=str(message),
                progress=progress,
                data=dict(data),
            )
        )
        if len(job.events) > _MAX_EVENTS_PER_JOB:
            job.events[:] = job.events[-_MAX_EVENTS_PER_JOB:]

    def _next_queued(self) -> Optional[JobRecord]:
        manifest = self.store.load()
        for job in manifest.jobs:
            if job.status == "queued":
                return JobRecord.from_dict(job.to_dict())
        return None

    def _set_running(self, job_id: str) -> JobRecord:
        manifest = self.store.load()
        job = self.store.find(manifest, job_id)
        if job.status != "queued":
            return JobRecord.from_dict(job.to_dict())
        job.status = "running"
        job.started_at = _utc_now()
        job.finished_at = None
        job.error = None
        job.message = "Running."
        self._append_event(job, "started", job.message, job.progress, {})
        self.store.save(manifest)
        return JobRecord.from_dict(job.to_dict())

    def _finish(
        self,
        job_id: str,
        *,
        status: str,
        message: str,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        manifest = self.store.load()
        job = self.store.find(manifest, job_id)
        job.status = status
        job.message = message
        job.result = result
        job.error = error
        job.finished_at = _utc_now()
        if status == "completed":
            job.progress = 1.0
        self._append_event(job, status, message, job.progress, {})
        self.store.save(manifest)

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                if self._stop:
                    return
                candidate = self._next_queued()
                if candidate is None:
                    self._condition.wait(timeout=0.5)
                    continue
                job = self._set_running(candidate.id)
                handler = self._handlers.get(job.kind)

            if handler is None:
                with self._condition:
                    self._finish(
                        job.id,
                        status="failed",
                        message=f"No handler registered for {job.kind}",
                        error="Missing job handler",
                    )
                continue

            context = JobContext(self, job.id, job.payload)
            try:
                context.checkpoint()
                result = handler(context) or {}
                context.checkpoint()
                with self._condition:
                    self._finish(
                        job.id,
                        status="completed",
                        message="Completed.",
                        result=result,
                    )
            except JobCancelled:
                with self._condition:
                    self._finish(
                        job.id,
                        status="cancelled",
                        message="Cancelled at a safe checkpoint.",
                    )
            except Exception as exc:
                with self._condition:
                    self._finish(
                        job.id,
                        status="failed",
                        message=f"Failed: {type(exc).__name__}: {exc}",
                        error=f"{type(exc).__name__}: {exc}",
                    )


def wait_for_terminal(
    manager: StudioJobManager,
    job_id: str,
    *,
    timeout: float = 5.0,
    poll_interval: float = 0.02,
) -> JobRecord:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job.status in _TERMINAL:
            return job
        time.sleep(poll_interval)
    raise TimeoutError(job_id)
