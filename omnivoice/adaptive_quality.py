#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Adaptive quality layer for robust long-form generation.

This module stays outside the OmniVoice decoder. It extends the existing
``RobustLongFormGenerator`` with two production-oriented safeguards:

* **Adaptive retry**: classify why a candidate failed and change the next
  generation attempt instead of repeating identical settings.
* **Pacing guard**: reject audio that is globally implausibly fast or contains
  a local speech-rate spike relative to the rest of the same chunk.

The implementation deliberately degrades gracefully. If Whisper word
timestamps are unavailable, text verification still works and the pacing guard
falls back to a global words-per-second check derived from the WAV duration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any, Optional

import numpy as np

from omnivoice.models.omnivoice import OmniVoiceGenerationConfig
from omnivoice.robust_longform import (
    ChunkReport,
    RobustLongFormConfig,
    RobustLongFormGenerator,
    VerificationScore,
    _normalize_words,
    _score_rank,
    _split_failed_chunk,
    score_transcript,
)

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveQualityConfig:
    """Controls retry adaptation and pacing rejection."""

    adaptive_retry: bool = True
    pacing_guard: bool = True

    # Pacing thresholds are intentionally conservative. Normal narration is
    # often around 2-3 words/s; values above these limits are usually obvious
    # speed-up artifacts rather than a stylistic choice.
    min_words_for_pacing: int = 7
    max_global_wps: float = 4.6
    max_local_wps: float = 5.5
    max_local_speed_ratio: float = 1.70
    pacing_window_words: int = 5

    # Retry adaptation.
    retry_position_temperature_factor: float = 0.70
    retry_position_temperature_floor: float = 0.50
    retry_position_temperature_cap: float = 1.50
    retry_speed_factor: float = 0.94
    retry_min_speed: float = 0.78
    retry_num_step_increment: int = 8
    retry_max_num_step: int = 48

    # If the same severe failure persists twice, splitting is generally more
    # useful than burning the remaining retries on an unstable long sequence.
    early_split_after: int = 2

    def __post_init__(self) -> None:
        if self.min_words_for_pacing < 1:
            raise ValueError("min_words_for_pacing must be >= 1")
        if self.max_global_wps <= 0 or self.max_local_wps <= 0:
            raise ValueError("pacing limits must be > 0")
        if self.max_local_speed_ratio <= 1:
            raise ValueError("max_local_speed_ratio must be > 1")
        if self.pacing_window_words < 2:
            raise ValueError("pacing_window_words must be >= 2")
        if not 0 < self.retry_position_temperature_factor <= 1:
            raise ValueError("retry_position_temperature_factor must be in (0, 1]")
        if self.retry_speed_factor <= 0 or self.retry_speed_factor > 1:
            raise ValueError("retry_speed_factor must be in (0, 1]")
        if self.early_split_after < 1:
            raise ValueError("early_split_after must be >= 1")


@dataclass
class PacingMetrics:
    global_wps: float = 0.0
    median_local_wps: float = 0.0
    max_local_wps: float = 0.0
    local_speed_ratio: float = 0.0
    anomaly: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass
class AdaptiveChunkReport(ChunkReport):
    failure_reasons: list[str] = field(default_factory=list)
    recovered_from: list[str] = field(default_factory=list)
    retry_actions: list[str] = field(default_factory=list)
    global_wps: float = 0.0
    median_local_wps: float = 0.0
    max_local_wps: float = 0.0
    local_speed_ratio: float = 0.0
    pacing_anomaly: bool = False


@dataclass
class _Candidate:
    audio: np.ndarray
    score: VerificationScore
    pacing: PacingMetrics
    attempt: int
    reasons: list[str]
    retry_actions: list[str]

    @property
    def accepted(self) -> bool:
        return self.score.accepted and not self.pacing.anomaly


def analyze_pacing(
    reference_text: str,
    audio_duration_seconds: float,
    word_timings: list[tuple[float, float, int]],
    config: AdaptiveQualityConfig,
) -> PacingMetrics:
    """Measure global and local speaking rate for a generated chunk.

    ``word_timings`` entries are ``(start_seconds, end_seconds, word_count)``.
    Word-level Whisper timestamps naturally use ``word_count=1``; the count
    field also supports ASR implementations that return short phrase chunks.
    """

    words = _normalize_words(reference_text)
    if len(words) < config.min_words_for_pacing or audio_duration_seconds <= 0:
        return PacingMetrics()

    global_wps = len(words) / max(audio_duration_seconds, 1e-6)
    local_rates: list[float] = []

    usable = [
        (float(start), float(end), max(1, int(count)))
        for start, end, count in word_timings
        if end is not None and start is not None and float(end) > float(start)
    ]

    for start_index in range(len(usable)):
        words_in_window = 0
        start = usable[start_index][0]
        end = start
        for end_index in range(start_index, len(usable)):
            item_start, item_end, count = usable[end_index]
            if item_start < start:
                continue
            words_in_window += count
            end = max(end, item_end)
            if words_in_window >= config.pacing_window_words:
                span = end - start
                if span > 0:
                    local_rates.append(words_in_window / span)
                break

    median_local = float(np.median(local_rates)) if local_rates else 0.0
    max_local = max(local_rates) if local_rates else 0.0
    ratio = (
        max_local / median_local
        if median_local > 0 and max_local > 0
        else 0.0
    )

    reasons: list[str] = []
    if global_wps > config.max_global_wps:
        reasons.append("global_speed")
    if (
        max_local > config.max_local_wps
        and ratio > config.max_local_speed_ratio
    ):
        reasons.append("local_speed_spike")

    return PacingMetrics(
        global_wps=global_wps,
        median_local_wps=median_local,
        max_local_wps=max_local,
        local_speed_ratio=ratio,
        anomaly=bool(reasons),
        reasons=reasons,
    )


class AdaptiveRobustLongFormGenerator(RobustLongFormGenerator):
    """Robust generator that adapts retries to the observed failure mode."""

    def __init__(
        self,
        model: Any,
        config: Optional[RobustLongFormConfig] = None,
        quality_config: Optional[AdaptiveQualityConfig] = None,
    ) -> None:
        super().__init__(model, config)
        self.quality_config = quality_config or AdaptiveQualityConfig()

    def _transcribe_with_timings(
        self,
        audio: np.ndarray,
    ) -> tuple[str, list[tuple[float, float, int]]]:
        """Transcribe once and request Whisper word timestamps when possible."""

        if not self.config.verify_with_asr:
            return "", []

        pipe = getattr(self.model, "_asr_pipe", None)
        if self.quality_config.pacing_guard and callable(pipe):
            try:
                result = pipe(
                    {
                        "array": np.asarray(audio, dtype=np.float32).reshape(-1),
                        "sampling_rate": int(self.model.sampling_rate),
                    },
                    return_timestamps="word",
                )
                transcript = str(result.get("text", "")).strip()
                timings: list[tuple[float, float, int]] = []
                for item in result.get("chunks", []) or []:
                    timestamp = item.get("timestamp")
                    if not timestamp or len(timestamp) != 2:
                        continue
                    start, end = timestamp
                    if start is None or end is None:
                        continue
                    count = max(1, len(_normalize_words(str(item.get("text", "")))))
                    timings.append((float(start), float(end), count))
                return transcript, timings
            except Exception:
                logger.debug(
                    "ASR word timestamps unavailable; falling back to plain transcription",
                    exc_info=True,
                )

        return (
            self.model.transcribe((audio, self.model.sampling_rate)),
            [],
        )

    def _verify_adaptive(
        self,
        text: str,
        audio: np.ndarray,
    ) -> tuple[VerificationScore, PacingMetrics, list[str]]:
        if self.config.verify_with_asr:
            transcript, timings = self._transcribe_with_timings(audio)
            score = score_transcript(text, transcript, self.config)
        else:
            transcript, timings = "", []
            score = VerificationScore(
                transcript="",
                wer=0.0,
                similarity=1.0,
                word_ratio=1.0,
                accepted=True,
            )

        duration = len(audio) / max(1, int(self.model.sampling_rate))
        pacing = (
            analyze_pacing(text, duration, timings, self.quality_config)
            if self.quality_config.pacing_guard
            else PacingMetrics()
        )

        reasons = self._failure_reasons(score, pacing)
        if pacing.anomaly and score.accepted:
            score = replace(score, accepted=False)
        return score, pacing, reasons

    def _failure_reasons(
        self,
        score: VerificationScore,
        pacing: PacingMetrics,
    ) -> list[str]:
        reasons: list[str] = []
        if score.critical_missing:
            reasons.append("critical_missing")
        if score.word_ratio < self.config.min_word_ratio:
            reasons.append("omission")
        if score.extra_repetitions:
            reasons.append("repetition")
        if pacing.anomaly:
            reasons.append("pacing")
        if (
            not score.accepted
            and not score.critical_missing
            and not score.extra_repetitions
            and score.word_ratio >= self.config.min_word_ratio
        ):
            reasons.append("asr_mismatch")
        return list(dict.fromkeys(reasons))

    def _adapt_next_attempt(
        self,
        generation_config: OmniVoiceGenerationConfig,
        generate_kwargs: dict[str, Any],
        reasons: list[str],
    ) -> tuple[OmniVoiceGenerationConfig, dict[str, Any], list[str]]:
        if not self.quality_config.adaptive_retry or not reasons:
            return generation_config, dict(generate_kwargs), []

        qc = self.quality_config
        config = generation_config
        kwargs = dict(generate_kwargs)
        changes: dict[str, Any] = {}
        actions: list[str] = []

        def lower_position_temperature(multiplier: float = 1.0) -> None:
            current = float(config.position_temperature)
            capped = min(current, qc.retry_position_temperature_cap)
            updated = max(
                qc.retry_position_temperature_floor,
                capped * qc.retry_position_temperature_factor * multiplier,
            )
            if abs(updated - current) > 1e-9:
                changes["position_temperature"] = updated
                actions.append(f"position_temperature->{updated:.2f}")

        if "repetition" in reasons:
            lower_position_temperature()
            if config.class_temperature != 0.0:
                changes["class_temperature"] = 0.0
                actions.append("class_temperature->0")

        if "critical_missing" in reasons or "omission" in reasons:
            updated_steps = min(
                qc.retry_max_num_step,
                int(config.num_step) + qc.retry_num_step_increment,
            )
            if updated_steps != config.num_step:
                changes["num_step"] = updated_steps
                actions.append(f"num_step->{updated_steps}")
            lower_position_temperature(multiplier=1.10)

        if "pacing" in reasons:
            if "duration" not in kwargs:
                current_speed = float(kwargs.get("speed", 1.0))
                updated_speed = max(
                    qc.retry_min_speed,
                    current_speed * qc.retry_speed_factor,
                )
                kwargs["speed"] = updated_speed
                actions.append(f"speed->{updated_speed:.3f}")
            lower_position_temperature(multiplier=0.95)

        if "asr_mismatch" in reasons and not changes:
            lower_position_temperature(multiplier=1.15)

        if changes:
            config = replace(config, **changes)
        return config, kwargs, list(dict.fromkeys(actions))

    def _should_split_early(
        self,
        reason_history: list[list[str]],
    ) -> bool:
        if len(reason_history) < self.quality_config.early_split_after:
            return False
        severe = {"critical_missing", "omission", "repetition", "pacing"}
        recent = reason_history[-self.quality_config.early_split_after :]
        common = severe.copy()
        for item in recent:
            common &= set(item)
        return bool(common)

    def _report(
        self,
        *,
        text: str,
        score: VerificationScore,
        pacing: PacingMetrics,
        attempts: int,
        depth: int,
        accepted: bool,
        failure_reasons: list[str],
        recovered_from: list[str],
        retry_actions: list[str],
    ) -> AdaptiveChunkReport:
        return AdaptiveChunkReport(
            text=text,
            transcript=score.transcript,
            attempts=attempts,
            depth=depth,
            accepted=accepted,
            wer=score.wer,
            similarity=score.similarity,
            word_ratio=score.word_ratio,
            critical_missing=score.critical_missing,
            extra_repetitions=score.extra_repetitions,
            failure_reasons=failure_reasons,
            recovered_from=recovered_from,
            retry_actions=retry_actions,
            global_wps=pacing.global_wps,
            median_local_wps=pacing.median_local_wps,
            max_local_wps=pacing.max_local_wps,
            local_speed_ratio=pacing.local_speed_ratio,
            pacing_anomaly=pacing.anomaly,
        )

    def _candidate_rank(self, item: _Candidate) -> tuple[float, ...]:
        return (
            0.0 if item.accepted else 1.0,
            1.0 if item.pacing.anomaly else 0.0,
            *_score_rank(item.score)[1:],
            item.pacing.max_local_wps,
        )

    def _generate_verified(
        self,
        text: str,
        generation_config: OmniVoiceGenerationConfig,
        generate_kwargs: dict[str, Any],
        depth: int,
    ) -> list[tuple[str, np.ndarray]]:
        candidates: list[_Candidate] = []
        reason_history: list[list[str]] = []
        action_history: list[str] = []
        recovered_from: list[str] = []

        attempt_config = generation_config
        attempt_kwargs = dict(generate_kwargs)

        for attempt in range(1, self.config.max_retries + 1):
            audio = self._generate_candidate(text, attempt_config, attempt_kwargs)
            score, pacing, reasons = self._verify_adaptive(text, audio)
            reason_history.append(reasons)
            recovered_from.extend(reasons)

            candidate = _Candidate(
                audio=audio,
                score=score,
                pacing=pacing,
                attempt=attempt,
                reasons=reasons,
                retry_actions=list(action_history),
            )
            candidates.append(candidate)

            logger.info(
                "Adaptive chunk depth=%d attempt=%d accepted=%s WER=%.3f "
                "global_wps=%.2f max_local_wps=%.2f reasons=%s",
                depth,
                attempt,
                candidate.accepted,
                score.wer,
                pacing.global_wps,
                pacing.max_local_wps,
                reasons,
            )

            if candidate.accepted:
                self._reports.append(
                    self._report(
                        text=text,
                        score=score,
                        pacing=pacing,
                        attempts=attempt,
                        depth=depth,
                        accepted=True,
                        failure_reasons=[],
                        recovered_from=list(dict.fromkeys(recovered_from[:-len(reasons) if reasons else None])),
                        retry_actions=list(action_history),
                    )
                )
                return [(text, audio)]

            if (
                depth < self.config.max_split_depth
                and self._should_split_early(reason_history)
            ):
                logger.warning(
                    "Persistent %s failure after %d attempts; splitting early",
                    reasons,
                    attempt,
                )
                break

            if attempt < self.config.max_retries:
                attempt_config, attempt_kwargs, actions = self._adapt_next_attempt(
                    attempt_config,
                    attempt_kwargs,
                    reasons,
                )
                action_history.extend(actions)

        candidates.sort(key=self._candidate_rank)
        best = candidates[0]

        if depth < self.config.max_split_depth:
            split_parts = _split_failed_chunk(text)
            if len(split_parts) > 1 and all(part != text for part in split_parts):
                logger.warning(
                    "Adaptive verification failed; splitting chunk into %d parts",
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
            self._report(
                text=text,
                score=best.score,
                pacing=best.pacing,
                attempts=best.attempt,
                depth=depth,
                accepted=False,
                failure_reasons=best.reasons,
                recovered_from=list(dict.fromkeys(recovered_from)),
                retry_actions=best.retry_actions,
            )
        )
        message = (
            "A long-form chunk still failed adaptive verification: "
            f"{text!r}; reasons={best.reasons}; ASR={best.score.transcript!r}; "
            f"WER={best.score.wer:.3f}; global_wps={best.pacing.global_wps:.2f}; "
            f"max_local_wps={best.pacing.max_local_wps:.2f}"
        )
        if self.config.strict:
            raise RuntimeError(message)
        logger.warning("%s. Using the best candidate because strict=False.", message)
        return [(text, best.audio)]
