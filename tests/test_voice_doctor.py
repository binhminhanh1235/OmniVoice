import numpy as np
import soundfile as sf

from omnivoice.voice_doctor import analyze_voice_reference


def _write(path, audio, sr=24000):
    sf.write(path, np.asarray(audio, dtype=np.float32), sr)
    return path


def _tone(seconds=6.0, sr=24000, amp=0.18):
    t = np.arange(int(seconds * sr), dtype=np.float32) / sr
    carrier = amp * np.sin(2 * np.pi * 180 * t)
    # Speech-like amplitude movement so dynamic-range heuristics are not flat.
    envelope = 0.55 + 0.45 * np.sin(2 * np.pi * 1.7 * t) ** 2
    return (carrier * envelope).astype(np.float32)


def test_clean_six_second_reference_scores_good(tmp_path):
    audio = _tone()
    # Add short natural edge silence.
    audio[:2400] = 0
    audio[-2400:] = 0
    path = _write(tmp_path / "clean.wav", audio)

    report = analyze_voice_reference(path)

    assert report.duration_seconds == 6.0
    assert report.sample_rate == 24000
    assert report.channels == 1
    assert report.score >= 78
    assert report.recommended is True
    assert "reference_too_short" not in report.issues
    assert "clipping" not in report.issues


def test_too_short_reference_is_rejected(tmp_path):
    path = _write(tmp_path / "short.wav", _tone(seconds=1.0))

    report = analyze_voice_reference(path)

    assert report.recommended is False
    assert "reference_too_short" in report.issues
    assert any("3–10" in item for item in report.recommendations)


def test_clipped_reference_is_rejected(tmp_path):
    audio = _tone(6.0, amp=1.4)
    audio = np.clip(audio, -1.0, 1.0)
    path = _write(tmp_path / "clipped.wav", audio)

    report = analyze_voice_reference(path)

    assert report.recommended is False
    assert report.clipping_ratio > 0
    assert "clipping" in report.issues


def test_silence_heavy_reference_gets_warning(tmp_path):
    sr = 24000
    audio = np.zeros(sr * 6, dtype=np.float32)
    audio[sr * 2 : sr * 4] = _tone(seconds=2.0, sr=sr)
    path = _write(tmp_path / "silence.wav", audio, sr)

    report = analyze_voice_reference(path)

    assert report.silence_ratio > 0.5
    assert "too_much_silence" in report.issues


def test_low_sample_rate_is_flagged(tmp_path):
    path = _write(tmp_path / "low_sr.wav", _tone(seconds=6.0, sr=8000), sr=8000)

    report = analyze_voice_reference(path)

    assert report.sample_rate == 8000
    assert "low_sample_rate" in report.issues
