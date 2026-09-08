#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Small, reproducible performance benchmark helpers for OmniVoice inference.

The benchmark deliberately measures raw ``model.generate`` first.  Keeping the
baseline below Project Studio / ASR verification makes decoder optimizations
comparable even when storage, network mounts, or Whisper placement differ.

The primary metric is real-time factor (RTF):

    generation wall time / generated audio duration

RTF < 1.0 means faster-than-real-time synthesis.  CUDA peak allocation is also
recorded when the model is hosted on a CUDA device.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Optional, Sequence

import numpy as np
import torch


DEFAULT_BENCHMARK_TEXTS: tuple[str, ...] = (
    "Not every time you step in, you are actually helping.",
    "The question is what happens next. Do they come back and listen? Do they reflect?",
    "Love is not unlimited access. Forgiveness is not instant trust. Helping a person is not the same as helping the pattern that keeps hurting them.",
)


@dataclass(frozen=True)
class BenchmarkSampleResult:
    sample: str
    repetition: int
    text_chars: int
    text_words: int
    elapsed_seconds: float
    audio_duration_seconds: float
    rtf: float
    peak_cuda_memory_mb: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkSummary:
    samples: int
    total_elapsed_seconds: float
    total_audio_seconds: float
    weighted_rtf: float
    mean_rtf: float
    median_rtf: float
    fastest_rtf: float
    slowest_rtf: float
    max_peak_cuda_memory_mb: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_results(results: Sequence[BenchmarkSampleResult]) -> BenchmarkSummary:
    if not results:
        raise ValueError("benchmark results cannot be empty")

    total_elapsed = sum(item.elapsed_seconds for item in results)
    total_audio = sum(item.audio_duration_seconds for item in results)
    rtfs = [item.rtf for item in results]
    peaks = [
        item.peak_cuda_memory_mb
        for item in results
        if item.peak_cuda_memory_mb is not None
    ]
    return BenchmarkSummary(
        samples=len(results),
        total_elapsed_seconds=total_elapsed,
        total_audio_seconds=total_audio,
        weighted_rtf=total_elapsed / max(total_audio, 1e-9),
        mean_rtf=statistics.fmean(rtfs),
        median_rtf=statistics.median(rtfs),
        fastest_rtf=min(rtfs),
        slowest_rtf=max(rtfs),
        max_peak_cuda_memory_mb=max(peaks) if peaks else None,
    )


def _model_device(model: Any) -> str:
    try:
        return str(model.device)
    except Exception:
        return "cpu"


def _cuda_index(device: str) -> Optional[int]:
    if not device.startswith("cuda") or not torch.cuda.is_available():
        return None
    if ":" not in device:
        return torch.cuda.current_device()
    try:
        return int(device.rsplit(":", 1)[1])
    except ValueError:
        return torch.cuda.current_device()


def _synchronize(device: str) -> None:
    index = _cuda_index(device)
    if index is not None:
        torch.cuda.synchronize(index)


def _reset_peak_memory(device: str) -> None:
    index = _cuda_index(device)
    if index is not None:
        torch.cuda.reset_peak_memory_stats(index)


def _peak_memory_mb(device: str) -> Optional[float]:
    index = _cuda_index(device)
    if index is None:
        return None
    return float(torch.cuda.max_memory_allocated(index) / (1024**2))


def benchmark_generate(
    model: Any,
    texts: Optional[Iterable[str]] = None,
    *,
    language: Optional[str] = "en",
    generation_config: Any = None,
    warmup: int = 1,
    repeat: int = 1,
    generate_kwargs: Optional[dict[str, Any]] = None,
) -> list[BenchmarkSampleResult]:
    """Benchmark raw ``model.generate`` calls and return per-sample metrics.

    Warmup calls are intentionally excluded from results.  Each measured call
    is synchronized at CUDA boundaries so elapsed wall time reflects completed
    GPU work rather than merely queued kernels.
    """

    items = [str(text).strip() for text in (texts or DEFAULT_BENCHMARK_TEXTS)]
    items = [text for text in items if text]
    if not items:
        raise ValueError("at least one non-empty benchmark text is required")
    if warmup < 0:
        raise ValueError("warmup must be >= 0")
    if repeat < 1:
        raise ValueError("repeat must be >= 1")

    kwargs = dict(generate_kwargs or {})
    if language is not None:
        kwargs.setdefault("language", language)
    if generation_config is not None:
        kwargs["generation_config"] = generation_config

    device = _model_device(model)
    for index in range(warmup):
        model.generate(text=items[index % len(items)], **kwargs)
        _synchronize(device)

    sampling_rate = int(model.sampling_rate)
    if sampling_rate <= 0:
        raise ValueError("model.sampling_rate must be > 0")

    results: list[BenchmarkSampleResult] = []
    for repetition in range(1, repeat + 1):
        for sample_index, text in enumerate(items, start=1):
            _synchronize(device)
            _reset_peak_memory(device)
            started = time.perf_counter()
            audios = model.generate(text=text, **kwargs)
            _synchronize(device)
            elapsed = time.perf_counter() - started

            if not audios:
                raise RuntimeError("model.generate returned no audio")
            audio = np.asarray(audios[0]).reshape(-1)
            audio_duration = float(audio.size / sampling_rate)
            rtf = elapsed / max(audio_duration, 1e-9)
            results.append(
                BenchmarkSampleResult(
                    sample=f"S{sample_index:02d}",
                    repetition=repetition,
                    text_chars=len(text),
                    text_words=len(text.split()),
                    elapsed_seconds=elapsed,
                    audio_duration_seconds=audio_duration,
                    rtf=rtf,
                    peak_cuda_memory_mb=_peak_memory_mb(device),
                )
            )
    return results
