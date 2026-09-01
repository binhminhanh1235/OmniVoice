#!/usr/bin/env python3
# Copyright    2026  OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Robust long-form generation helpers.

This module intentionally sits on top of :class:`OmniVoice` instead of changing
its base decoding algorithm.  It targets failure modes that become more common
with long narration: skipped words, duplicated phrases, sentence mixing, and
phonemes damaged at chunk boundaries.

The pipeline is:

    clean text -> semantic chunks -> generate -> optional ASR verification
        -> retry failed chunks -> recursively split persistent failures
        -> concatenate with explicit silence

The generator reuses a single ``VoiceClonePrompt`` and disables OmniVoice's
internal long-form splitter for the already-small chunks.  This prevents two
independent chunkers from fighting each other.
"""

from __future__ import annotations

import html
import logging
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from typing import Any, Optional

import numpy as np

from omnivoice.models.omnivoice import OmniVoiceGenerationConfig, VoiceClonePrompt
from omnivoice.utils.text import ABBREVIATIONS

logger = logging.getLogger(__name__)

_DOT_SENTINEL = "\ue000"
_CLOSING_MARKS = "\"'”’)]}》」】"
_CRITICAL_WORDS = {"not", "no", "never", "without"}

_CONTRACTIONS = {
    "can't": "can not",
    "cannot": "can not",
    "won't": "will not",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "weren't": "were not",
    "don't": "do not",
    "doesn't": "does not",
    "didn't": "did not",
    "shouldn't": "should not",
    "wouldn't": "would not",
    "couldn't": "could not",
    "mustn't": "must not",
    "haven't": "have not",
    "hasn't": "has not",
    "hadn't": "had not",
}


@dataclass
class RobustLongFormConfig:
    """Controls semantic chunking and verification.

    ``verify_with_asr`` is opt-in at the model level but enabled here because
    correctness is the purpose of this wrapper.  The ASR model is loaded once
    and may be placed on CPU to preserve GPU memory for OmniVoice.
    """

    max_chunk_words: int = 28
    max_chunk_chars: int = 220
    pause_ms: int = 320
    paragraph_pause_ms: int = 460
    max_retries: int = 3
    max_split_depth: int = 2

    verify_with_asr: bool = True
    asr_model_name: str = "openai/whisper-small.en"
    asr_device: str = "cpu"
    max_wer: float = 0.18
    min_similarity: float = 0.82
    min_word_ratio: float = 0.74
    max_word_ratio: float = 1.30
    repeated_ngram_size: int = 2
    strict: bool = False

    normalize_chunk_rms: bool = True
    min_rms_gain: float = 0.75
    max_rms_gain: float = 1.33

    # Chunk-level fades can attenuate quiet attacks/releases.  PR #259 fixes
    # edge detection; explicit silence between chunks makes fades unnecessary.
    disable_chunk_fades: bool = True
    exact_chunk_edges: bool = True

    def __post_init__(self) -> None:
        if self.max_chunk_words < 4:
            raise ValueError("max_chunk_words must be >= 4")
        if self.max_chunk_chars < 40:
            raise ValueError("max_chunk_chars must be >= 40")
        if self.max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        if self.max_split_depth < 0:
            raise ValueError("max_split_depth must be >= 0")
        if self.pause_ms < 0 or self.paragraph_pause_ms < 0:
            raise ValueError("pause durations must be >= 0")
        if not 0 <= self.max_wer <= 1:
            raise ValueError("max_wer must be between 0 and 1")
        if not 0 <= self.min_similarity <= 1:
            raise ValueError("min_similarity must be between 0 and 1")
        if self.min_word_ratio <= 0 or self.max_word_ratio < self.min_word_ratio:
            raise ValueError("invalid word-ratio limits")


@dataclass(frozen=True)
class TextChunk:
    text: str
    paragraph_end: bool = False


@dataclass
class VerificationScore:
    transcript: str
    wer: float
    similarity: float
    word_ratio: float
    critical_missing: list[str] = field(default_factory=list)
    extra_repetitions: list[str] = field(default_factory=list)
    accepted: bool = False


@dataclass
class ChunkReport:
    text: str
    transcript: str
    attempts: int
    depth: int
    accepted: bool
    wer: float
    similarity: float
    word_ratio: float
    critical_missing: list[str] = field(default_factory=list)
    extra_repetitions: list[str] = field(default_factory=list)


@dataclass
class RobustLongFormResult:
    audio: np.ndarray
    reports: list[ChunkReport]
    chunks: list[str]
    sampling_rate: int

    @property
    def all_verified(self) -> bool:
        return all(report.accepted for report in self.reports)


def clean_tts_text(text: str) -> str:
    """Decode HTML entities and remove layout-only whitespace safely."""

    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    replacements = {
        "\u00a0": " ",
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _protect_non_sentence_periods(text: str) -> str:
    protected = text
    for abbreviation in sorted(ABBREVIATIONS, key=len, reverse=True):
        if abbreviation in protected:
            protected = protected.replace(
                abbreviation, abbreviation.replace(".", _DOT_SENTINEL)
            )
    protected = re.sub(
        r"(?<=\d)\.(?=\d)",
        _DOT_SENTINEL,
        protected,
    )
    return protected


def _split_sentences(paragraph: str) -> list[str]:
    """Split only at hard sentence boundaries, not commas/semicolons."""

    paragraph = re.sub(r"\s+", " ", paragraph.strip())
    if not paragraph:
        return []

    protected = _protect_non_sentence_periods(paragraph)
    closer_class = re.escape(_CLOSING_MARKS)
    pattern = re.compile(
        rf".+?(?:[.!?。！？]+[{closer_class}]*(?=\s|$)|$)",
        flags=re.DOTALL,
    )
    sentences = []
    for match in pattern.finditer(protected):
        sentence = match.group(0).strip().replace(_DOT_SENTINEL, ".")
        if sentence:
            sentences.append(sentence)
    return sentences or [paragraph]


def _within_limits(text: str, max_words: int, max_chars: int) -> bool:
    return len(text.split()) <= max_words and len(text) <= max_chars


def _candidate_cut_positions(text: str, marks: str) -> list[int]:
    return [match.end() for match in re.finditer(f"[{re.escape(marks)}]", text)]


def _choose_cut(text: str, positions: list[int], max_words: int, max_chars: int) -> int:
    if not positions:
        return 0

    valid = []
    for pos in positions:
        left = text[:pos].strip()
        if len(left.split()) >= 4 and _within_limits(left, max_words, max_chars):
            valid.append(pos)
    if valid:
        return max(valid)

    # If every punctuation boundary is slightly over the target, choose the
    # earliest useful one rather than chopping at an arbitrary word.
    for pos in positions:
        if len(text[:pos].split()) >= 4:
            return pos
    return 0


def _fallback_word_cut(text: str, max_words: int, max_chars: int) -> int:
    word_ends = [match.end() for match in re.finditer(r"\S+\s*", text)]
    if not word_ends:
        return 0

    best = 0
    for index, pos in enumerate(word_ends, start=1):
        if index > max_words or pos > max_chars:
            break
        best = pos
    if best:
        return best

    return word_ends[min(max_words, len(word_ends)) - 1]


def _split_overlong(text: str, max_words: int, max_chars: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if _within_limits(text, max_words, max_chars):
        return [text]

    # Prefer clause boundaries. A comma is deliberately the last punctuation
    # option because frequent comma splitting is a common source of unnatural
    # long-form boundaries.
    cut = 0
    for marks in (";:；：", ",，"):
        cut = _choose_cut(
            text,
            _candidate_cut_positions(text, marks),
            max_words,
            max_chars,
        )
        if cut:
            break

    if not cut:
        cut = _fallback_word_cut(text, max_words, max_chars)

    left = text[:cut].strip()
    right = text[cut:].strip()
    if not left or not right or left == text or right == text:
        return [text]

    return _split_overlong(left, max_words, max_chars) + _split_overlong(
        right, max_words, max_chars
    )


def semantic_chunk_text(
    text: str,
    max_words: int = 28,
    max_chars: int = 220,
) -> list[TextChunk]:
    """Create stable chunks while preserving sentence and paragraph meaning.

    Hard sentence boundaries are always preferred.  Semicolons/colons are
    secondary boundaries for genuinely long sentences; commas are a fallback.
    Short rhetorical sentences are intentionally *not* merged together.
    """

    text = clean_tts_text(text)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[TextChunk] = []

    for paragraph_index, paragraph in enumerate(paragraphs):
        sentences = _split_sentences(paragraph)
        paragraph_chunks: list[str] = []
        for sentence in sentences:
            paragraph_chunks.extend(_split_overlong(sentence, max_words, max_chars))

        for index, chunk in enumerate(paragraph_chunks):
            is_last = index == len(paragraph_chunks) - 1
            chunks.append(
                TextChunk(
                    text=chunk,
                    paragraph_end=is_last and paragraph_index < len(paragraphs) - 1,
                )
            )
    return chunks


def _normalize_words(text: str) -> list[str]:
    text = clean_tts_text(text).lower()
    for contraction, expanded in _CONTRACTIONS.items():
        text = text.replace(contraction, expanded)
    text = re.sub(r"[^a-z0-9'\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.split()


def _edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    if not reference:
        return len(hypothesis)
    previous = list(range(len(hypothesis) + 1))
    for i, ref_word in enumerate(reference, start=1):
        current = [i]
        for j, hyp_word in enumerate(hypothesis, start=1):
            substitution = previous[j - 1] + (ref_word != hyp_word)
            insertion = current[j - 1] + 1
            deletion = previous[j] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1]


def _extra_repeated_ngrams(
    reference: list[str], hypothesis: list[str], n: int
) -> list[str]:
    if n <= 0 or len(hypothesis) < n:
        return []

    def ngrams(words: list[str]) -> Counter:
        return Counter(tuple(words[i : i + n]) for i in range(len(words) - n + 1))

    ref_counts = ngrams(reference)
    hyp_counts = ngrams(hypothesis)
    return [
        " ".join(gram)
        for gram, count in hyp_counts.items()
        if count > max(1, ref_counts.get(gram, 0))
    ]


def score_transcript(
    reference: str,
    transcript: str,
    config: RobustLongFormConfig,
) -> VerificationScore:
    """Score ASR output against the text that should have been spoken."""

    ref_words = _normalize_words(reference)
    hyp_words = _normalize_words(transcript)
    if not hyp_words:
        return VerificationScore(
            transcript=transcript,
            wer=1.0,
            similarity=0.0,
            word_ratio=0.0,
            critical_missing=sorted(set(ref_words) & _CRITICAL_WORDS),
            extra_repetitions=["<empty transcript>"],
            accepted=False,
        )

    distance = _edit_distance(ref_words, hyp_words)
    word_error_rate = distance / max(1, len(ref_words))
    similarity = SequenceMatcher(None, ref_words, hyp_words).ratio()
    word_ratio = len(hyp_words) / max(1, len(ref_words))

    ref_counts = Counter(ref_words)
    hyp_counts = Counter(hyp_words)
    critical_missing = sorted(
        word for word in _CRITICAL_WORDS if ref_counts[word] > hyp_counts[word]
    )
    repetitions = _extra_repeated_ngrams(
        ref_words,
        hyp_words,
        config.repeated_ngram_size,
    )

    accepted = (
        word_error_rate <= config.max_wer
        and similarity >= config.min_similarity
        and config.min_word_ratio <= word_ratio <= config.max_word_ratio
        and not critical_missing
        and not repetitions
    )
    return VerificationScore(
        transcript=transcript,
        wer=word_error_rate,
        similarity=similarity,
        word_ratio=word_ratio,
        critical_missing=critical_missing,
        extra_repetitions=repetitions,
        accepted=accepted,
    )


def _score_rank(score: VerificationScore) -> tuple[float, ...]:
    return (
        0.0 if score.accepted else 1.0,
        score.wer,
        -score.similarity,
        abs(1.0 - score.word_ratio),
        float(len(score.extra_repetitions)),
        float(len(score.critical_missing)),
    )


def _active_rms(audio: np.ndarray) -> float:
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not audio.size:
        return 0.0
    peak = float(np.max(np.abs(audio)))
    threshold = max(1e-4, peak * 0.03)
    active = audio[np.abs(audio) >= threshold]
    if not active.size:
        active = audio
    return float(np.sqrt(np.mean(active**2) + 1e-12))


def _split_failed_chunk(text: str) -> list[str]:
    """Split a repeatedly failing chunk near its semantic midpoint."""

    text = text.strip()
    midpoint = len(text) / 2
    for marks in (";:；：", ",，", ".!?。！？"):
        positions = _candidate_cut_positions(text, marks)
        usable = [pos for pos in positions if 4 <= len(text[:pos].split())]
        usable = [pos for pos in usable if 4 <= len(text[pos:].split())]
        if usable:
            cut = min(usable, key=lambda pos: abs(pos - midpoint))
            return [text[:cut].strip(), text[cut:].strip()]

    words = text.split()
    if len(words) < 8:
        return [text]
    cut = len(words) // 2
    return [" ".join(words[:cut]), " ".join(words[cut:])]


class RobustLongFormGenerator:
    """Generate long narration with semantic chunking and ASR quality gates."""

    def __init__(
        self,
        model: Any,
        config: Optional[RobustLongFormConfig] = None,
    ) -> None:
        self.model = model
        self.config = config or RobustLongFormConfig()
        self._reports: list[ChunkReport] = []

    def _ensure_asr(self) -> None:
        if not self.config.verify_with_asr:
            return
        if getattr(self.model, "_asr_pipe", None) is None:
            self.model.load_asr_model(
                model_name=self.config.asr_model_name,
                device=self.config.asr_device,
            )

    def _safe_generation_config(
        self,
        generation_config: Optional[OmniVoiceGenerationConfig],
    ) -> OmniVoiceGenerationConfig:
        config = generation_config or OmniVoiceGenerationConfig()
        changes: dict[str, Any] = {
            # The wrapper already split the text.  Prevent nested automatic
            # chunking so one semantic chunk maps to one verification unit.
            "audio_chunk_threshold": 1e9,
        }
        if self.config.disable_chunk_fades:
            changes["fade_duration"] = 0.0
            changes["pad_duration"] = 0.0
        if self.config.exact_chunk_edges:
            field_names = config.__dataclass_fields__
            if "output_target_lead_silence_ms" in field_names:
                changes["output_target_lead_silence_ms"] = 0
            if "output_target_trail_silence_ms" in field_names:
                changes["output_target_trail_silence_ms"] = 0
        return replace(config, **changes)

    def _generate_candidate(
        self,
        text: str,
        generation_config: OmniVoiceGenerationConfig,
        generate_kwargs: dict[str, Any],
    ) -> np.ndarray:
        audios = self.model.generate(
            text=text,
            generation_config=generation_config,
            **generate_kwargs,
        )
        return np.asarray(audios[0], dtype=np.float32).reshape(-1)

    def _verify(self, text: str, audio: np.ndarray) -> VerificationScore:
        if not self.config.verify_with_asr:
            return VerificationScore(
                transcript="",
                wer=0.0,
                similarity=1.0,
                word_ratio=1.0,
                accepted=True,
            )
        transcript = self.model.transcribe((audio, self.model.sampling_rate))
        return score_transcript(text, transcript, self.config)

    def _generate_verified(
        self,
        text: str,
        generation_config: OmniVoiceGenerationConfig,
        generate_kwargs: dict[str, Any],
        depth: int,
    ) -> list[tuple[str, np.ndarray]]:
        candidates: list[tuple[np.ndarray, VerificationScore, int]] = []

        for attempt in range(1, self.config.max_retries + 1):
            audio = self._generate_candidate(text, generation_config, generate_kwargs)
            score = self._verify(text, audio)
            candidates.append((audio, score, attempt))

            logger.info(
                "Robust chunk depth=%d attempt=%d accepted=%s WER=%.3f similarity=%.3f",
                depth,
                attempt,
                score.accepted,
                score.wer,
                score.similarity,
            )
            if score.accepted:
                self._reports.append(
                    ChunkReport(
                        text=text,
                        transcript=score.transcript,
                        attempts=attempt,
                        depth=depth,
                        accepted=True,
                        wer=score.wer,
                        similarity=score.similarity,
                        word_ratio=score.word_ratio,
                        critical_missing=score.critical_missing,
                        extra_repetitions=score.extra_repetitions,
                    )
                )
                return [(text, audio)]

        candidates.sort(key=lambda item: _score_rank(item[1]))
        best_audio, best_score, best_attempt = candidates[0]

        if depth < self.config.max_split_depth:
            split_parts = _split_failed_chunk(text)
            if len(split_parts) > 1 and all(part != text for part in split_parts):
                logger.warning(
                    "Chunk failed verification after %d attempts; splitting into %d parts",
                    self.config.max_retries,
                    len(split_parts),
                )
                outputs: list[tuple[str, np.ndarray]] = []
                for part in split_parts:
                    outputs.extend(
                        self._generate_verified(
                            part,
                            generation_config,
                            generate_kwargs,
                            depth + 1,
                        )
                    )
                return outputs

        self._reports.append(
            ChunkReport(
                text=text,
                transcript=best_score.transcript,
                attempts=best_attempt,
                depth=depth,
                accepted=False,
                wer=best_score.wer,
                similarity=best_score.similarity,
                word_ratio=best_score.word_ratio,
                critical_missing=best_score.critical_missing,
                extra_repetitions=best_score.extra_repetitions,
            )
        )
        message = (
            "A long-form chunk still failed verification after retries/splitting: "
            f"{text!r}; ASR={best_score.transcript!r}; WER={best_score.wer:.3f}"
        )
        if self.config.strict:
            raise RuntimeError(message)
        logger.warning("%s. Using the best candidate because strict=False.", message)
        return [(text, best_audio)]

    def _stitch(
        self,
        pieces: list[tuple[str, np.ndarray, bool]],
    ) -> np.ndarray:
        if not pieces:
            return np.zeros(0, dtype=np.float32)

        audios = [np.asarray(item[1], dtype=np.float32).reshape(-1) for item in pieces]
        if self.config.normalize_chunk_rms:
            rms_values = [_active_rms(audio) for audio in audios]
            nonzero = [value for value in rms_values if value > 0]
            target = float(np.median(nonzero)) if nonzero else 0.0
            normalized = []
            for audio, current in zip(audios, rms_values):
                if current > 0 and target > 0:
                    gain = np.clip(
                        target / current,
                        self.config.min_rms_gain,
                        self.config.max_rms_gain,
                    )
                    audio = audio * float(gain)
                normalized.append(audio)
            audios = normalized

        output: list[np.ndarray] = []
        sample_rate = int(self.model.sampling_rate)
        for index, ((_, _, paragraph_end), audio) in enumerate(zip(pieces, audios)):
            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
            if peak > 0.999:
                audio = audio * (0.999 / peak)
            output.append(audio)

            if index < len(audios) - 1:
                pause_ms = (
                    self.config.paragraph_pause_ms
                    if paragraph_end
                    else self.config.pause_ms
                )
                output.append(
                    np.zeros(int(sample_rate * pause_ms / 1000), dtype=np.float32)
                )
        return np.concatenate(output).astype(np.float32)

    def generate(
        self,
        text: str,
        generation_config: Optional[OmniVoiceGenerationConfig] = None,
        **generate_kwargs: Any,
    ) -> RobustLongFormResult:
        """Generate one long-form narration.

        ``generate_kwargs`` are forwarded to :meth:`OmniVoice.generate`, e.g.
        ``language``, ``voice_clone_prompt``, ``ref_audio``, ``ref_text``,
        ``instruct``, ``speed`` and ``normalize_text``.

        When ``ref_audio`` is supplied without a reusable ``voice_clone_prompt``,
        the wrapper creates the prompt once and reuses it for all chunks.
        """

        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")

        chunks = semantic_chunk_text(
            text,
            max_words=self.config.max_chunk_words,
            max_chars=self.config.max_chunk_chars,
        )
        if not chunks:
            raise ValueError("text produced no speakable chunks")

        kwargs = dict(generate_kwargs)
        voice_prompt = kwargs.get("voice_clone_prompt")
        ref_audio = kwargs.get("ref_audio")
        if voice_prompt is None and ref_audio is not None:
            ref_text = kwargs.pop("ref_text", None)
            kwargs.pop("ref_audio", None)
            preprocess_prompt = (
                generation_config.preprocess_prompt
                if generation_config is not None
                else True
            )
            voice_prompt = self.model.create_voice_clone_prompt(
                ref_audio=ref_audio,
                ref_text=ref_text,
                preprocess_prompt=preprocess_prompt,
            )
            kwargs["voice_clone_prompt"] = voice_prompt

        self._ensure_asr()
        safe_config = self._safe_generation_config(generation_config)
        self._reports = []

        stitched_pieces: list[tuple[str, np.ndarray, bool]] = []
        for chunk in chunks:
            verified_pieces = self._generate_verified(
                chunk.text,
                safe_config,
                kwargs,
                depth=0,
            )
            for piece_index, (piece_text, piece_audio) in enumerate(verified_pieces):
                stitched_pieces.append(
                    (
                        piece_text,
                        piece_audio,
                        chunk.paragraph_end and piece_index == len(verified_pieces) - 1,
                    )
                )

        audio = self._stitch(stitched_pieces)
        return RobustLongFormResult(
            audio=audio,
            reports=list(self._reports),
            chunks=[item[0] for item in stitched_pieces],
            sampling_rate=int(self.model.sampling_rate),
        )


def generate_robust_longform(
    model: Any,
    text: str,
    robust_config: Optional[RobustLongFormConfig] = None,
    generation_config: Optional[OmniVoiceGenerationConfig] = None,
    **generate_kwargs: Any,
) -> RobustLongFormResult:
    """Convenience function around :class:`RobustLongFormGenerator`."""

    return RobustLongFormGenerator(model, robust_config).generate(
        text,
        generation_config=generation_config,
        **generate_kwargs,
    )
