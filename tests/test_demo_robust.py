#!/usr/bin/env python3

from __future__ import annotations

import numpy as np

from omnivoice.cli.demo_robust import (
    _should_use_robust,
    _to_gradio_audio,
    create_generate_fn,
)
from omnivoice.robust_longform import RobustLongFormConfig


class _FakePrompt:
    pass


class _FakeModel:
    sampling_rate = 24000

    def __init__(self):
        self.generated_texts = []
        self._asr_pipe = None

    def create_voice_clone_prompt(
        self,
        ref_audio,
        ref_text=None,
        preprocess_prompt=True,
    ):
        assert ref_audio == "reference.wav"
        return _FakePrompt()

    def generate(self, text, generation_config=None, **kwargs):
        self.generated_texts.append(text)
        return [np.full(240, 0.1, dtype=np.float32)]

    def load_asr_model(self, model_name=None, device=None):
        self._asr_pipe = object()

    def transcribe(self, audio):
        return self.generated_texts[-1]


def test_should_use_robust_for_multiple_sentences():
    assert _should_use_robust(
        "This is one sentence. This is another sentence.",
        enabled=True,
        min_words=100,
        max_chunk_words=20,
        max_chunk_chars=180,
        duration=None,
    )


def test_should_not_use_robust_when_duration_is_set():
    assert not _should_use_robust(
        "This is one sentence. This is another sentence.",
        enabled=True,
        min_words=1,
        max_chunk_words=20,
        max_chunk_chars=180,
        duration=10.0,
    )


def test_to_gradio_audio_clips_waveform():
    rate, waveform = _to_gradio_audio(
        np.array([-2.0, 0.0, 2.0], dtype=np.float32),
        24000,
    )
    assert rate == 24000
    assert waveform.dtype == np.int16
    assert waveform.tolist() == [-32767, 0, 32767]


def test_generate_fn_normalizes_html_and_uses_robust_chunks():
    model = _FakeModel()
    config = RobustLongFormConfig(
        max_chunk_words=20,
        max_chunk_chars=180,
        max_retries=1,
        verify_with_asr=False,
        normalize_chunk_rms=False,
        exact_chunk_edges=False,
    )
    generate = create_generate_fn(
        model,
        config,
        robust_enabled=True,
        robust_min_words=2,
    )

    audio, status = generate(
        "Patterns that reject truth. &#x20; Patterns that avoid responsibility.",
        "English",
        "reference.wav",
        "",
        4,
        2.0,
        True,
        1.0,
        None,
        True,
        True,
        "clone",
        ref_text="Reference sentence.",
    )

    assert audio[0] == 24000
    assert "Done (robust)" in status
    assert "&#x20;" not in " ".join(model.generated_texts)
    assert model.generated_texts == [
        "Patterns that reject truth.",
        "Patterns that avoid responsibility.",
    ]
