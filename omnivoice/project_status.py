#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Fast project-level status summaries for large Project Studio workspaces.

The queue usually needs to answer a simpler question than the full project
controller: which projects still need work?  This module derives a compact
status from ``project.json`` plus the crash-safe ``section-status.json``
sidecar without loading models or audio.

Statuses intentionally describe render progress, not queue membership:

- ``DONE``: every section is verified and its sidecar marks it complete;
- ``GENERATING``: at least one section is currently queued/generating;
- ``NEEDS_REVIEW``: no section is generating, but at least one is unverified;
- ``FAILED``: no section is generating, but at least one is failed;
- ``PENDING``: anything else that still needs generation.

``DONE`` projects are hidden by default in the Project Queue UI, while users
can explicitly include them when needed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

PROJECT_STATUSES = ("PENDING", "GENERATING", "NEEDS_REVIEW", "FAILED", "DONE")
DEFAULT_QUEUE_PROJECT_STATUSES = ("PENDING", "GENERATING")


@dataclass(frozen=True)
class ProjectStatusSummary:
    path: str
    title: str
    status: str
    completed_sections: int
    total_sections: int
    current_sections: tuple[str, ...] = ()
    updated_at: Optional[str] = None

    @property
    def progress(self) -> str:
        return f"{self.completed_sections}/{self.total_sections}"

    @property
    def dropdown_label(self) -> str:
        return f"[{self.status} {self.progress}] {self.title}"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def summarize_project(project_root: str | Path) -> ProjectStatusSummary:
    root = Path(project_root).expanduser()
    manifest = _read_json(root / "project.json")
    sidecar = _read_json(root / "section-status.json")

    title = str(manifest.get("title") or root.name)
    manifest_sections = manifest.get("sections") or []
    section_ids = [
        str(item.get("id") or "")
        for item in manifest_sections
        if isinstance(item, dict) and item.get("id")
    ]
    total = len(section_ids)

    sidecar_sections = sidecar.get("sections") or {}
    raw_states: list[str] = []
    complete = 0
    active: list[str] = []
    for section_id in section_ids:
        record = sidecar_sections.get(section_id) if isinstance(sidecar_sections, dict) else None
        if not isinstance(record, dict):
            # Fall back to manifest state for projects created before the
            # section-status sidecar existed.
            manifest_record = next(
                (
                    item
                    for item in manifest_sections
                    if isinstance(item, dict) and str(item.get("id")) == section_id
                ),
                {},
            )
            raw = str(manifest_record.get("status") or "pending").lower()
            is_complete = raw == "verified" and bool(manifest_record.get("audio_file"))
        else:
            raw = str(record.get("status") or "pending").lower()
            is_complete = bool(record.get("complete")) and raw == "verified"
        raw_states.append(raw)
        if is_complete:
            complete += 1
        if raw in {"queued", "generating"}:
            active.append(section_id)

    if total > 0 and complete == total:
        status = "DONE"
    elif any(state in {"queued", "generating"} for state in raw_states):
        status = "GENERATING"
    elif any(state == "unverified" for state in raw_states):
        status = "NEEDS_REVIEW"
    elif any(state == "failed" for state in raw_states):
        status = "FAILED"
    else:
        status = "PENDING"

    updated = sidecar.get("updated_at") or manifest.get("updated_at")
    return ProjectStatusSummary(
        path=str(root),
        title=title,
        status=status,
        completed_sections=complete,
        total_sections=total,
        current_sections=tuple(active),
        updated_at=(str(updated) if updated else None),
    )


def scan_project_statuses(projects_root: str | Path) -> list[ProjectStatusSummary]:
    root = Path(projects_root).expanduser()
    summaries = [
        summarize_project(manifest.parent)
        for manifest in root.glob("*/project.json")
    ]
    return sorted(
        summaries,
        key=lambda item: (
            PROJECT_STATUSES.index(item.status)
            if item.status in PROJECT_STATUSES
            else len(PROJECT_STATUSES),
            item.title.lower(),
        ),
    )


def filter_project_statuses(
    summaries: Iterable[ProjectStatusSummary],
    statuses: Optional[Iterable[str]] = None,
    *,
    exclude_paths: Optional[Iterable[str | Path]] = None,
) -> list[ProjectStatusSummary]:
    selected = {
        str(value).upper()
        for value in (statuses or DEFAULT_QUEUE_PROJECT_STATUSES)
        if str(value).strip()
    }
    excluded = {
        str(Path(value).expanduser().resolve())
        for value in (exclude_paths or [])
    }
    return [
        item
        for item in summaries
        if item.status in selected
        and str(Path(item.path).expanduser().resolve()) not in excluded
    ]


def project_status_rows(summaries: Iterable[ProjectStatusSummary]) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in summaries:
        rows.append(
            [
                item.status,
                item.title,
                item.progress,
                ", ".join(item.current_sections),
                item.updated_at or "",
                item.path,
            ]
        )
    return rows
