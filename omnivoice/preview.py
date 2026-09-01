#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Non-destructive preview generation for Project Studio.

Preview-before-render generates a few representative samples from an existing
project without changing section/chunk status, checkpoint files, or selected
final audio. This lets users approve voice/style choices before spending GPU
on a full long-form render.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Optional

import soundfile as sf

from omnivoice.adaptive_quality import AdaptiveRobustLongFormGenerator
from omnivoice.models.omnivoice import OmniVoiceGenerationConfig
from omnivoice.project import (
    OmniVoiceProject,
    OmniVoiceStyleResolver,
    ProjectBeat,
    ProjectChunk,
    ProjectSection,
)
from omnivoice.robust_longform import RobustLongFormConfig
from omnivoice.style_bank import StyleBankProjectRunner
from omnivoice.voice_library import VoiceLibrary


@dataclass(frozen=True)
class PreviewTarget:
    label: str
    section_id: str
    beat_id: str
    chunk_id: str
    style: str
    text: str


@dataclass(frozen=True)
class PreviewResult:
    target: PreviewTarget
    audio_file: str
    report_file: str
    voice_name: str
    voice_variant: str
    voice_variant_fallback: bool
    verified: bool


def _flatten_targets(project: OmniVoiceProject):
    items: list[tuple[ProjectSection, ProjectBeat, ProjectChunk]] = []
    for section in project.manifest.sections:
        for beat in section.beats:
            for chunk in beat.chunks:
                items.append((section, beat, chunk))
    return items


def select_preview_targets(project: OmniVoiceProject) -> list[PreviewTarget]:
    """Pick opening/middle/ending chunks while avoiding duplicate samples."""

    items = _flatten_targets(project)
    if not items:
        return []

    requested = [
        ("opening", 0),
        ("middle", len(items) // 2),
        ("ending", len(items) - 1),
    ]
    seen: set[int] = set()
    targets: list[PreviewTarget] = []
    for label, index in requested:
        if index in seen:
            continue
        seen.add(index)
        section, beat, chunk = items[index]
        targets.append(
            PreviewTarget(
                label=label,
                section_id=section.id,
                beat_id=beat.id,
                chunk_id=chunk.id,
                style=beat.style,
                text=chunk.text,
            )
        )
    return targets


class ProjectPreviewGenerator:
    """Generate representative samples without mutating project state."""

    def __init__(
        self,
        model: Any,
        voice_library: VoiceLibrary,
        *,
        voice_name: str,
        preferred_variant: str = "AUTO",
    ) -> None:
        self.model = model
        self.voice_library = voice_library
        self.voice_name = voice_name
        self.preferred_variant = preferred_variant
        self.style_bank = StyleBankProjectRunner(
            model,
            voice_library,
            voice_name=voice_name,
            preferred_variant=preferred_variant,
        )
        self.style_resolver = OmniVoiceStyleResolver()

    def generate(
        self,
        project: OmniVoiceProject,
        *,
        robust_config: Optional[RobustLongFormConfig] = None,
        generation_config: Optional[OmniVoiceGenerationConfig] = None,
        labels: Optional[Iterable[str]] = None,
        language: Optional[str] = "en",
        strict: bool = False,
    ) -> list[PreviewResult]:
        base_robust = robust_config or RobustLongFormConfig(
            max_chunk_words=project.manifest.max_chunk_words,
            max_chunk_chars=project.manifest.max_chunk_chars,
            verify_with_asr=True,
            max_retries=2,
            max_split_depth=1,
            strict=strict,
        )
        base_generation = generation_config or OmniVoiceGenerationConfig(
            num_step=32,
            guidance_scale=2.0,
            position_temperature=1.0,
            class_temperature=0.0,
            audio_chunk_threshold=1e9,
            pad_duration=0.0,
            fade_duration=0.0,
        )

        # Preview honors the same explicit verification switch as project render.
        # Synthetic/unit-test previews with verify_with_asr=False must not be
        # rejected by a separate pacing-only gate.
        effective_quality = (
            self.style_bank.quality_config
            if base_robust.verify_with_asr
            else replace(self.style_bank.quality_config, pacing_guard=False)
        )

        allowed = {item.lower() for item in labels} if labels is not None else None
        targets = [
            target
            for target in select_preview_targets(project)
            if allowed is None or target.label in allowed
        ]

        output_dir = project.root / "previews"
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[PreviewResult] = []

        for target in targets:
            profile = self.style_resolver.resolve(target.style)
            resolution = self.style_bank.resolve_voice(target.style)
            style_robust = replace(
                base_robust,
                pause_ms=max(0, int(base_robust.pause_ms * profile.pause_multiplier)),
                paragraph_pause_ms=max(
                    0,
                    int(base_robust.paragraph_pause_ms * profile.pause_multiplier),
                ),
                strict=strict,
            )

            kwargs: dict[str, Any] = {
                "voice_clone_prompt": resolution.prompt,
                "speed": profile.speed,
            }
            if language:
                kwargs["language"] = language
            if profile.native_instruct:
                kwargs["instruct"] = profile.native_instruct

            generated = AdaptiveRobustLongFormGenerator(
                self.model,
                style_robust,
                effective_quality,
            ).generate(
                target.text,
                generation_config=base_generation,
                **kwargs,
            )

            stem = f"{target.label}_{target.section_id}_{target.chunk_id}"
            audio_path = output_dir / f"{stem}.wav"
            report_path = output_dir / f"{stem}.json"
            sf.write(audio_path, generated.audio, generated.sampling_rate, subtype="PCM_16")

            payload = {
                "preview": asdict(target),
                "voice_name": resolution.voice_name,
                "voice_variant": resolution.variant,
                "voice_variant_fallback": resolution.used_fallback,
                "all_verified": generated.all_verified,
                "quality_guard": "adaptive_retry+pacing",
                "reports": [asdict(report) for report in generated.reports],
            }
            report_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            results.append(
                PreviewResult(
                    target=target,
                    audio_file=str(audio_path),
                    report_file=str(report_path),
                    voice_name=resolution.voice_name,
                    voice_variant=resolution.variant,
                    voice_variant_fallback=resolution.used_fallback,
                    verified=generated.all_verified,
                )
            )

        return results


def generate_project_previews(
    project: OmniVoiceProject,
    model: Any,
    voice_library: VoiceLibrary,
    *,
    voice_name: str,
    preferred_variant: str = "AUTO",
    **kwargs: Any,
) -> list[PreviewResult]:
    return ProjectPreviewGenerator(
        model,
        voice_library,
        voice_name=voice_name,
        preferred_variant=preferred_variant,
    ).generate(project, **kwargs)