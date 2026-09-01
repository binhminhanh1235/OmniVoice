import numpy as np
import soundfile as sf
import torch

from omnivoice import VoiceClonePrompt
from omnivoice.cli.voice_doctor_ui import (
    build_voice_doctor_demo,
    save_voice_reference,
)
from omnivoice.voice_library import VoiceLibrary


class FakeCloneModel:
    def __init__(self):
        self.calls = []

    def create_voice_clone_prompt(
        self,
        *,
        ref_audio,
        ref_text=None,
        preprocess_prompt=True,
    ):
        self.calls.append((ref_audio, ref_text, preprocess_prompt))
        return VoiceClonePrompt(
            ref_audio_tokens=torch.tensor([[1, 2, 3, 4]], dtype=torch.long),
            ref_text=ref_text or "auto transcript",
            ref_rms=0.1,
        )


def _clean_reference(path):
    sr = 24000
    seconds = 6.0
    t = np.arange(int(sr * seconds), dtype=np.float32) / sr
    carrier = 0.18 * np.sin(2 * np.pi * 180 * t)
    envelope = 0.55 + 0.45 * np.sin(2 * np.pi * 1.7 * t) ** 2
    audio = (carrier * envelope).astype(np.float32)
    audio[:2400] = 0
    audio[-2400:] = 0
    sf.write(path, audio, sr)
    return path


def test_voice_doctor_demo_builds_analysis_only():
    demo = build_voice_doctor_demo()
    assert demo is not None


def test_voice_doctor_demo_builds_with_voice_library(tmp_path):
    demo = build_voice_doctor_demo(FakeCloneModel(), tmp_path / "workspace")
    assert demo is not None


def test_analyze_and_save_reuses_same_reference_file(tmp_path):
    model = FakeCloneModel()
    library = VoiceLibrary(tmp_path / "voices")
    audio_path = _clean_reference(tmp_path / "reference.wav")

    report, message = save_voice_reference(
        model,
        library,
        audio_path=audio_path,
        voice_name="David",
        variant="WARM",
        ref_text="This is the exact reference transcript.",
        language="en",
    )

    assert report.recommended is True
    assert len(model.calls) == 1
    assert model.calls[0][0] == audio_path
    assert model.calls[0][1] == "This is the exact reference transcript."
    entry = library.get("David")
    assert "WARM" in entry.variants
    assert entry.variants["WARM"].reference_file is not None
    assert "Saved voice 'David'" in message


def test_low_quality_reference_requires_explicit_override(tmp_path):
    model = FakeCloneModel()
    library = VoiceLibrary(tmp_path / "voices")
    sr = 24000
    audio_path = tmp_path / "too-short.wav"
    sf.write(audio_path, np.zeros(sr, dtype=np.float32), sr)

    try:
        save_voice_reference(
            model,
            library,
            audio_path=audio_path,
            voice_name="Bad",
        )
    except ValueError as exc:
        assert "not recommended" in str(exc)
    else:
        raise AssertionError("Expected a low-quality reference to be blocked")

    assert model.calls == []
