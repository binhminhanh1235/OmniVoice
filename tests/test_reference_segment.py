from pathlib import Path

import numpy as np
import soundfile as sf

from omnivoice.reference_segment import (
    ReferenceSegmentConfig,
    export_reference_segment,
    find_reference_segments,
)


def _long_reference(path: Path) -> Path:
    sr = 24000
    seconds = 18
    audio = np.zeros(sr * seconds, dtype=np.float32)

    # 0-6s: mostly silence / very weak signal.
    t = np.arange(sr * 6, dtype=np.float32) / sr
    audio[: sr * 6] = 0.001 * np.sin(2 * np.pi * 120 * t)

    # 6-12s: clean speech-like modulated carrier with tiny quiet edges.
    clean = 0.16 * np.sin(2 * np.pi * 185 * t)
    envelope = 0.45 + 0.55 * np.sin(2 * np.pi * 2.1 * t) ** 2
    clean = (clean * envelope).astype(np.float32)
    clean[: int(sr * 0.12)] = 0
    clean[-int(sr * 0.12) :] = 0
    audio[sr * 6 : sr * 12] = clean

    # 12-18s: intentionally clipped/hot.
    dirty = 1.2 * np.sin(2 * np.pi * 200 * t)
    audio[sr * 12 :] = np.clip(dirty, -1.0, 1.0)

    sf.write(path, audio, sr, subtype="FLOAT")
    return path


def test_finder_prefers_clean_middle_region(tmp_path: Path):
    source = _long_reference(tmp_path / "long.wav")
    result = find_reference_segments(
        source,
        ReferenceSegmentConfig(
            segment_seconds=6.0,
            hop_seconds=0.5,
            max_candidates=4,
            min_spacing_seconds=2.0,
        ),
    )

    assert result.duration_seconds == 18.0
    assert len(result.candidates) == 4
    best = result.best
    assert 5.0 <= best.start_seconds <= 7.0
    assert best.clipping_ratio == 0.0
    assert best.score >= 70
    assert "clipping" not in best.issues


def test_export_writes_selected_candidate_with_expected_duration(tmp_path: Path):
    source = _long_reference(tmp_path / "long.wav")
    result = find_reference_segments(
        source,
        ReferenceSegmentConfig(segment_seconds=6.0, hop_seconds=1.0, max_candidates=3),
    )
    output = export_reference_segment(result, result.best.rank, tmp_path / "best.wav")

    audio, sr = sf.read(output, dtype="float32")
    assert sr == 24000
    assert abs(len(audio) / sr - 6.0) < 0.02
    assert output.exists()


def test_short_source_is_ranked_as_one_candidate_when_at_least_three_seconds(tmp_path: Path):
    sr = 24000
    path = tmp_path / "short.wav"
    t = np.arange(sr * 4, dtype=np.float32) / sr
    sf.write(path, 0.1 * np.sin(2 * np.pi * 180 * t), sr)

    result = find_reference_segments(path)
    assert len(result.candidates) == 1
    assert result.best.start_seconds == 0.0
    assert 3.9 <= result.best.end_seconds <= 4.01
