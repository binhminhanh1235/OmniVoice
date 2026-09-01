import json
from pathlib import Path

from omnivoice.project import OmniVoiceProject
from omnivoice.section_history import (
    create_section_snapshot,
    list_section_versions,
    restore_section_version,
    section_version_audio,
)
from omnivoice.section_status import write_section_status


SCRIPT = """# History Test

## S01 — 0:00–0:10
A short section for version history testing.
"""


def _make_generated(project: OmniVoiceProject, marker: bytes) -> None:
    section = project.get_section("S01")
    beat = section.beats[0]
    chunk = beat.chunks[0]
    section_dir = project.root / "sections" / "S01"
    chunk_path = section_dir / "chunks" / f"{chunk.id}.wav"
    report_path = section_dir / "chunks" / f"{chunk.id}.json"
    beat_path = section_dir / "beats" / f"{beat.id}.wav"
    section_path = section_dir / "S01.wav"

    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    beat_path.parent.mkdir(parents=True, exist_ok=True)
    chunk_path.write_bytes(marker + b"-chunk")
    report_path.write_text(json.dumps({"marker": marker.decode()}), encoding="utf-8")
    beat_path.write_bytes(marker + b"-beat")
    section_path.write_bytes(marker + b"-section")

    chunk.audio_file = str(chunk_path.relative_to(project.root))
    chunk.report_file = str(report_path.relative_to(project.root))
    chunk.status = "verified"
    beat.audio_file = str(beat_path.relative_to(project.root))
    beat.status = "verified"
    section.audio_file = str(section_path.relative_to(project.root))
    section.status = "verified"
    project.save()
    write_section_status(project)


def test_snapshot_restores_complete_section_checkpoint(tmp_path: Path):
    project = OmniVoiceProject.create(SCRIPT, tmp_path / "project")
    _make_generated(project, b"v1")

    version = create_section_snapshot(project, "S01", reason="before edit")
    assert version is not None
    assert version.id == "v0001"
    assert section_version_audio(project, "S01", "v0001").read_bytes() == b"v1-section"

    _make_generated(project, b"v2")
    restore_section_version(project, "S01", "v0001", snapshot_current=True)

    reloaded = OmniVoiceProject.load(project.root)
    section = reloaded.get_section("S01")
    beat = section.beats[0]
    chunk = beat.chunks[0]

    assert (project.root / section.audio_file).read_bytes() == b"v1-section"
    assert (project.root / beat.audio_file).read_bytes() == b"v1-beat"
    assert (project.root / chunk.audio_file).read_bytes() == b"v1-chunk"
    report = json.loads((project.root / chunk.report_file).read_text(encoding="utf-8"))
    assert report["marker"] == "v1"
    assert section.status == "verified"
    assert beat.status == "verified"
    assert chunk.status == "verified"

    sidecar = json.loads((project.root / "section-status.json").read_text(encoding="utf-8"))
    assert sidecar["sections"]["S01"]["status"] == "verified"

    versions = list_section_versions(reloaded, "S01")
    assert [item.id for item in versions] == ["v0002", "v0001"]
    assert versions[0].reason == "before restoring v0001"
    assert section_version_audio(reloaded, "S01", "v0002").read_bytes() == b"v2-section"


def test_snapshot_returns_none_before_section_has_audio(tmp_path: Path):
    project = OmniVoiceProject.create(SCRIPT, tmp_path / "project")
    assert create_section_snapshot(project, "S01") is None
    assert list_section_versions(project, "S01") == []
