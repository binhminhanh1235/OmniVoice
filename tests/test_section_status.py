#!/usr/bin/env python3

import json
from pathlib import Path

from omnivoice.project import OmniVoiceProject
from omnivoice.section_status import (
    SECTION_STATUS_NAME,
    ensure_section_status,
    incomplete_section_ids,
    restore_section_status,
    set_section_status,
    write_section_status,
)


SCRIPT = """# Resume Checkpoint Test

## S01 — 0:00–0:10
First section should be remembered after a runtime restart.

## S02 — 0:10–0:20
Second section should remain available for resume generation.
"""


def _project(tmp_path: Path) -> OmniVoiceProject:
    return OmniVoiceProject.create(SCRIPT, tmp_path / "project")


def _fake_completed_section(project: OmniVoiceProject, section_id: str) -> None:
    section = project.get_section(section_id)
    path = project.root / "sections" / section.id / f"{section.id}.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"completed-section")
    section.audio_file = str(path.relative_to(project.root))
    section.status = "verified"
    project.save()


def test_section_status_file_is_created_for_project(tmp_path: Path):
    project = _project(tmp_path)
    path = ensure_section_status(project)

    assert path.name == SECTION_STATUS_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["project_source_hash"] == project.manifest.source_hash
    assert payload["sections"]["S01"]["status"] == "pending"
    assert payload["sections"]["S02"]["status"] == "pending"


def test_restore_uses_verified_sidecar_when_manifest_is_stale(tmp_path: Path):
    project = _project(tmp_path)
    _fake_completed_section(project, "S01")
    write_section_status(project)

    # Simulate a stale project.json after an interrupted/cloud-synced session.
    project.get_section("S01").status = "pending"
    project.save()

    loaded = OmniVoiceProject.load(project.root)
    assert loaded.get_section("S01").status == "pending"

    result = restore_section_status(loaded, sync_manifest=True)

    assert result.restored == ("S01",)
    assert loaded.get_section("S01").status == "verified"
    assert incomplete_section_ids(loaded) == ["S02"]

    reloaded = OmniVoiceProject.load(project.root)
    assert reloaded.get_section("S01").status == "verified"


def test_interrupted_generating_state_recovers_to_pending(tmp_path: Path):
    project = _project(tmp_path)
    ensure_section_status(project)
    set_section_status(project, "S02", "generating")

    loaded = OmniVoiceProject.load(project.root)
    result = restore_section_status(loaded)

    assert result.recovered_interrupted == ("S02",)
    assert loaded.get_section("S02").status == "pending"
    assert "S02" in incomplete_section_ids(loaded)


def test_verified_status_is_not_trusted_when_section_wav_is_missing(tmp_path: Path):
    project = _project(tmp_path)
    section = project.get_section("S01")
    section.status = "verified"
    section.audio_file = "sections/S01/S01.wav"
    project.save()
    write_section_status(project)

    loaded = OmniVoiceProject.load(project.root)
    result = restore_section_status(loaded)

    assert result.invalid_complete == ("S01",)
    assert loaded.get_section("S01").status == "pending"
    assert "S01" in incomplete_section_ids(loaded)


def test_corrupt_sidecar_never_prevents_project_load(tmp_path: Path):
    project = _project(tmp_path)
    path = ensure_section_status(project)
    path.write_text("{not valid json", encoding="utf-8")

    loaded = OmniVoiceProject.load(project.root)
    restore_section_status(loaded)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["sections"]["S01"]["status"] == "pending"
