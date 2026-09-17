import zipfile

import pytest

from omnivoice.cli.section_export_ui import build_section_export_demo
from omnivoice.project import OmniVoiceProject
from omnivoice.section_export import create_project_audio_archive, section_ids


SCRIPT = """# Export Demo

## S01 — 0:00–0:10

First generated section.

## S02 — 0:10–0:20

Second section is intentionally missing audio in one test.
"""


class FakeModel:
    sampling_rate = 24000


def test_project_audio_archive_keeps_native_bytes_and_manifest_order(tmp_path):
    project = OmniVoiceProject.create(SCRIPT, tmp_path / "project")
    assert section_ids(project) == ["S01", "S02"]

    expected = {}
    for section_id, payload in (("S01", b"native-one"), ("S02", b"native-two")):
        section = project.get_section(section_id)
        wav_path = project.root / "sections" / section_id / f"{section_id}.wav"
        wav_path.write_bytes(payload)
        section.audio_file = str(wav_path.relative_to(project.root))
        section.status = "verified"
        expected[f"{section_id}.wav"] = payload
    project.save()

    result = create_project_audio_archive(project)
    assert result.included == ("S01", "S02")
    assert result.skipped == ()
    assert result.archive.exists()

    with zipfile.ZipFile(result.archive) as bundle:
        assert bundle.namelist() == ["S01.wav", "S02.wav"]
        for name, payload in expected.items():
            assert bundle.read(name) == payload


def test_project_audio_archive_allows_partial_project(tmp_path):
    project = OmniVoiceProject.create(SCRIPT, tmp_path / "project")
    section = project.get_section("S01")
    wav_path = project.root / "sections" / "S01" / "S01.wav"
    wav_path.write_bytes(b"native-one")
    section.audio_file = str(wav_path.relative_to(project.root))
    project.save()

    result = create_project_audio_archive(project)
    assert result.included == ("S01",)
    assert result.skipped == ("S02: no generated section audio",)


def test_project_audio_archive_rejects_no_audio_and_external_path(tmp_path):
    project = OmniVoiceProject.create(SCRIPT, tmp_path / "project")
    with pytest.raises(ValueError, match="no generated section audio"):
        create_project_audio_archive(project)

    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"outside")
    section = project.get_section("S01")
    section.audio_file = str(outside)
    project.save()
    with pytest.raises(ValueError, match="outside project root"):
        create_project_audio_archive(project)


def test_section_export_gradio_smoke(tmp_path):
    demo = build_section_export_demo(FakeModel(), tmp_path / "studio")
    assert demo is not None
