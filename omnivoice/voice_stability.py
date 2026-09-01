#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Optional real-generation stability test for saved voice prompts.

Voice Doctor measures the input file. Voice Stability Score goes one step
further: it loads a saved Voice Library prompt, synthesizes a small fixed test
set, transcribes each result, and scores text fidelity plus pacing stability.

This first version deliberately does not claim speaker-identity similarity. A
future speaker-embedding layer can add that metric without changing the public
report shape.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Optional, Sequence

import numpy as np
import soundfile as sf

from omnivoice.adaptive_quality import AdaptiveQualityConfig, analyze_pacing
from omnivoice.models.omnivoice import OmniVoiceGenerationConfig
from omnivoice.robust_longform import RobustLongFormConfig, score_transcript
from omnivoice.voice_library import VoiceLibrary


DEFAULT_STABILITY_TEXTS = (
    "The morning is quiet, and the road ahead is clear.",
    "I will not rush the answer; I will speak with patience and care.",
    "Sometimes the smallest choice changes the direction of an entire day.",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class VoiceStabilityConfig:
    test_texts: tuple[str, ...] = DEFAULT_STABILITY_TEXTS
    language: str = "en"
    max_wer: float = 0.18
    min_similarity: float = 0.82
    min_word_ratio: float = 0.74
    max_word_ratio: float = 1.30
    recommended_score: int = 80
    save_audio: bool = True


@dataclass(frozen=True)
class VoiceStabilitySample:
    index: int
    text: str
    transcript: str
    accepted: bool
    wer: float
    similarity: float
    word_ratio: float
    critical_missing: tuple[str, ...]
    extra_repetitions: tuple[str, ...]
    duration_seconds: float
    global_wps: float
    pacing_anomaly: bool
    sample_score: float
    audio_file: Optional[str] = None


@dataclass(frozen=True)
class VoiceStabilityReport:
    voice_name: str
    variant: str
    score: int
    grade: str
    stable: bool
    passed: int
    total: int
    mean_wer: float
    mean_similarity: float
    mean_global_wps: float
    wps_stddev: float
    created_at: str
    samples: tuple[VoiceStabilitySample, ...] = field(default_factory=tuple)
    issues: tuple[str, ...] = field(default_factory=tuple)
    report_file: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _generation_config() -> OmniVoiceGenerationConfig:
    return OmniVoiceGenerationConfig(
        num_step=32,
        guidance_scale=2.0,
        position_temperature=1.0,
        class_temperature=0.0,
        audio_chunk_threshold=1e9,
        pad_duration=0.0,
        fade_duration=0.0,
    )


def _verification_config(config: VoiceStabilityConfig) -> RobustLongFormConfig:
    return RobustLongFormConfig(
        verify_with_asr=True,
        max_wer=config.max_wer,
        min_similarity=config.min_similarity,
        min_word_ratio=config.min_word_ratio,
        max_word_ratio=config.max_word_ratio,
        max_retries=1,
        max_split_depth=0,
    )


def _sample_score(score, pacing_anomaly: bool) -> float:
    # Weighted fidelity score, followed by explicit semantic/repetition/pacing
    # penalties. Keep the score interpretable rather than pretending it is a
    # calibrated perceptual MOS metric.
    ratio_quality = max(0.0, 1.0 - min(1.0, abs(1.0 - score.word_ratio)))
    value = (
        55.0 * max(0.0, 1.0 - min(1.0, score.wer))
        + 35.0 * max(0.0, min(1.0, score.similarity))
        + 10.0 * ratio_quality
    )
    if score.critical_missing:
        value -= 20.0
    if score.extra_repetitions:
        value -= 15.0
    if pacing_anomaly:
        value -= 15.0
    return max(0.0, min(100.0, value))


def _grade(score: int) -> str:
    if score >= 90:
        return "EXCELLENT"
    if score >= 80:
        return "GOOD"
    if score >= 65:
        return "REVIEW"
    return "UNSTABLE"


def evaluate_voice_stability(
    model: Any,
    library: VoiceLibrary,
    *,
    voice_name: str,
    variant: str = "DEFAULT",
    config: VoiceStabilityConfig | None = None,
) -> VoiceStabilityReport:
    """Run three short clone tests and persist a stability report."""

    cfg = config or VoiceStabilityConfig()
    texts: Sequence[str] = tuple(text.strip() for text in cfg.test_texts if text.strip())
    if not texts:
        raise ValueError("Voice Stability Score requires at least one test sentence")

    entry = library.get(voice_name)
    chosen_variant, _ = library.resolve_variant(
        voice_name,
        style="DEFAULT",
        preferred_variant=variant or "DEFAULT",
    )
    prompt = library.load_prompt(voice_name, chosen_variant)

    if getattr(model, "_asr_pipe", None) is None and hasattr(model, "load_asr_model"):
        model.load_asr_model(model_name="openai/whisper-small.en", device="cpu")

    output_dir = library.root / entry.slug / "stability" / chosen_variant.lower()
    output_dir.mkdir(parents=True, exist_ok=True)

    verify_cfg = _verification_config(cfg)
    pacing_cfg = AdaptiveQualityConfig()
    generation_cfg = _generation_config()
    samples: list[VoiceStabilitySample] = []

    for index, text in enumerate(texts, start=1):
        generated = model.generate(
            text=text,
            language=cfg.language,
            voice_clone_prompt=prompt,
            generation_config=generation_cfg,
        )
        audio = np.asarray(generated[0], dtype=np.float32).reshape(-1)
        sample_rate = int(model.sampling_rate)
        duration = len(audio) / max(1, sample_rate)
        transcript = str(model.transcribe((audio, sample_rate))).strip()
        fidelity = score_transcript(text, transcript, verify_cfg)
        pacing = analyze_pacing(text, duration, [], pacing_cfg)
        accepted = fidelity.accepted and not pacing.anomaly
        score_value = _sample_score(fidelity, pacing.anomaly)

        audio_file: Optional[str] = None
        if cfg.save_audio:
            audio_path = output_dir / f"sample-{index:02d}.wav"
            sf.write(audio_path, audio, sample_rate, subtype="PCM_16")
            audio_file = str(audio_path)

        samples.append(
            VoiceStabilitySample(
                index=index,
                text=text,
                transcript=transcript,
                accepted=accepted,
                wer=round(fidelity.wer, 4),
                similarity=round(fidelity.similarity, 4),
                word_ratio=round(fidelity.word_ratio, 4),
                critical_missing=tuple(fidelity.critical_missing),
                extra_repetitions=tuple(fidelity.extra_repetitions),
                duration_seconds=round(duration, 3),
                global_wps=round(pacing.global_wps, 3),
                pacing_anomaly=pacing.anomaly,
                sample_score=round(score_value, 2),
                audio_file=audio_file,
            )
        )

    passed = sum(sample.accepted for sample in samples)
    mean_wer = mean(sample.wer for sample in samples)
    mean_similarity = mean(sample.similarity for sample in samples)
    wps_values = [sample.global_wps for sample in samples if sample.global_wps > 0]
    mean_wps = mean(wps_values) if wps_values else 0.0
    wps_std = pstdev(wps_values) if len(wps_values) > 1 else 0.0

    base_score = mean(sample.sample_score for sample in samples)
    failed_fraction = (len(samples) - passed) / len(samples)
    # Penalize inconsistent delivery across otherwise acceptable samples.
    consistency_penalty = min(10.0, wps_std * 5.0)
    final_score = int(round(max(0.0, min(100.0, base_score - 20.0 * failed_fraction - consistency_penalty))))

    issues: list[str] = []
    if passed < len(samples):
        issues.append(f"{len(samples) - passed} of {len(samples)} clone tests failed fidelity/pacing checks")
    if any(sample.critical_missing for sample in samples):
        issues.append("one or more semantic-critical words were missing")
    if any(sample.extra_repetitions for sample in samples):
        issues.append("one or more clone tests contained extra repeated phrases")
    if any(sample.pacing_anomaly for sample in samples):
        issues.append("one or more clone tests had implausibly fast pacing")
    if wps_std > 0.65:
        issues.append("speaking rate varied substantially across the test set")

    stable = final_score >= cfg.recommended_score and passed == len(samples)
    report_path = output_dir / "stability.json"
    report = VoiceStabilityReport(
        voice_name=entry.name,
        variant=chosen_variant,
        score=final_score,
        grade=_grade(final_score),
        stable=stable,
        passed=passed,
        total=len(samples),
        mean_wer=round(mean_wer, 4),
        mean_similarity=round(mean_similarity, 4),
        mean_global_wps=round(mean_wps, 3),
        wps_stddev=round(wps_std, 3),
        created_at=_utc_now(),
        samples=tuple(samples),
        issues=tuple(issues),
        report_file=str(report_path),
    )
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report
