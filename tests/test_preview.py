import json
from pathlib import Path

import numpy as np
import torch

from omnivoice import OmniVoiceProject, VoiceClonePrompt, VoiceLibrary
from omnivoice.preview import ProjectPreviewGenerator, select_preview_targets
from omnivoice.robust_longform import RobustLongFormConfig


SCRIPT = """# Preview Demo

## S01 — 0:00–0:20

[WARM] Opening sentence one. Opening sentence two has enough words for another useful chunk.

## S02 — 0:20–0:40

[SOFT] Middle sentence one. Middle sentence two has enough words for another useful chunk.

## S03 — 0:40–1:00

[WARM] Ending sentence one. Ending sentence two has enough words for another useful chunk.
""".strip()


class FakeModel:
    sampling_rate = 8000

    def __init__(self):
        self.calls = []

    def generate(self, text, generation_config=None, **kwargs):
        prompt = kwargs.get("voice_clone_prompt")
        self.calls.append(
            {
                "text": text,
                "prompt_text": prompt.ref_text if prompt is not None else None,
                "speed": kwargs.get("speed"),
            }
        )
        return [np.full(max(1000, len(text) * 20), 0.01, dtype=np.float32)]


def _prompt(label: str) -> VoiceClonePrompt:
    return VoiceClonePrompt(
        ref_audio_tokens=torch.zeros((2, 4), dtype=torch.long),
        ref_text=label,
        ref_rms=0.1,
    )


def _library(root: Path) -> VoiceLibrary:
    voices = VoiceLibrary(root)
    voices.save_prompt("Narrator", _prompt("default prompt"), variant="DEFAULT")
    voices.save_prompt("Narrator", _prompt("warm prompt"), variant="WARM")
    voices.save_prompt("Narrator", _prompt("soft prompt"), variant="SOFT")
    return voices


def test_select_preview_targets_opening_middle_ending(tmp_path: Path):
    project = OmniVoiceProject.create(
        SCRIPT,
        tmp_path / "project",
        max_chunk_words=7,
        max_chunk_chars=90,
    )
    targets = select_preview_targets(project)

    assert [target.label for target in targets] == ["opening", "middle", "ending"]
    assert targets[0].section_id == "S01"
    assert targets[-1].section_id == "S03"


def test_preview_generation_is_non_destructive_and_style_aware(tmp_path: Path):
    project = OmniVoiceProject.create(
        SCRIPT,
        tmp_path / "project",
        max_chunk_words=7,
        max_chunk_chars=90,
    )
    model = FakeModel()
    voices = _library(tmp_path / "voices")

    before_manifest = (project.root / "project.json").read_text(encoding="utf-8")
    before_statuses = [
        chunk.status
        for section in project.manifest.sections
        for beat in section.beats
        for chunk in beat.chunks
    ]

    preview = ProjectPreviewGenerator(
        model,
        voices,
        voice_name="Narrator",
        preferred_variant="AUTO",
    )
    results = preview.generate(
        project,
        robust_config=RobustLongFormConfig(
            verify_with_asr=False,
            max_chunk_words=7,
            max_chunk_chars=90,
        ),
        language="en",
    )

    assert len(results) == 3
    assert all(Path(item.audio_file).exists() for item in results)
    assert all(Path(item.report_file).exists() for item in results)
    assert all(item.verified for item in results)

    # Opening and ending are WARM. The representative middle sample is SOFT.
    resolved = {item.target.label: item.voice_variant for item in results}
    assert resolved["opening"] == "WARM"
    assert resolved["middle"] == "SOFT"
    assert resolved["ending"] == "WARM"

    prompt_texts = [call["prompt_text"] for call in model.calls]
    assert "warm prompt" in prompt_texts
    assert "soft prompt" in prompt_texts

    # Preview files are separate and project checkpoint state is untouched.
    after_manifest = (project.root / "project.json").read_text(encoding="utf-8")
    after_statuses = [
        chunk.status
        for section in project.manifest.sections
        for beat in section.beats
        for chunk in beat.chunks
    ]
    assert after_manifest == before_manifest
    assert after_statuses == before_statuses
    assert set(after_statuses) == {"pending"}

    payload = json.loads(Path(results[1].report_file).read_text(encoding="utf-8"))
    assert payload["voice_variant"] == "SOFT"
    assert payload["preview"]["label"] == "middle"


def test_preview_can_generate_only_one_label(tmp_path: Path):
    project = OmniVoiceProject.create(SCRIPT, tmp_path / "project")
    preview = ProjectPreviewGenerator(
        FakeModel(),
        _library(tmp_path / "voices"),
        voice_name="Narrator",
    )
    results = preview.generate(
        project,
        robust_config=RobustLongFormConfig(verify_with_asr=False),
        labels=["opening"],
    )
    assert [item.target.label for item in results] == ["opening"]
