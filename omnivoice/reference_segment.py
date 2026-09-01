#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Find clean short voice-cloning references inside longer recordings.

The selector is intentionally lightweight. It scans fixed-size windows with the
same signal concepts used by Voice Doctor and ranks candidates without running
another neural model. Only selected candidates are written to disk.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
import soundfile as sf

from omnivoice.voice_doctor import VoiceDoctorConfig, _dbfs, _frame_rms


@dataclass(frozen=True)
class ReferenceSegmentConfig:
    segment_seconds: float = 6.0
    hop_seconds: float = 0.75
    max_candidates: int = 5
    min_source_seconds: float = 3.0
    min_spacing_seconds: float = 2.0
    edge_seconds: float = 0.20

    def __post_init__(self) -> None:
        if not 3.0 <= self.segment_seconds <= 10.0:
            raise ValueError("segment_seconds must be between 3 and 10")
        if self.hop_seconds <= 0:
            raise ValueError("hop_seconds must be > 0")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be >= 1")
        if self.min_spacing_seconds < 0:
            raise ValueError("min_spacing_seconds must be >= 0")
        if self.edge_seconds < 0:
            raise ValueError("edge_seconds must be >= 0")


@dataclass(frozen=True)
class ReferenceSegmentCandidate:
    rank: int
    start_seconds: float
    end_seconds: float
    score: int
    rms_dbfs: float
    peak_dbfs: float
    silence_ratio: float
    clipping_ratio: float
    dynamic_range_db: float
    dc_offset: float
    edge_activity: float
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReferenceSegmentResult:
    source_path: str
    duration_seconds: float
    sample_rate: int
    channels: int
    segment_seconds: float
    candidates: tuple[ReferenceSegmentCandidate, ...]

    @property
    def best(self) -> ReferenceSegmentCandidate:
        if not self.candidates:
            raise ValueError("No reference segment candidates")
        return self.candidates[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "duration_seconds": self.duration_seconds,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "segment_seconds": self.segment_seconds,
            "candidates": [item.to_dict() for item in self.candidates],
        }


def _segment_metrics(
    mono: np.ndarray,
    sample_rate: int,
    doctor: VoiceDoctorConfig,
    selector: ReferenceSegmentConfig,
) -> dict[str, Any]:
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    rms = (
        float(np.sqrt(np.mean(np.square(mono, dtype=np.float64))))
        if mono.size
        else 0.0
    )
    peak_dbfs = _dbfs(peak)
    rms_dbfs = _dbfs(rms)
    clipping_ratio = (
        float(np.mean(np.abs(mono) >= doctor.clipping_threshold))
        if mono.size
        else 0.0
    )
    dc_offset = float(np.mean(mono)) if mono.size else 0.0

    frames = _frame_rms(mono, sample_rate, doctor.frame_ms)
    frame_db = np.asarray([_dbfs(value) for value in frames], dtype=np.float32)
    silence_ratio = (
        float(np.mean(frame_db <= doctor.silence_dbfs)) if frame_db.size else 1.0
    )
    non_silent = frame_db[frame_db > doctor.silence_dbfs]
    if non_silent.size:
        noise_floor = float(np.percentile(non_silent, 15))
        speech_level = float(np.percentile(non_silent, 85))
        dynamic_range = max(0.0, speech_level - noise_floor)
    else:
        dynamic_range = 0.0

    edge_samples = max(1, int(sample_rate * selector.edge_seconds))
    if mono.size:
        left = mono[:edge_samples]
        right = mono[-edge_samples:]
        edge_rms = []
        for edge in (left, right):
            value = float(np.sqrt(np.mean(np.square(edge, dtype=np.float64)))) if edge.size else 0.0
            edge_rms.append(_dbfs(value))
        # 0 means quiet/natural edges, 1 means both edges contain strong speech.
        edge_activity = float(
            np.mean([1.0 if value > doctor.silence_dbfs + 8.0 else 0.0 for value in edge_rms])
        )
    else:
        edge_activity = 0.0

    issues: list[str] = []
    score = 100.0

    if clipping_ratio > doctor.max_clipping_ratio:
        score -= 40.0
        issues.append("clipping")
    elif peak_dbfs > -0.5:
        score -= 8.0
        issues.append("peak_too_hot")

    if rms_dbfs < doctor.ideal_rms_min_dbfs:
        score -= min(28.0, 8.0 + abs(rms_dbfs - doctor.ideal_rms_min_dbfs) * 1.3)
        issues.append("too_quiet")
    elif rms_dbfs > doctor.ideal_rms_max_dbfs:
        score -= min(20.0, 6.0 + abs(rms_dbfs - doctor.ideal_rms_max_dbfs))
        issues.append("too_loud")

    # Short cloning prompts benefit from continuous speech, but a tiny pause at
    # the edges is preferable to cutting through a phoneme.
    if silence_ratio > 0.45:
        score -= 35.0
        issues.append("too_much_silence")
    elif silence_ratio > 0.30:
        score -= 16.0
        issues.append("silence_heavy")
    elif silence_ratio < 0.005:
        score -= 5.0
        issues.append("no_silence")

    if dynamic_range < 4.0 and non_silent.size:
        score -= 16.0
        issues.append("low_dynamic_separation")
    elif dynamic_range >= 8.0:
        score += min(6.0, (dynamic_range - 8.0) * 0.5)

    if abs(dc_offset) > doctor.max_dc_offset:
        score -= 12.0
        issues.append("dc_offset")

    # Penalize windows that look cut through strong speech at both boundaries.
    score -= 5.0 * edge_activity
    if edge_activity >= 1.0:
        issues.append("busy_edges")

    return {
        "score": int(max(0, min(100, round(score)))),
        "rms_dbfs": round(rms_dbfs, 2),
        "peak_dbfs": round(peak_dbfs, 2),
        "silence_ratio": round(silence_ratio, 4),
        "clipping_ratio": round(clipping_ratio, 6),
        "dynamic_range_db": round(dynamic_range, 2),
        "dc_offset": round(dc_offset, 6),
        "edge_activity": round(edge_activity, 3),
        "issues": tuple(dict.fromkeys(issues)),
    }


def find_reference_segments(
    audio_path: str | Path,
    config: Optional[ReferenceSegmentConfig] = None,
    doctor_config: Optional[VoiceDoctorConfig] = None,
) -> ReferenceSegmentResult:
    """Rank non-overlapping clean short windows from a longer recording."""

    cfg = config or ReferenceSegmentConfig()
    doctor = doctor_config or VoiceDoctorConfig()
    path = Path(audio_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(path)

    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    channels = int(audio.shape[1])
    mono = np.mean(audio, axis=1, dtype=np.float32).reshape(-1)
    duration = float(mono.size / max(1, int(sample_rate)))
    if duration < cfg.min_source_seconds:
        raise ValueError(
            f"Source is only {duration:.2f}s. Use Voice Doctor directly for clips under {cfg.min_source_seconds:.1f}s."
        )

    segment_samples = min(mono.size, max(1, int(sample_rate * cfg.segment_seconds)))
    actual_segment_seconds = segment_samples / sample_rate
    hop_samples = max(1, int(sample_rate * cfg.hop_seconds))

    starts: list[int]
    if mono.size <= segment_samples:
        starts = [0]
    else:
        final_start = mono.size - segment_samples
        starts = list(range(0, final_start + 1, hop_samples))
        if starts[-1] != final_start:
            starts.append(final_start)

    raw: list[tuple[int, dict[str, Any]]] = []
    for start in starts:
        window = mono[start : start + segment_samples]
        raw.append((start, _segment_metrics(window, sample_rate, doctor, cfg)))

    raw.sort(
        key=lambda item: (
            -int(item[1]["score"]),
            float(item[1]["clipping_ratio"]),
            abs(float(item[1]["rms_dbfs"]) + 20.0),
            float(item[1]["silence_ratio"]),
            item[0],
        )
    )

    chosen: list[tuple[int, dict[str, Any]]] = []
    min_spacing_samples = int(sample_rate * cfg.min_spacing_seconds)
    for item in raw:
        start = item[0]
        if any(abs(start - selected[0]) < min_spacing_samples for selected in chosen):
            continue
        chosen.append(item)
        if len(chosen) >= cfg.max_candidates:
            break

    candidates: list[ReferenceSegmentCandidate] = []
    for rank, (start, metrics) in enumerate(chosen, start=1):
        start_seconds = start / sample_rate
        candidates.append(
            ReferenceSegmentCandidate(
                rank=rank,
                start_seconds=round(start_seconds, 3),
                end_seconds=round(start_seconds + actual_segment_seconds, 3),
                **metrics,
            )
        )

    return ReferenceSegmentResult(
        source_path=str(path),
        duration_seconds=round(duration, 3),
        sample_rate=int(sample_rate),
        channels=channels,
        segment_seconds=round(actual_segment_seconds, 3),
        candidates=tuple(candidates),
    )


def export_reference_segment(
    result: ReferenceSegmentResult,
    rank: int,
    output_path: str | Path,
) -> Path:
    """Write exactly one ranked candidate from the original multi-channel source."""

    candidate = next((item for item in result.candidates if item.rank == int(rank)), None)
    if candidate is None:
        raise KeyError(f"Unknown candidate rank: {rank}")

    source = Path(result.source_path)
    audio, sample_rate = sf.read(source, dtype="float32", always_2d=True)
    start = max(0, int(round(candidate.start_seconds * sample_rate)))
    end = min(len(audio), int(round(candidate.end_seconds * sample_rate)))
    segment = audio[start:end]
    if segment.size == 0:
        raise RuntimeError("Selected reference segment is empty")

    output = Path(output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    data = segment[:, 0] if segment.shape[1] == 1 else segment
    sf.write(output, data, sample_rate, subtype="PCM_16")
    return output


def save_reference_segment_report(
    result: ReferenceSegmentResult,
    output_path: str | Path,
) -> Path:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
