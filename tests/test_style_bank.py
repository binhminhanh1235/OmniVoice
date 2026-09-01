import json

import numpy as np

from omnivoice import VoiceClonePrompt
from omnivoice.project import OmniVoiceProject
from omnivoice.robust_longform import RobustLongFormConfig
from omnivoice.style_bank import StyleBankProjectRunner
from omnivoice.voice_library import VoiceLibrary


SCRIPT = """# Style Project

## S01 — 0:00–0:20

[WARM] Warm narration should use the warm reference voice.

## S02 — 0:20–0:40

[SOFT] Soft narration should use the soft reference voice.

## S03 — 0:40–1:00

[EMPHASIZE] Emphasis should fall back to warm when emphasize is absent.
"""


def _prompt(label: str) -> VoiceClonePrompt:
    return VoiceClonePrompt(
        ref_audio_tokens=np_to_tensor([1, 2, 3, 4]),
        ref_text=label,
        ref_rms=0.1,
    )


def np_to_tensor(values):
    import torch

    return torch.tensor(values, dtype=torch.long).reshape(1, -1)


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
                "instruct": kwargs.get("instruct"),
            }
        )
        return [np.full(max(800, len(text) * 20), 0.01, dtype=np.float32)]


def test_style_bank_uses_reference_variant_per_beat(tmp_path):
    voices = VoiceLibrary(tmp_path / "voices")
    voices.save_prompt("David", _prompt("default"), variant="DEFAULT")
    voices.save_prompt("David", _prompt("warm"), variant="WARM")
    voices.save_prompt("David", _prompt("soft"), variant="SOFT")

    project = OmniVoiceProject.create(
        SCRIPT,
        tmp_path / "project",
        max_chunk_words=30,
        max_chunk_chars=240,
    )
    model = FakeModel()
    runner = StyleBankProjectRunner(
        model,
        voices,
        voice_name="David",
        preferred_variant="AUTO",
    )
    runner.generate(
        project,
        robust_config=RobustLongFormConfig(
            verify_with_asr=False,
            max_chunk_words=30,
            max_chunk_chars=240,
        ),
        language="en",
    )

    assert [call["prompt_text"] for call in model.calls] == [
        "warm",
        "soft",
        "warm",
    ]
    # Generic emotion tags still never become unsupported instruct strings.
    assert all(call["instruct"] is None for call in model.calls)

    reports = []
    for section in project.manifest.sections:
        for beat in section.beats:
            for chunk in beat.chunks:
                reports.append(
                    json.loads(
                        (project.root / chunk.report_file).read_text(encoding="utf-8")
                    )
                )

    assert [report["voice_variant"] for report in reports] == [
        "WARM",
        "SOFT",
        "WARM",
    ]
    assert [report["voice_variant_fallback"] for report in reports] == [
        False,
        False,
        True,
    ]


def test_explicit_variant_locks_whole_project(tmp_path):
    voices = VoiceLibrary(tmp_path / "voices")
    voices.save_prompt("David", _prompt("default"), variant="DEFAULT")
    voices.save_prompt("David", _prompt("warm"), variant="WARM")
    voices.save_prompt("David", _prompt("soft"), variant="SOFT")

    project = OmniVoiceProject.create(
        SCRIPT,
        tmp_path / "project",
        max_chunk_words=30,
        max_chunk_chars=240,
    )
    model = FakeModel()
    runner = StyleBankProjectRunner(
        model,
        voices,
        voice_name="David",
        preferred_variant="DEFAULT",
    )
    runner.generate(
        project,
        robust_config=RobustLongFormConfig(
            verify_with_asr=False,
            max_chunk_words=30,
            max_chunk_chars=240,
        ),
    )

    assert {call["prompt_text"] for call in model.calls} == {"default"}
