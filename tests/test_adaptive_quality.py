#!/usr/bin/env python3

import numpy as np

from omnivoice.adaptive_quality import (
    AdaptiveQualityConfig,
    AdaptiveRobustLongFormGenerator,
    analyze_pacing,
)
from omnivoice.models.omnivoice import OmniVoiceGenerationConfig
from omnivoice.robust_longform import RobustLongFormConfig


def test_pacing_guard_rejects_implausibly_fast_global_rate():
    config = AdaptiveQualityConfig(
        min_words_for_pacing=4,
        max_global_wps=4.0,
    )
    metrics = analyze_pacing(
        "one two three four five six seven eight",
        1.5,
        [],
        config,
    )
    assert metrics.anomaly is True
    assert "global_speed" in metrics.reasons
    assert metrics.global_wps > 5.0


def test_pacing_guard_detects_local_speed_spike():
    config = AdaptiveQualityConfig(
        min_words_for_pacing=4,
        max_global_wps=10.0,
        max_local_wps=5.0,
        max_local_speed_ratio=1.6,
        pacing_window_words=4,
    )
    timings = [
        (0.0, 0.5, 1),
        (0.5, 1.0, 1),
        (1.0, 1.5, 1),
        (1.5, 2.0, 1),
        (2.0, 2.15, 1),
        (2.15, 2.30, 1),
        (2.30, 2.45, 1),
        (2.45, 2.60, 1),
        (2.60, 3.10, 1),
        (3.10, 3.60, 1),
        (3.60, 4.10, 1),
        (4.10, 4.60, 1),
    ]
    metrics = analyze_pacing(
        "one two three four five six seven eight nine ten eleven twelve",
        4.6,
        timings,
        config,
    )
    assert metrics.anomaly is True
    assert "local_speed_spike" in metrics.reasons
    assert metrics.max_local_wps > metrics.median_local_wps


class _RetryASR:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def __call__(self, audio_input, return_timestamps=None):
        del audio_input, return_timestamps
        return self.outputs.pop(0)


class _AdaptiveFakeModel:
    sampling_rate = 10

    def __init__(self, asr_outputs, audio_lengths=None):
        self._asr_pipe = _RetryASR(asr_outputs)
        self.audio_lengths = list(audio_lengths or [30] * len(asr_outputs))
        self.generate_calls = []

    def generate(self, text, generation_config=None, **kwargs):
        self.generate_calls.append(
            {
                "text": text,
                "config": generation_config,
                "kwargs": dict(kwargs),
            }
        )
        length = self.audio_lengths.pop(0)
        return [np.ones(length, dtype=np.float32)]

    def transcribe(self, audio):
        del audio
        raise AssertionError("timestamp ASR path should be used in this test")

    def load_asr_model(self, model_name=None, device=None):
        del model_name, device


def test_adaptive_retry_reduces_temperature_after_repetition():
    outputs = [
        {
            "text": "Patterns reject truth reject truth and avoid responsibility.",
            "chunks": [],
        },
        {
            "text": "Patterns reject truth and avoid responsibility.",
            "chunks": [],
        },
    ]
    model = _AdaptiveFakeModel(outputs, audio_lengths=[30, 30])
    robust = RobustLongFormConfig(
        max_retries=2,
        max_split_depth=0,
        normalize_chunk_rms=False,
    )
    generator = AdaptiveRobustLongFormGenerator(model, robust)
    result = generator.generate(
        "Patterns reject truth and avoid responsibility.",
        generation_config=OmniVoiceGenerationConfig(position_temperature=1.2),
    )

    assert result.all_verified is True
    assert len(model.generate_calls) == 2
    first = model.generate_calls[0]["config"].position_temperature
    second = model.generate_calls[1]["config"].position_temperature
    assert second < first
    assert "repetition" in result.reports[0].recovered_from
    assert any("position_temperature" in item for item in result.reports[0].retry_actions)


def test_adaptive_retry_slows_next_attempt_after_pacing_failure():
    transcript = "one two three four five six seven eight nine ten"
    outputs = [
        {"text": transcript, "chunks": []},
        {"text": transcript, "chunks": []},
    ]
    # First candidate: 1 second = 10 words/s -> reject. Second: 4 seconds = 2.5 words/s.
    model = _AdaptiveFakeModel(outputs, audio_lengths=[10, 40])
    robust = RobustLongFormConfig(
        max_retries=2,
        max_split_depth=0,
        normalize_chunk_rms=False,
    )
    quality = AdaptiveQualityConfig(
        min_words_for_pacing=4,
        max_global_wps=4.5,
    )
    generator = AdaptiveRobustLongFormGenerator(model, robust, quality)
    result = generator.generate(
        transcript,
        generation_config=OmniVoiceGenerationConfig(position_temperature=1.0),
        speed=1.0,
    )

    assert result.all_verified is True
    assert len(model.generate_calls) == 2
    assert model.generate_calls[1]["kwargs"]["speed"] < 1.0
    assert "pacing" in result.reports[0].recovered_from
    assert any(item.startswith("speed->") for item in result.reports[0].retry_actions)
