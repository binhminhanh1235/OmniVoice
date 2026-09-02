import json

import numpy as np
import torch

from omnivoice import VoiceClonePrompt
from omnivoice.voice_library import VoiceLibrary
from omnivoice.voice_stability import evaluate_voice_stability


class FakeStableModel:
    sampling_rate = 8000

    def __init__(self, drop_not=False):
        self.last_text = ""
        self.calls = []
        self.drop_not = drop_not

    def generate(self, text, generation_config=None, **kwargs):
        self.last_text = text
        self.calls.append(text)
        words = max(1, len(text.split()))
        duration = words / 2.5
        return [np.full(int(duration * self.sampling_rate), 0.01, dtype=np.float32)]

    def transcribe(self, audio):
        if self.drop_not and " not " in f" {self.last_text.lower()} ":
            return self.last_text.replace(" not ", " ")
        return self.last_text


def _library(tmp_path):
    library = VoiceLibrary(tmp_path / "voices")
    prompt = VoiceClonePrompt(
        ref_audio_tokens=torch.tensor([[1, 2, 3, 4]], dtype=torch.long),
        ref_text="reference voice",
        ref_rms=0.1,
    )
    library.save_prompt("David", prompt, variant="DEFAULT")
    return library


def test_stable_voice_passes_three_clone_tests_and_persists_report(tmp_path):
    model = FakeStableModel()
    library = _library(tmp_path)

    report = evaluate_voice_stability(
        model,
        library,
        voice_name="David",
        variant="DEFAULT",
    )

    assert report.stable is True
    assert report.passed == report.total == 3
    assert report.score >= 90
    assert len(model.calls) == 3
    assert all(sample.accepted for sample in report.samples)
    assert all(sample.audio_file for sample in report.samples)

    payload = json.loads(open(report.report_file, encoding="utf-8").read())
    assert payload["voice_name"] == "David"
    assert payload["variant"] == "DEFAULT"
    assert len(payload["samples"]) == 3


def test_missing_not_makes_stability_gate_fail(tmp_path):
    model = FakeStableModel(drop_not=True)
    library = _library(tmp_path)

    report = evaluate_voice_stability(
        model,
        library,
        voice_name="David",
    )

    assert report.stable is False
    assert report.passed == 2
    failed = [sample for sample in report.samples if not sample.accepted]
    assert len(failed) == 1
    assert "not" in failed[0].critical_missing
    assert any("semantic-critical" in item for item in report.issues)
