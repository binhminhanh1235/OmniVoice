#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Style-aware project generation using Voice Library variants.

This runner preserves the existing Project persistence/checkpoint logic while
selecting a reusable voice prompt per beat. Generic style tags such as WARM or
SOFT therefore affect the reference style when a matching variant exists, with
safe fallback to DEFAULT when it does not.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, Iterable, Optional

import soundfile as sf

from omnivoice.adaptive_quality import (
    AdaptiveQualityConfig,
    AdaptiveRobustLongFormGenerator,
)
from omnivoice.models.omnivoice import OmniVoiceGenerationConfig
from omnivoice.project import (
    OmniVoiceProject,
    OmniVoiceStyleResolver,
    StyleProfile,
    _utc_now,
    _write_json,
)
from omnivoice.robust_longform import RobustLongFormConfig
from omnivoice.voice_library import VoiceLibrary, VoicePromptResolution


class StyleBankProjectRunner:
    """Generate a project with one Voice Library variant selected per beat."""

    def __init__(
        self,
        model: Any,
        voice_library: VoiceLibrary,
        *,
        voice_name: str,
        preferred_variant: str = "AUTO",
        style_profiles: Optional[dict[str, StyleProfile]] = None,
        quality_config: Optional[AdaptiveQualityConfig] = None,
    ) -> None:
        self.model = model
        self.voice_library = voice_library
        self.voice_name = voice_name
        self.preferred_variant = preferred_variant
        self.style_resolver = OmniVoiceStyleResolver(style_profiles)
        self.quality_config = quality_config or AdaptiveQualityConfig()
        self._resolution_cache: dict[str, VoicePromptResolution] = {}

    def resolve_voice(self, style: str) -> VoicePromptResolution:
        variant, used_fallback = self.voice_library.resolve_variant(
            self.voice_name,
            style=style,
            preferred_variant=self.preferred_variant,
        )
        cache_key = variant
        cached = self._resolution_cache.get(cache_key)
        if cached is not None:
            return VoicePromptResolution(
                prompt=cached.prompt,
                voice_name=cached.voice_name,
                requested_style=style.upper(),
                variant=variant,
                used_fallback=used_fallback,
            )
        resolution = self.voice_library.resolve_prompt(
            self.voice_name,
            style=style,
            preferred_variant=self.preferred_variant,
        )
        self._resolution_cache[cache_key] = resolution
        return resolution

    def generate(
        self,
        project: OmniVoiceProject,
        *,
        robust_config: Optional[RobustLongFormConfig] = None,
        generation_config: Optional[OmniVoiceGenerationConfig] = None,
        section_ids: Optional[Iterable[str]] = None,
        resume: bool = True,
        **generate_kwargs: Any,
    ):
        sample_rate = int(self.model.sampling_rate)
        base_robust = robust_config or RobustLongFormConfig(
            max_chunk_words=project.manifest.max_chunk_words,
            max_chunk_chars=project.manifest.max_chunk_chars,
        )
        base_generation = generation_config or OmniVoiceGenerationConfig()

        # `verify_with_asr=False` is an explicit request to bypass quality
        # verification. Keep that contract intact by disabling the pacing guard
        # too; otherwise tiny synthetic/test audio can trigger unrelated retries.
        effective_quality = (
            self.quality_config
            if base_robust.verify_with_asr
            else replace(self.quality_config, pacing_guard=False)
        )

        selected = None
        if section_ids is not None:
            selected = {item.upper() for item in section_ids}

        for section in project.manifest.sections:
            if selected is not None and section.id not in selected:
                continue

            for beat in section.beats:
                profile = self.style_resolver.resolve(beat.style)
                resolution = self.resolve_voice(beat.style)
                style_robust = replace(
                    base_robust,
                    pause_ms=max(
                        0,
                        int(base_robust.pause_ms * profile.pause_multiplier),
                    ),
                    paragraph_pause_ms=max(
                        0,
                        int(
                            base_robust.paragraph_pause_ms
                            * profile.pause_multiplier
                        ),
                    ),
                )

                for chunk in beat.chunks:
                    audio_path, report_path = project._chunk_paths(section, chunk)
                    if (
                        resume
                        and chunk.status == "verified"
                        and audio_path.exists()
                    ):
                        chunk.audio_file = str(audio_path.relative_to(project.root))
                        chunk.report_file = str(report_path.relative_to(project.root))
                        continue

                    kwargs = dict(generate_kwargs)
                    kwargs["voice_clone_prompt"] = resolution.prompt

                    if "duration" not in kwargs and "speed" not in kwargs:
                        kwargs["speed"] = profile.speed

                    # A native instruct is used only when OmniVoice documents it.
                    # Generic WARM/SOFT/EMPHASIZE styles remain reference metadata.
                    if profile.native_instruct and "instruct" not in kwargs:
                        kwargs["instruct"] = profile.native_instruct

                    generator = AdaptiveRobustLongFormGenerator(
                        self.model,
                        style_robust,
                        effective_quality,
                    )
                    result = generator.generate(
                        chunk.text,
                        generation_config=base_generation,
                        **kwargs,
                    )

                    audio_path.parent.mkdir(parents=True, exist_ok=True)
                    sf.write(
                        audio_path,
                        result.audio,
                        result.sampling_rate,
                        subtype="PCM_16",
                    )
                    report_payload = {
                        "section": section.id,
                        "beat": beat.id,
                        "chunk": chunk.id,
                        "style": chunk.style,
                        "voice_name": resolution.voice_name,
                        "voice_variant": resolution.variant,
                        "voice_variant_fallback": resolution.used_fallback,
                        "all_verified": result.all_verified,
                        "source_text": chunk.text,
                        "generated_chunks": result.chunks,
                        "quality_guard": "adaptive_retry+pacing",
                        "reports": [asdict(report) for report in result.reports],
                    }
                    _write_json(report_path, report_payload)

                    chunk.audio_file = str(audio_path.relative_to(project.root))
                    chunk.report_file = str(report_path.relative_to(project.root))
                    chunk.status = (
                        "verified" if result.all_verified else "unverified"
                    )
                    chunk.updated_at = _utc_now()
                    project.save()

                project._assemble_beat(section, beat, sample_rate, profile)
                project.save()

            project._assemble_section(section, sample_rate, self.style_resolver)
            project.save()

        return project.manifest


def generate_project_with_style_bank(
    project: OmniVoiceProject,
    model: Any,
    voice_library: VoiceLibrary,
    *,
    voice_name: str,
    preferred_variant: str = "AUTO",
    robust_config: Optional[RobustLongFormConfig] = None,
    generation_config: Optional[OmniVoiceGenerationConfig] = None,
    style_profiles: Optional[dict[str, StyleProfile]] = None,
    quality_config: Optional[AdaptiveQualityConfig] = None,
    section_ids: Optional[Iterable[str]] = None,
    resume: bool = True,
    **generate_kwargs: Any,
):
    runner = StyleBankProjectRunner(
        model,
        voice_library,
        voice_name=voice_name,
        preferred_variant=preferred_variant,
        style_profiles=style_profiles,
        quality_config=quality_config,
    )
    return runner.generate(
        project,
        robust_config=robust_config,
        generation_config=generation_config,
        section_ids=section_ids,
        resume=resume,
        **generate_kwargs,
    )