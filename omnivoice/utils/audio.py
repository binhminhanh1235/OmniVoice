#!/usr/bin/env python3
# Copyright    2026  Xiaomi Corp.        (authors:  Han Zhu)
#
# See ../../LICENSE for clarification regarding multiple authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Audio I/O and processing utilities.

Provides functions for loading, resampling, silence removal,
chunking, cross-fading, and format conversion.

All public functions in this module operate on **numpy float32 arrays**
with shape ``(C, T)`` (channels-first).
"""

import io
import logging
import math
from numbers import Integral, Real

import numpy as np
import soundfile as sf
import torch
import torchaudio
from pydub import AudioSegment
from pydub.silence import detect_leading_silence, detect_nonsilent

logger = logging.getLogger(__name__)


def _validate_nonnegative_integer(name: str, value: int) -> int:
    """Return *value* as an int or raise a clear validation error."""
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")
    return int(value)


def _validate_optional_nonnegative_integer(
    name: str,
    value: int | None,
) -> int | None:
    """Validate an optional non-negative integer without coercion."""
    if value is None:
        return None
    return _validate_nonnegative_integer(name, value)


def _validate_nonnegative_real(name: str, value: float) -> float:
    """Return *value* as a finite float or raise a clear validation error."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a finite non-negative number")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return value


def _validate_optional_peak_limit(name: str, value: float | None) -> float | None:
    """Return a peak limit in ``(0, 1]`` or preserve ``None``."""
    if value is None:
        return None
    value = _validate_nonnegative_real(name, value)
    if value <= 0 or value > 1:
        raise ValueError(f"{name} must be greater than zero and at most one")
    return value


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_waveform(audio_path: str):
    """Load audio from a file path, returning (data, sample_rate).

    Tries two backends in order:
    1. soundfile — covers WAV/FLAC/OGG etc., no ffmpeg needed.
    2. librosa — covers MP3/M4A etc. via audioread + ffmpeg.

    Returns:
        (data, sample_rate) where data is a numpy float32 array of
        shape (C, T).
    """
    try:
        data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
        return data.T, sr  # (T, C) → (C, T)
    except Exception:
        # soundfile cannot handle MP3/M4A etc., fall back to librosa.
        import librosa

        data, sr = librosa.load(audio_path, sr=None, mono=False)
        if data.ndim == 1:
            data = data[np.newaxis, :]
        return data, sr


def load_audio(audio_path: str, sampling_rate: int) -> np.ndarray:
    """Load a waveform from file and resample to the target rate.

    Parameters:
        audio_path: path of the audio.
        sampling_rate: target sampling rate.

    Returns:
        Numpy float32 array of shape (1, T).
    """
    data, sr = load_waveform(audio_path)

    if data.shape[0] > 1:
        data = np.mean(data, axis=0, keepdims=True)
    if sr != sampling_rate:
        data = torchaudio.functional.resample(
            torch.from_numpy(data), orig_freq=sr, new_freq=sampling_rate
        ).numpy()

    return data


def load_audio_bytes(raw: bytes, sampling_rate: int) -> np.ndarray:
    """Load audio from in-memory bytes and resample.

    Parameters:
        raw: raw audio file bytes (e.g. from WebDataset).
        sampling_rate: target sampling rate.

    Returns:
        Numpy float32 array of shape (1, T).
    """
    buf = io.BytesIO(raw)

    try:
        data, sr = sf.read(buf, dtype="float32", always_2d=True)
        data = data.T  # (T, C) → (C, T)
    except Exception:
        import librosa

        buf.seek(0)
        data, sr = librosa.load(buf, sr=None, mono=False)
        if data.ndim == 1:
            data = data[np.newaxis, :]

    if data.shape[0] > 1:
        data = np.mean(data, axis=0, keepdims=True)
    if sr != sampling_rate:
        data = torchaudio.functional.resample(
            torch.from_numpy(data), orig_freq=sr, new_freq=sampling_rate
        ).numpy()

    return data


# ---------------------------------------------------------------------------
# Audio processing (all numpy in / numpy out)
# ---------------------------------------------------------------------------


def numpy_to_audiosegment(audio: np.ndarray, sample_rate: int) -> AudioSegment:
    """Convert a numpy float32 array of shape (C, T) to a pydub AudioSegment."""
    audio_int = (audio * 32768.0).clip(-32768, 32767).astype(np.int16)
    if audio_int.shape[0] > 1:
        audio_int = audio_int.T.flatten()  # interleave channels
    return AudioSegment(
        data=audio_int.tobytes(),
        sample_width=2,
        frame_rate=sample_rate,
        channels=audio.shape[0],
    )


def audiosegment_to_numpy(aseg: AudioSegment) -> np.ndarray:
    """Convert a pydub AudioSegment to a numpy float32 array of shape (C, T)."""
    data = np.array(aseg.get_array_of_samples()).astype(np.float32) / 32768.0
    if aseg.channels == 1:
        return data[np.newaxis, :]
    return data.reshape(-1, aseg.channels).T


def remove_silence(
    audio: np.ndarray,
    sampling_rate: int,
    mid_sil: int = 300,
    lead_sil: int = 100,
    trail_sil: int = 300,
    keep_mid_sil: int | None = None,
) -> np.ndarray:
    """Shorten long middle silences and trim edge silences.

    Parameters:
        audio: numpy array with shape (C, T).
        sampling_rate: sampling rate of the audio.
        mid_sil: minimum middle-silence duration in ms (0 to skip).
        lead_sil: kept leading silence in ms.
        trail_sil: kept trailing silence in ms.
        keep_mid_sil: maximum total duration kept from each detected middle
            silence, in ms. ``None`` keeps at most ``mid_sil`` ms.

    Returns:
        Numpy array with shape (C, T').
    """
    mid_sil = _validate_nonnegative_integer("mid_sil", mid_sil)
    lead_sil = _validate_nonnegative_integer("lead_sil", lead_sil)
    trail_sil = _validate_nonnegative_integer("trail_sil", trail_sil)
    if keep_mid_sil is None:
        keep_mid_sil = mid_sil
    else:
        keep_mid_sil = _validate_nonnegative_integer("keep_mid_sil", keep_mid_sil)

    if audio.ndim != 2:
        raise ValueError("audio must have shape (channels, samples)")
    if audio.shape[-1] == 0:
        return audio

    # Pydub is used only to detect millisecond ranges. Reconstructing the
    # returned waveform from AudioSegment would quantize float input to PCM16
    # and hard-clip samples outside [-1, 1]. Slice the original float array
    # instead so silence post-processing never changes voiced samples.
    processed = audio
    detection_proxy = numpy_to_audiosegment(processed, sampling_rate)

    if mid_sil > 0:
        keep_per_side = keep_mid_sil // 2
        output_ranges = [
            [start - keep_per_side, end + keep_per_side]
            for start, end in detect_nonsilent(
                detection_proxy,
                min_silence_len=mid_sil,
                silence_thresh=-50,
                seek_step=10,
            )
        ]
        for current, following in zip(output_ranges, output_ranges[1:]):
            if following[0] < current[1]:
                midpoint = (current[1] + following[0]) // 2
                current[1] = midpoint
                following[0] = midpoint

        sample_ranges = [
            (
                max(0, int(start * sampling_rate / 1000.0)),
                min(processed.shape[-1], int(end * sampling_rate / 1000.0)),
            )
            for start, end in output_ranges
        ]
        chunks = [
            processed[..., start:end] for start, end in sample_ranges if end > start
        ]
        processed = np.concatenate(chunks, axis=-1) if chunks else processed[..., :0]

    if processed.shape[-1] == 0:
        return processed

    edge_proxy = numpy_to_audiosegment(processed, sampling_rate)
    leading_silence = detect_leading_silence(
        edge_proxy,
        silence_threshold=-50,
    )
    trailing_silence = detect_leading_silence(
        edge_proxy.reverse(),
        silence_threshold=-50,
    )
    start_ms = max(0, leading_silence - lead_sil)
    end_ms = min(len(edge_proxy), len(edge_proxy) - trailing_silence + trail_sil)
    start_sample = max(0, int(start_ms * sampling_rate / 1000.0))
    end_sample = min(processed.shape[-1], int(end_ms * sampling_rate / 1000.0))
    return processed[..., start_sample:end_sample]


def limit_audio_peak(
    audio: np.ndarray,
    peak_limit: float | None,
) -> np.ndarray:
    """Scale a waveform only when its absolute peak exceeds *peak_limit*.

    This operation preserves duration and relative dynamics. ``None`` keeps
    the waveform unchanged.
    """
    peak_limit = _validate_optional_peak_limit("peak_limit", peak_limit)
    if peak_limit is None or audio.size == 0:
        return audio
    peak = float(np.max(np.abs(audio)))
    if peak <= peak_limit or peak <= 1e-12:
        return audio
    return audio * (peak_limit / peak)


def match_edge_silence(
    audio: np.ndarray,
    sampling_rate: int,
    target_lead_silence_ms: int | None = None,
    target_trail_silence_ms: int | None = None,
) -> np.ndarray:
    """Match either output edge to an exact amount of digital silence.

    ``None`` preserves the corresponding edge exactly as received. A numeric
    target removes zero-valued PCM16 proxy samples on that edge and replaces
    them with the requested number of zero-valued samples. This sample-accurate
    rule avoids millisecond detector rounding and preserves PCM-representable
    low-level attacks, including audio below a conventional dBFS silence
    threshold. Voiced samples are always sliced from the original
    floating-point waveform.

    The target values describe alignment supplied by the caller; this function
    does not infer timing from reference audio. Callers that must fit a fixed
    window should subtract intentional edge silence from the pre-synthesis
    audio-token budget.

    Parameters:
        audio: numpy array with shape (C, T).
        sampling_rate: sampling rate of the audio.
        target_lead_silence_ms: exact final leading silence in milliseconds, or
            ``None`` to keep the existing leading edge.
        target_trail_silence_ms: exact final trailing silence in milliseconds,
            or ``None`` to keep the existing trailing edge.

    Returns:
        Numpy array with shape (C, T').
    """
    target_lead_silence_ms = _validate_optional_nonnegative_integer(
        "target_lead_silence_ms", target_lead_silence_ms
    )
    target_trail_silence_ms = _validate_optional_nonnegative_integer(
        "target_trail_silence_ms", target_trail_silence_ms
    )

    if audio.ndim != 2:
        raise ValueError("audio must have shape (channels, samples)")
    if audio.shape[-1] == 0:
        return audio
    if target_lead_silence_ms is None and target_trail_silence_ms is None:
        return audio

    # Inspect a PCM16 proxy sample by sample. The returned core still comes
    # from the original float array, so quantization is used only to decide
    # which edge samples are digital silence. This deliberately preserves any
    # PCM-representable low-level phoneme instead of applying a dBFS threshold.
    detection_proxy = (audio * 32768.0).clip(-32768, 32767).astype(np.int16)
    active_samples = np.any(detection_proxy != 0, axis=0)
    active_indices = np.flatnonzero(active_samples)

    # A silent model output is not turned into an apparently valid timing pad.
    if active_indices.size == 0:
        return audio[..., :0]

    start_sample = 0
    if target_lead_silence_ms is not None:
        start_sample = int(active_indices[0])
    end_sample = audio.shape[-1]
    if target_trail_silence_ms is not None:
        end_sample = max(start_sample, int(active_indices[-1]) + 1)

    parts: list[np.ndarray] = []
    if target_lead_silence_ms is not None:
        lead_samples = round(target_lead_silence_ms * sampling_rate / 1000.0)
        if lead_samples:
            parts.append(np.zeros((audio.shape[0], lead_samples), dtype=audio.dtype))

    parts.append(audio[..., start_sample:end_sample])

    if target_trail_silence_ms is not None:
        trail_samples = round(target_trail_silence_ms * sampling_rate / 1000.0)
        if trail_samples:
            parts.append(np.zeros((audio.shape[0], trail_samples), dtype=audio.dtype))

    return np.concatenate(parts, axis=-1)


def remove_silence_edges(
    audio: AudioSegment,
    lead_sil: int = 100,
    trail_sil: int = 300,
    silence_threshold: float = -50,
) -> AudioSegment:
    """Remove edge silences, keeping *lead_sil* / *trail_sil* ms."""
    start_idx = detect_leading_silence(audio, silence_threshold=silence_threshold)
    start_idx = max(0, start_idx - lead_sil)
    audio = audio[start_idx:]

    audio = audio.reverse()
    start_idx = detect_leading_silence(audio, silence_threshold=silence_threshold)
    start_idx = max(0, start_idx - trail_sil)
    audio = audio[start_idx:]
    audio = audio.reverse()

    return audio


def fade_and_pad_audio(
    audio: np.ndarray,
    pad_duration: float = 0.1,
    fade_duration: float = 0.1,
    sample_rate: int = 24000,
) -> np.ndarray:
    """Apply fade-in/out and pad with silence to prevent clicks.

    Args:
        audio: numpy array of shape (C, T).
        pad_duration: silence padding duration per side (seconds).
        fade_duration: fade curve duration (seconds).
        sample_rate: audio sampling rate.

    Returns:
        Processed numpy array of shape (C, T_new).
    """
    pad_duration = _validate_nonnegative_real("pad_duration", pad_duration)
    fade_duration = _validate_nonnegative_real("fade_duration", fade_duration)

    if audio.shape[-1] == 0:
        return audio

    fade_samples = int(fade_duration * sample_rate)
    pad_samples = int(pad_duration * sample_rate)

    processed = audio.copy()

    if fade_samples > 0:
        k = min(fade_samples, processed.shape[-1] // 2)
        if k > 0:
            fade_in = np.linspace(0, 1, k, dtype=np.float32)[np.newaxis, :]
            processed[..., :k] *= fade_in

            fade_out = np.linspace(1, 0, k, dtype=np.float32)[np.newaxis, :]
            processed[..., -k:] *= fade_out

    if pad_samples > 0:
        silence = np.zeros(
            (processed.shape[0], pad_samples),
            dtype=processed.dtype,
        )
        processed = np.concatenate([silence, processed, silence], axis=-1)

    return processed


def trim_long_audio(
    audio: np.ndarray,
    sampling_rate: int,
    max_duration: float = 15.0,
    min_duration: float = 3.0,
    trim_threshold: float = 20.0,
) -> np.ndarray:
    """Trim audio to <= *max_duration* by splitting at the largest silence gap.

    Only trims when the audio exceeds *trim_threshold* seconds.

    Args:
        audio: numpy array of shape (C, T).
        sampling_rate: audio sampling rate.
        max_duration: maximum duration in seconds.
        min_duration: minimum duration in seconds.
        trim_threshold: only trim if audio is longer than this (seconds).

    Returns:
        Trimmed numpy array.
    """
    duration = audio.shape[-1] / sampling_rate
    if duration <= trim_threshold:
        return audio

    seg = numpy_to_audiosegment(audio, sampling_rate)
    nonsilent = detect_nonsilent(
        seg, min_silence_len=100, silence_thresh=-40, seek_step=10
    )
    if not nonsilent:
        return audio

    max_ms = int(max_duration * 1000)
    min_ms = int(min_duration * 1000)

    best_split = 0
    for start, end in nonsilent:
        if start > best_split and start <= max_ms:
            best_split = start
        if end > max_ms:
            break

    if best_split < min_ms:
        best_split = min(max_ms, len(seg))

    trimmed = seg[:best_split]
    return audiosegment_to_numpy(trimmed)


def cross_fade_chunks(
    chunks: list[np.ndarray],
    sample_rate: int,
    silence_duration: float = 0.3,
) -> np.ndarray:
    """Concatenate audio chunks with silence gaps and cross-fade at boundaries.

    Args:
        chunks: list of numpy arrays, each (C, T).
        sample_rate: audio sample rate.
        silence_duration: total silence gap duration in seconds.

    Returns:
        Merged numpy array (C, T_total).
    """
    if len(chunks) == 1:
        return chunks[0]

    total_n = int(silence_duration * sample_rate)
    fade_n = total_n // 3
    silence_n = fade_n
    merged = chunks[0].copy()

    for chunk in chunks[1:]:
        parts = [merged]

        fout_n = min(fade_n, merged.shape[-1])
        if fout_n > 0:
            w_out = np.linspace(1, 0, fout_n, dtype=np.float32)[np.newaxis, :]
            parts[-1][..., -fout_n:] *= w_out

        parts.append(np.zeros((chunks[0].shape[0], silence_n), dtype=np.float32))

        fade_in = chunk.copy()
        fin_n = min(fade_n, fade_in.shape[-1])
        if fin_n > 0:
            w_in = np.linspace(0, 1, fin_n, dtype=np.float32)[np.newaxis, :]
            fade_in[..., :fin_n] *= w_in

        parts.append(fade_in)
        merged = np.concatenate(parts, axis=-1)

    return merged
