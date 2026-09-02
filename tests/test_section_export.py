import shutil

import numpy as np
import pytest
import soundfile as sf

from omnivoice.cli.section_export_ui import build_section_export_demo
from omnivoice.project import OmniVoiceProject
from omnivoice.section_export import export_section_mp3s, section_ids


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


def test_export_rejects_empty_or_unknown_selection(tmp_path):
    project = OmniVoiceProject.create(SCRIPT, tmp_path / "project")

    with pytest.raises(ValueError, match="Select at least one"):
        export_section_mp3s(project, [])

    with pytest.raises(ValueError, match="Unknown sections"):
        export_section_mp3s(project, ["S99"])


def test_section_export_gradio_smoke(tmp_path):
    demo = build_section_export_demo(FakeModel(), tmp_path / "studio")
    assert demo is not None
