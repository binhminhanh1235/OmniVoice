#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Persistent multi-project render queue for Project Studio.

The queue is deliberately independent from Gradio. It stores enough metadata
under the Studio workspace to survive Colab/runtime restarts and delegates the
actual section generation to the existing section-resume controller.

Durability rules:
- queue state is flushed after every project/section transition;
- an interrupted ``running`` item is recovered as ``pending`` on startup;
- completed project items are skipped on the next run;
- each project is generated one section at a time so ``section-status.json``
  remains the fine-grained resume authority inside the project itself.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from omnivoice.section_status import incomplete_section_ids, section_is_complete

QUEUE_FILE_NAME = "project-queue.json"
QUEUE_VERSION = 1
# Failed/needs-review items are still owned by the queue and should be requeued
# rather than duplicated accidentally.
_ACTIVE_STATES = {"pending", "running", "paused", "failed", "needs_review"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


@dataclass
class ProjectQueueItem:
    id: str
    project_path: str
    project_title: str
    voice_name: str
    voice_variant: str = "AUTO"
    language: Optional[str] = "en"
    strict: bool = False
    auto_merge: bool = True
    status: str = "pending"
    current_section: Optional[str] = None
    completed_sections: int = 0
    total_sections: int = 0
    attempts: int = 0
    error: Optional[str] = None
    merged_audio: Optional[str] = None
    added_at: str = field(default_factory=_utc_now)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectQueueItem":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in payload.items() if key in allowed})


@dataclass
class ProjectQueueManifest:
    version: int = QUEUE_VERSION
    paused: bool = False
    updated_at: str = field(default_factory=_utc_now)
    items: list[ProjectQueueItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectQueueManifest":
        items = [ProjectQueueItem.from_dict(item) for item in payload.get("items", [])]
        return cls(
            version=int(payload.get("version", QUEUE_VERSION)),
            paused=bool(payload.get("paused", False)),
            updated_at=str(payload.get("updated_at") or _utc_now()),
            items=items,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "paused": self.paused,
            "updated_at": self.updated_at,
            "items": [asdict(item) for item in self.items],
        }


@dataclass(frozen=True)
class QueueEvent:
    item_id: Optional[str]
    project_path: Optional[str]
    project_title: Optional[str]
    status: str
    current_section: Optional[str]
    message: str


class ProjectQueueStore:
    """Persistent queue sidecar stored once per Studio workspace."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser()
        self.path = self.workspace / QUEUE_FILE_NAME
        self.workspace.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save(ProjectQueueManifest())

    def load(self) -> ProjectQueueManifest:
        if not self.path.exists():
            return ProjectQueueManifest()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ProjectQueueManifest()
        if int(payload.get("version", QUEUE_VERSION)) != QUEUE_VERSION:
            return ProjectQueueManifest()
        return ProjectQueueManifest.from_dict(payload)

    def save(self, manifest: ProjectQueueManifest) -> Path:
        manifest.updated_at = _utc_now()
        _atomic_write(self.path, manifest.to_dict())
        return self.path

    def recover_interrupted(self) -> ProjectQueueManifest:
        """Recover stale in-progress state after a runtime restart."""

        manifest = self.load()
        changed = False
        for item in manifest.items:
            if item.status == "running":
                item.status = "pending"
                item.error = (
                    "Recovered after interrupted runtime; resume will continue "
                    "incomplete sections."
                )
                changed = True
        if manifest.paused:
            # A pause request belongs to the dead process. Re-opening Studio
            # should not leave the queue permanently inert.
            manifest.paused = False
            changed = True
        if changed:
            self.save(manifest)
        return manifest

    def enqueue(
        self,
        controller: Any,
        project_path: str | Path,
        *,
        voice_name: Optional[str] = None,
        voice_variant: Optional[str] = None,
        language: Optional[str] = None,
        strict: bool = False,
        auto_merge: bool = True,
    ) -> ProjectQueueItem:
        project = controller.load_project(project_path)
        settings = controller.load_project_settings(project)
        selected_voice = (voice_name or settings.get("voice_name") or "").strip()
        if not selected_voice:
            raise ValueError(
                "Project has no saved voice. Select a voice before adding it to the queue."
            )
        selected_variant = (
            voice_variant or settings.get("voice_variant") or "AUTO"
        ).upper()
        selected_language = (
            language if language is not None else settings.get("language", "en")
        )

        manifest = self.load()
        project_root = str(project.root.resolve())
        for existing in manifest.items:
            if existing.project_path == project_root and existing.status in _ACTIVE_STATES:
                raise ValueError(
                    f"Project is already queued as {existing.status}: "
                    f"{project.manifest.title}. Remove or requeue the existing item."
                )

        total = len(project.manifest.sections)
        complete = sum(
            section_is_complete(project, section)
            for section in project.manifest.sections
        )
        item = ProjectQueueItem(
            id=uuid.uuid4().hex[:12],
            project_path=project_root,
            project_title=project.manifest.title,
            voice_name=selected_voice,
            voice_variant=selected_variant,
            language=selected_language,
            strict=bool(strict),
            auto_merge=bool(auto_merge),
            completed_sections=complete,
            total_sections=total,
            status="completed" if total and complete == total else "pending",
        )
        if item.status == "completed":
            item.finished_at = _utc_now()
        manifest.items.append(item)
        self.save(manifest)
        return item

    def find(self, manifest: ProjectQueueManifest, item_id: str) -> ProjectQueueItem:
        for item in manifest.items:
            if item.id == item_id:
                return item
        raise KeyError(item_id)

    def remove(self, item_id: str) -> ProjectQueueManifest:
        manifest = self.load()
        item = self.find(manifest, item_id)
        if item.status == "running":
            raise ValueError("Cannot remove a running project. Pause the queue first.")
        manifest.items = [candidate for candidate in manifest.items if candidate.id != item_id]
        self.save(manifest)
        return manifest

    def move(self, item_id: str, delta: int) -> ProjectQueueManifest:
        manifest = self.load()
        index = next(
            (i for i, item in enumerate(manifest.items) if item.id == item_id),
            None,
        )
        if index is None:
            raise KeyError(item_id)
        target = max(0, min(len(manifest.items) - 1, index + int(delta)))
        if target != index:
            item = manifest.items.pop(index)
            manifest.items.insert(target, item)
        self.save(manifest)
        return manifest

    def clear_completed(self) -> ProjectQueueManifest:
        manifest = self.load()
        manifest.items = [item for item in manifest.items if item.status != "completed"]
        self.save(manifest)
        return manifest

    def requeue(self, item_id: str) -> ProjectQueueManifest:
        manifest = self.load()
        item = self.find(manifest, item_id)
        if item.status == "running":
            raise ValueError("Cannot requeue a running project. Pause the queue first.")
        item.status = "pending"
        item.current_section = None
        item.error = None
        item.finished_at = None
        self.save(manifest)
        return manifest

    def request_pause(self) -> ProjectQueueManifest:
        manifest = self.load()
        manifest.paused = True
        self.save(manifest)
        return manifest

    def resume_queue(self) -> ProjectQueueManifest:
        manifest = self.load()
        manifest.paused = False
        self.save(manifest)
        return manifest


class ProjectQueueRunner:
    """Run queued projects sequentially using section-level resume semantics."""

    def __init__(self, controller: Any, store: ProjectQueueStore) -> None:
        self.controller = controller
        self.store = store

    def _refresh_progress(self, item: ProjectQueueItem) -> list[str]:
        project = self.controller.load_project(item.project_path)
        item.total_sections = len(project.manifest.sections)
        item.completed_sections = sum(
            section_is_complete(project, section)
            for section in project.manifest.sections
        )
        return incomplete_section_ids(project)

    def _save_item(self, item: ProjectQueueItem) -> ProjectQueueManifest:
        manifest = self.store.load()
        target = self.store.find(manifest, item.id)
        target.__dict__.update(asdict(item))
        self.store.save(manifest)
        return manifest

    def _pause_requested(self) -> bool:
        return bool(self.store.load().paused)

    def run(
        self,
        *,
        continue_on_error: bool = True,
    ) -> Generator[QueueEvent, None, ProjectQueueManifest]:
        manifest = self.store.recover_interrupted()

        for seed in list(manifest.items):
            current_manifest = self.store.load()
            item = self.store.find(current_manifest, seed.id)
            if item.status in {"completed", "cancelled"}:
                continue
            if item.status not in {"pending", "failed", "needs_review", "paused"}:
                continue
            if self._pause_requested():
                item.status = "paused"
                self._save_item(item)
                yield QueueEvent(
                    item.id,
                    item.project_path,
                    item.project_title,
                    "paused",
                    item.current_section,
                    "Queue paused before starting the next project.",
                )
                break

            item.status = "running"
            item.started_at = item.started_at or _utc_now()
            item.finished_at = None
            item.error = None
            item.attempts += 1
            pending = self._refresh_progress(item)
            self._save_item(item)
            yield QueueEvent(
                item.id,
                item.project_path,
                item.project_title,
                "running",
                None,
                f"Starting {item.project_title}: "
                f"{item.completed_sections}/{item.total_sections} sections complete.",
            )

            try:
                for section_id in pending:
                    if self._pause_requested():
                        item.status = "paused"
                        item.current_section = section_id
                        self._save_item(item)
                        yield QueueEvent(
                            item.id,
                            item.project_path,
                            item.project_title,
                            "paused",
                            section_id,
                            f"Queue paused before {item.project_title} / {section_id}.",
                        )
                        return self.store.load()

                    item.current_section = section_id
                    self._save_item(item)
                    yield QueueEvent(
                        item.id,
                        item.project_path,
                        item.project_title,
                        "running",
                        section_id,
                        f"Generating {item.project_title} / {section_id}...",
                    )

                    self.controller.generate(
                        item.project_path,
                        voice_name=item.voice_name,
                        voice_variant=item.voice_variant,
                        language=item.language,
                        section_ids=[section_id],
                        resume=True,
                        strict=item.strict,
                    )
                    self._refresh_progress(item)
                    self._save_item(item)
                    yield QueueEvent(
                        item.id,
                        item.project_path,
                        item.project_title,
                        "running",
                        section_id,
                        f"Finished {item.project_title} / {section_id}. "
                        f"{item.completed_sections}/{item.total_sections} sections complete.",
                    )

                remaining = self._refresh_progress(item)
                item.current_section = None
                if remaining:
                    item.status = "needs_review"
                    item.error = (
                        "Generation finished but some sections are not verified: "
                        + ", ".join(remaining)
                    )
                else:
                    item.status = "completed"
                    item.error = None
                    if item.auto_merge:
                        try:
                            merged = self.controller.merge_project(
                                item.project_path,
                                require_verified=True,
                            )
                            item.merged_audio = str(merged)
                        except Exception as exc:
                            # Audio generation is still complete. Keep the item
                            # completed and expose merge failure separately.
                            item.error = (
                                f"Auto-merge failed: {type(exc).__name__}: {exc}"
                            )
                    item.finished_at = _utc_now()
                self._save_item(item)
                yield QueueEvent(
                    item.id,
                    item.project_path,
                    item.project_title,
                    item.status,
                    None,
                    (
                        f"Completed {item.project_title}."
                        if item.status == "completed"
                        else f"{item.project_title} needs review: {item.error}"
                    ),
                )
            except Exception as exc:
                item.status = "failed"
                item.error = f"{type(exc).__name__}: {exc}"
                item.finished_at = _utc_now()
                self._save_item(item)
                yield QueueEvent(
                    item.id,
                    item.project_path,
                    item.project_title,
                    "failed",
                    item.current_section,
                    f"Failed {item.project_title}: {item.error}",
                )
                if not continue_on_error:
                    break

        return self.store.load()


def queue_rows(manifest: ProjectQueueManifest) -> list[list[Any]]:
    """Stable table representation shared by UI/tests."""

    rows: list[list[Any]] = []
    for index, item in enumerate(manifest.items, start=1):
        rows.append(
            [
                index,
                item.project_title,
                item.status.upper(),
                f"{item.completed_sections}/{item.total_sections}",
                item.current_section or "",
                item.voice_name,
                item.voice_variant,
                item.language or "",
                "yes" if item.auto_merge else "no",
                item.error or "",
                item.id,
            ]
        )
    return rows
