#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Persistent section-level checkpoints for resumable Project Studio renders.

``project.json`` remains the complete project manifest.  This module adds a
small, independent ``section-status.json`` checkpoint whose only job is to
answer one question reliably after a Colab/runtime restart: which sections are
already complete and which sections still need work?

A section recorded as ``verified`` is considered complete only when its section
WAV still exists.  Interrupted ``generating``/``queued`` states are recovered
as ``pending`` when the project is loaded, so a killed runtime cannot leave a
section permanently stuck in an in-progress state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from omnivoice.project import OmniVoiceProject, ProjectSection, _utc_now

SECTION_STATUS_NAME = "section-status.json"
SECTION_STATUS_VERSION = 1
_INTERRUPTED_STATES = {"generating", "queued"}


@dataclass(frozen=True)
class SectionStatusRestore:
    restored: tuple[str, ...] = ()
    recovered_interrupted: tuple[str, ...] = ()
    invalid_complete: tuple[str, ...] = ()


def section_status_path(project: OmniVoiceProject) -> Path:
    return project.root / SECTION_STATUS_NAME


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


def _default_section_audio(project: OmniVoiceProject, section: ProjectSection) -> Path:
    return project.root / "sections" / section.id / f"{section.id}.wav"


def _section_audio_path(
    project: OmniVoiceProject,
    section: ProjectSection,
    audio_file: Optional[str] = None,
) -> Path:
    value = audio_file or section.audio_file
    if value:
        return project.root / value
    return _default_section_audio(project, section)


def section_is_complete(project: OmniVoiceProject, section: ProjectSection) -> bool:
    """Return True only for a verified section whose final WAV still exists."""

    return section.status == "verified" and _section_audio_path(project, section).exists()


def _record_for(project: OmniVoiceProject, section: ProjectSection) -> dict[str, Any]:
    return {
        "status": section.status,
        "audio_file": section.audio_file,
        "updated_at": section.updated_at,
        "complete": section_is_complete(project, section),
    }


def write_section_status(project: OmniVoiceProject) -> Path:
    """Persist current section states to the independent resume checkpoint."""

    payload = {
        "version": SECTION_STATUS_VERSION,
        "project_source_hash": project.manifest.source_hash,
        "updated_at": _utc_now(),
        "sections": {
            section.id: _record_for(project, section)
            for section in project.manifest.sections
        },
    }
    path = section_status_path(project)
    _atomic_write(path, payload)
    return path


def ensure_section_status(project: OmniVoiceProject) -> Path:
    path = section_status_path(project)
    if not path.exists():
        return write_section_status(project)
    return path


def _restore_verified_children(project: OmniVoiceProject, section: ProjectSection) -> None:
    """Recover child checkpoint metadata when their persisted audio still exists."""

    for beat in section.beats:
        if beat.audio_file:
            beat_path = project.root / beat.audio_file
        else:
            beat_path = project.root / "sections" / section.id / "beats" / f"{beat.id}.wav"
        if beat_path.exists():
            beat.audio_file = str(beat_path.relative_to(project.root))
            beat.status = "verified"

        for chunk in beat.chunks:
            if chunk.audio_file:
                chunk_path = project.root / chunk.audio_file
            else:
                chunk_path = (
                    project.root
                    / "sections"
                    / section.id
                    / "chunks"
                    / f"{chunk.id}.wav"
                )
            report_path = chunk_path.with_suffix(".json")
            if chunk_path.exists():
                chunk.audio_file = str(chunk_path.relative_to(project.root))
                if report_path.exists():
                    chunk.report_file = str(report_path.relative_to(project.root))
                chunk.status = "verified"


def restore_section_status(
    project: OmniVoiceProject,
    *,
    sync_manifest: bool = False,
    create_if_missing: bool = True,
) -> SectionStatusRestore:
    """Overlay section checkpoints onto a loaded project manifest.

    ``verified`` is restored only when the final section WAV exists.  Stale
    ``generating`` and ``queued`` states become ``pending`` in memory because
    they represent interrupted work.  When ``sync_manifest`` is true, the
    reconciled state is also written back to ``project.json`` so existing UI
    code immediately sees the recovered checkpoint state.
    """

    path = section_status_path(project)
    if not path.exists():
        if create_if_missing:
            write_section_status(project)
        return SectionStatusRestore()

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A damaged sidecar must never make the main project unloadable.
        if create_if_missing:
            write_section_status(project)
        return SectionStatusRestore()

    if payload.get("version") != SECTION_STATUS_VERSION:
        return SectionStatusRestore()
    saved_hash = payload.get("project_source_hash")
    if saved_hash and saved_hash != project.manifest.source_hash:
        return SectionStatusRestore()

    records = payload.get("sections") or {}
    restored: list[str] = []
    interrupted: list[str] = []
    invalid_complete: list[str] = []

    for section in project.manifest.sections:
        record = records.get(section.id)
        if not isinstance(record, dict):
            continue

        raw_status = str(record.get("status") or "pending").lower()
        saved_audio = record.get("audio_file")
        if saved_audio:
            section.audio_file = str(saved_audio)

        if raw_status == "verified":
            audio_path = _section_audio_path(project, section, section.audio_file)
            if audio_path.exists():
                section.audio_file = str(audio_path.relative_to(project.root))
                section.status = "verified"
                _restore_verified_children(project, section)
                restored.append(section.id)
            else:
                section.status = "pending"
                section.audio_file = None
                invalid_complete.append(section.id)
        elif raw_status in _INTERRUPTED_STATES:
            section.status = "pending"
            interrupted.append(section.id)
        else:
            section.status = raw_status

        if record.get("updated_at"):
            section.updated_at = str(record["updated_at"])

    if sync_manifest and (restored or interrupted or invalid_complete):
        project.save()

    return SectionStatusRestore(
        restored=tuple(restored),
        recovered_interrupted=tuple(interrupted),
        invalid_complete=tuple(invalid_complete),
    )


def set_section_status(
    project: OmniVoiceProject,
    section_id: str,
    status: str,
    *,
    save_manifest: bool = True,
) -> Path:
    """Set one section state and checkpoint the complete section-status table."""

    section = project.get_section(section_id)
    section.status = status.lower()
    section.updated_at = _utc_now()
    if save_manifest:
        project.save()
    return write_section_status(project)


def incomplete_section_ids(
    project: OmniVoiceProject,
    section_ids: Optional[Iterable[str]] = None,
) -> list[str]:
    """Return selected sections that still require generation, in project order."""

    selected = None
    if section_ids is not None:
        selected = {item.upper() for item in section_ids}
    return [
        section.id
        for section in project.manifest.sections
        if (selected is None or section.id in selected)
        and not section_is_complete(project, section)
    ]
