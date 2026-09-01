#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Persistent snapshots for generated project sections.

A section version stores the final section WAV together with beat/chunk audio,
verification reports, and the serialized ProjectSection state. Restoring a
version therefore restores a coherent checkpoint instead of only swapping the
final WAV while leaving stale chunk metadata behind.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from omnivoice.project import (
    OmniVoiceProject,
    ProjectBeat,
    ProjectChunk,
    ProjectSection,
    _utc_now,
)
from omnivoice.section_status import write_section_status

HISTORY_DIR_NAME = "history"
HISTORY_INDEX_NAME = "history.json"
HISTORY_FORMAT_VERSION = 1


@dataclass(frozen=True)
class SectionVersion:
    id: str
    section_id: str
    created_at: str
    reason: str
    status: str
    source_hash: str
    snapshot_dir: str
    audio_file: Optional[str] = None


def _section_dir(project: OmniVoiceProject, section_id: str) -> Path:
    return project.root / "sections" / section_id.upper()


def _history_root(project: OmniVoiceProject, section_id: str) -> Path:
    return _section_dir(project, section_id) / HISTORY_DIR_NAME


def _index_path(project: OmniVoiceProject, section_id: str) -> Path:
    return _history_root(project, section_id) / HISTORY_INDEX_NAME


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _read_index(project: OmniVoiceProject, section_id: str) -> dict[str, Any]:
    path = _index_path(project, section_id)
    if not path.exists():
        return {
            "version": HISTORY_FORMAT_VERSION,
            "section_id": section_id.upper(),
            "versions": [],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "version": HISTORY_FORMAT_VERSION,
            "section_id": section_id.upper(),
            "versions": [],
        }
    if payload.get("version") != HISTORY_FORMAT_VERSION:
        return {
            "version": HISTORY_FORMAT_VERSION,
            "section_id": section_id.upper(),
            "versions": [],
        }
    return payload


def _next_version_id(project: OmniVoiceProject, section_id: str) -> str:
    existing = _read_index(project, section_id).get("versions", [])
    highest = 0
    for record in existing:
        value = str(record.get("id") or "")
        if value.startswith("v") and value[1:].isdigit():
            highest = max(highest, int(value[1:]))
    return f"v{highest + 1:04d}"


def list_section_versions(
    project: OmniVoiceProject,
    section_id: str,
) -> list[SectionVersion]:
    """Return section versions newest first."""

    project.get_section(section_id)  # validate section id
    payload = _read_index(project, section_id)
    versions: list[SectionVersion] = []
    for record in payload.get("versions", []):
        try:
            versions.append(SectionVersion(**record))
        except TypeError:
            continue
    return list(reversed(versions))


def create_section_snapshot(
    project: OmniVoiceProject,
    section_id: str,
    *,
    reason: str = "manual snapshot",
) -> Optional[SectionVersion]:
    """Snapshot one generated section, returning None if it has no final WAV."""

    section = project.get_section(section_id)
    section_dir = _section_dir(project, section.id)
    final_path = (
        project.root / section.audio_file
        if section.audio_file
        else section_dir / f"{section.id}.wav"
    )
    if not final_path.exists():
        return None

    version_id = _next_version_id(project, section.id)
    history_root = _history_root(project, section.id)
    snapshot_dir = history_root / version_id
    if snapshot_dir.exists():
        raise FileExistsError(snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=False)

    # Copy only generation artifacts. Never copy the history directory into
    # itself, which would make each version recursively contain older versions.
    for directory in ("chunks", "beats"):
        source = section_dir / directory
        if source.exists():
            shutil.copytree(source, snapshot_dir / directory)

    for filename in ("text.txt", "metadata.json"):
        source = section_dir / filename
        if source.exists():
            shutil.copy2(source, snapshot_dir / filename)

    shutil.copy2(final_path, snapshot_dir / f"{section.id}.wav")
    _atomic_json(
        snapshot_dir / "section.json",
        {
            "version": HISTORY_FORMAT_VERSION,
            "project_source_hash": project.manifest.source_hash,
            "section": asdict(section),
        },
    )

    record = SectionVersion(
        id=version_id,
        section_id=section.id,
        created_at=_utc_now(),
        reason=(reason or "manual snapshot").strip(),
        status=section.status,
        source_hash=project.manifest.source_hash,
        snapshot_dir=str(snapshot_dir.relative_to(project.root)),
        audio_file=str((snapshot_dir / f"{section.id}.wav").relative_to(project.root)),
    )
    index = _read_index(project, section.id)
    index["section_id"] = section.id
    index.setdefault("versions", []).append(asdict(record))
    _atomic_json(_index_path(project, section.id), index)
    return record


def _section_from_dict(data: dict[str, Any]) -> ProjectSection:
    beats: list[ProjectBeat] = []
    for beat_data in data.get("beats", []):
        chunks = [ProjectChunk(**chunk) for chunk in beat_data.get("chunks", [])]
        fields = dict(beat_data)
        fields["chunks"] = chunks
        beats.append(ProjectBeat(**fields))
    fields = dict(data)
    fields["beats"] = beats
    return ProjectSection(**fields)


def restore_section_version(
    project: OmniVoiceProject,
    section_id: str,
    version_id: str,
    *,
    snapshot_current: bool = True,
) -> SectionVersion:
    """Restore a coherent section snapshot and sync project/status checkpoints."""

    section_id = section_id.upper()
    current = project.get_section(section_id)
    versions = {item.id: item for item in list_section_versions(project, section_id)}
    if version_id not in versions:
        raise KeyError(f"Unknown section version: {section_id}/{version_id}")
    version = versions[version_id]

    snapshot_dir = project.root / version.snapshot_dir
    state_path = snapshot_dir / "section.json"
    if not state_path.exists():
        raise FileNotFoundError(state_path)
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    saved_hash = payload.get("project_source_hash")
    if saved_hash and saved_hash != project.manifest.source_hash:
        raise ValueError(
            "Section version belongs to a different project script/source hash"
        )

    if snapshot_current:
        create_section_snapshot(
            project,
            section_id,
            reason=f"before restoring {version_id}",
        )

    section_dir = _section_dir(project, section_id)
    section_dir.mkdir(parents=True, exist_ok=True)
    for directory in ("chunks", "beats"):
        destination = section_dir / directory
        if destination.exists():
            shutil.rmtree(destination)
        source = snapshot_dir / directory
        if source.exists():
            shutil.copytree(source, destination)
        else:
            destination.mkdir(parents=True, exist_ok=True)

    for filename in ("text.txt", "metadata.json", f"{section_id}.wav"):
        source = snapshot_dir / filename
        destination = section_dir / filename
        if source.exists():
            shutil.copy2(source, destination)
        elif destination.exists() and filename.endswith(".wav"):
            destination.unlink()

    restored = _section_from_dict(payload["section"])
    final_path = section_dir / f"{section_id}.wav"
    if final_path.exists():
        restored.audio_file = str(final_path.relative_to(project.root))

    for index, section in enumerate(project.manifest.sections):
        if section.id == section_id:
            project.manifest.sections[index] = restored
            break
    else:
        raise KeyError(f"Unknown section: {section_id}")

    project.save()
    write_section_status(project)
    return version


def section_version_audio(
    project: OmniVoiceProject,
    section_id: str,
    version_id: str,
) -> Path:
    versions = {item.id: item for item in list_section_versions(project, section_id)}
    if version_id not in versions:
        raise KeyError(f"Unknown section version: {section_id}/{version_id}")
    record = versions[version_id]
    if not record.audio_file:
        raise FileNotFoundError(f"{section_id}/{version_id} has no archived audio")
    path = project.root / record.audio_file
    if not path.exists():
        raise FileNotFoundError(path)
    return path
