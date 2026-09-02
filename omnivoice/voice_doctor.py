#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Reference-audio diagnostics for reliable voice cloning.

Voice Doctor is intentionally non-destructive. It measures a reference clip and
returns a score plus recommendations before ``create_voice_clone_prompt`` is
called. It does not trim, denoise, normalize, or otherwise alter user audio.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf


@dataclass(frozen=True)
class VoiceDoctorConfig:
    recommended_min_seconds: float = 3.0
    recommended_max_seconds: float = 10.0
    hard_min_seconds: float = 1.5
    hard_max_seconds: float = 20.0
    silence_dbfs: float = -45.0
    ideal_silence_min: float = 0.01
    ideal_silence_max: float = 0.30
    max_silence_ratio: float = 0.50
    clipping_threshold: float = 0.999
    max_clipping_ratio: float = 0.0005
    ideal_rms_min_dbfs: float = -30.0
    ideal_rms_max_dbfs: float = -12.0
    max_dc_offset: float = 0.01
    frame_ms: float = 30.0


@dataclass(frozen=True)
class VoiceDoctorReport:
    path: str
    score: int
    grade: str
    recommended: bool
    duration_seconds: float
    sample_rate: int
    channels: int
    peak_dbfs: float
    rms_dbfs: float
    clipping_ratio: float
    silence_ratio: float
    dc_offset: float
    noise_floor_dbfs: float
    dynamic_range_db: float
    issues: tuple[str, ...] = field(default_factory=tuple)
    recommendations: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dbfs(value: float, floor: float = -120.0) -> float:
    value = abs(float(value))
    if value <= 1e-12:
        return floor
    return max(floor, float(20.0 * np.log10(value)))


def _frame_rms(audio: np.ndarray, sample_rate: int, frame_ms: float) -> np.ndarray:
    frame = max(1, int(sample_rate * frame_ms / 1000.0))
    if audio.size == 0:
        return np.zeros(0, dtype=np.float32)
    count = int(np.ceil(audio.size / frame))
    padded = np.pad(audio, (0, count * frame - audio.size))
    frames = padded.reshape(count, frame)
    return np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1)).astype(np.float32)


def analyze_voice_reference(
    audio_path: str | Path,
    config: VoiceDoctorConfig | None = None,
) -> VoiceDoctorReport:
    """Analyze a reference file and return an actionable suitability report."""

    cfg = config or VoiceDoctorConfig()
    path = Path(audio_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(path)

    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    channels = int(audio.shape[1])
    mono = np.mean(audio, axis=1, dtype=np.float32).reshape(-1)
    duration = float(len(mono) / max(1, int(sample_rate)))

    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64)))) if mono.size else 0.0
    peak_dbfs = _dbfs(peak)
    rms_dbfs = _dbfs(rms)
    clipping_ratio = float(np.mean(np.abs(mono) >= cfg.clipping_threshold)) if mono.size else 0.0
    dc_offset = float(np.mean(mono)) if mono.size else 0.0

    frames = _frame_rms(mono, int(sample_rate), cfg.frame_ms)
    frame_db = np.asarray([_dbfs(value) for value in frames], dtype=np.float32)
    silence_ratio = float(np.mean(frame_db <= cfg.silence_dbfs)) if frame_db.size else 1.0

    non_silent = frame_db[frame_db > cfg.silence_dbfs]
    if non_silent.size:
        noise_floor = float(np.percentile(non_silent, 15))
        speech_level = float(np.percentile(non_silent, 85))
        dynamic_range = max(0.0, speech_level - noise_floor)
    else:
        noise_floor = -120.0
        dynamic_range = 0.0

    score = 100
    issues: list[str] = []
    recs: list[str] = []

    if duration < cfg.hard_min_seconds:
        score -= 40
        issues.append("reference_too_short")
        recs.append("Use a clean 3–10 second clip with one complete spoken phrase.")
    elif duration < cfg.recommended_min_seconds:
        score -= 18
        issues.append("reference_short")
        recs.append("A 3–10 second reference is usually more stable.")
    elif duration > cfg.hard_max_seconds:
        score -= 35
        issues.append("reference_too_long")
        recs.append("Choose one clean 3–10 second segment instead of the full recording.")
    elif duration > cfg.recommended_max_seconds:
        score -= 12
        issues.append("reference_long")
        recs.append("Prefer a 3–10 second segment for faster and more stable cloning.")

    if clipping_ratio > cfg.max_clipping_ratio:
        score -= 28
        issues.append("clipping")
        recs.append("Choose a reference without clipped peaks or re-record at a lower level.")
    elif peak_dbfs > -0.5:
        score -= 8
        issues.append("peak_too_hot")
        recs.append("Leave a little peak headroom to avoid edge distortion.")

    if rms_dbfs < cfg.ideal_rms_min_dbfs:
        score -= 16
        issues.append("too_quiet")
        recs.append("Use a clearer/louder reference; avoid very low recording gain.")
    elif rms_dbfs > cfg.ideal_rms_max_dbfs:
        score -= 10
        issues.append("too_loud")
        recs.append("Use a reference with more headroom and less aggressive limiting.")

    if silence_ratio > cfg.max_silence_ratio:
        score -= 22
        issues.append("too_much_silence")
        recs.append("Trim long silence and keep mostly continuous speech.")
    elif silence_ratio < cfg.ideal_silence_min:
        score -= 3
        issues.append("no_edge_silence")
        recs.append("A tiny amount of natural edge silence is helpful, but do not pad heavily.")
    elif silence_ratio > cfg.ideal_silence_max:
        score -= 8
        issues.append("silence_heavy")
        recs.append("Trim pauses so speech occupies most of the reference clip.")

    if abs(dc_offset) > cfg.max_dc_offset:
        score -= 12
        issues.append("dc_offset")
        recs.append("Use a recording without strong DC offset or run a safe high-pass cleanup.")

    if dynamic_range < 4.0 and non_silent.size:
        score -= 10
        issues.append("low_dynamic_separation")
        recs.append("Prefer a cleaner recording with less constant background noise/compression.")

    if channels > 1:
        score -= 3
        issues.append("stereo_reference")
        recs.append("Mono reference is simpler and avoids channel-phase surprises.")

    if sample_rate < 16000:
        score -= 12
        issues.append("low_sample_rate")
        recs.append("Use a reference sampled at 16 kHz or higher when possible.")

    score = int(max(0, min(100, round(score))))
    if score >= 90:
        grade = "EXCELLENT"
    elif score >= 78:
        grade = "GOOD"
    elif score >= 60:
        grade = "REVIEW"
    else:
        grade = "POOR"

    recommended = score >= 78 and not any(
        item in issues for item in ("reference_too_short", "reference_too_long", "clipping")
    )

    return VoiceDoctorReport(
        path=str(path),
        score=score,
        grade=grade,
        recommended=recommended,
        duration_seconds=round(duration, 3),
        sample_rate=int(sample_rate),
        channels=channels,
        peak_dbfs=round(peak_dbfs, 2),
        rms_dbfs=round(rms_dbfs, 2),
        clipping_ratio=round(clipping_ratio, 6),
        silence_ratio=round(silence_ratio, 4),
        dc_offset=round(dc_offset, 6),
        noise_floor_dbfs=round(noise_floor, 2),
        dynamic_range_db=round(dynamic_range, 2),
        issues=tuple(dict.fromkeys(issues)),
        recommendations=tuple(dict.fromkeys(recs)),
    )
