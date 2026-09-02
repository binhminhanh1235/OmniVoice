import shutil
import zipfile

import numpy as np
import pytest
import soundfile as sf

from omnivoice.cli.section_export_ui import build_section_export_demo
from omnivoice.project import OmniVoiceProject
from omnivoice.section_export import (
    create_section_mp3_archive,
    export_section_mp3s,
    section_ids,
)


SCRIPT = """# Export Demo

## S01 — 0:00–0:10

First generated section.

## S02 — 0:10–0:20

Second section is intentionally missing audio in one test.
"""


class FakeModel:
    sampling_rate = 24000


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_export_selected_sections_to_mp3_and_reuse_cache(tmp_path):
    project = OmniVoiceProject.create(SCRIPT, tmp_path / "project")
    assert section_ids(project) == ["S01", "S02"]

    section = project.get_section("S01")
    wav_path = project.root / "sections" / "S01" / "S01.wav"
    sf.write(
        wav_path,
        np.zeros(2400, dtype=np.float32),
        24000,
        subtype="PCM_16",
    )
    section.audio_file = str(wav_path.relative_to(project.root))
    section.status = "verified"
    project.save()

    first = export_section_mp3s(project, ["S01", "S02"])
    assert [path.name for path in first.files] == ["S01.mp3"]
    assert first.files[0].exists()
    assert first.files[0].stat().st_size > 0
    assert first.reused == ()
    assert first.skipped == ("S02: no generated section audio",)

    second = export_section_mp3s(project, ["S01"])
    assert second.files == first.files
    assert second.reused == ("S01",)
    assert second.skipped == ()


def test_download_all_archive_contains_only_selected_project_mp3s(tmp_path):
    project = OmniVoiceProject.create(SCRIPT, tmp_path / "project")
    export_dir = project.root / "exports" / "mp3"
    export_dir.mkdir(parents=True, exist_ok=True)
    first = export_dir / "S01.mp3"
    second = export_dir / "S02.mp3"
    first.write_bytes(b"fake-mp3-one")
    second.write_bytes(b"fake-mp3-two")

    archive = create_section_mp3_archive(project, [first, second])
    assert archive.exists()
    assert archive.name == f"{project.root.name}-selected-sections.zip"
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.namelist() == ["S01.mp3", "S02.mp3"]
        assert bundle.read("S01.mp3") == b"fake-mp3-one"
        assert bundle.read("S02.mp3") == b"fake-mp3-two"

    with pytest.raises(ValueError, match="At least two"):
        create_section_mp3_archive(project, [first])

    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"not-project-audio")
    with pytest.raises(ValueError, match="outside project MP3 exports"):
        create_section_mp3_archive(project, [first, outside])


def test_export_rejects_empty_or_unknown_selection(tmp_path):
    project = OmniVoiceProject.create(SCRIPT, tmp_path / "project")

    with pytest.raises(ValueError, match="Select at least one"):
        export_section_mp3s(project, [])

    with pytest.raises(ValueError, match="Unknown sections"):
        export_section_mp3s(project, ["S99"])


def test_section_export_gradio_smoke(tmp_path):
    demo = build_section_export_demo(FakeModel(), tmp_path / "studio")
    assert demo is not None
