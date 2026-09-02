#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Advanced-settings aware Project Studio controller."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from omnivoice.advanced_settings import (
    ADVANCED_SETTINGS_KEY,
    AdvancedGenerationSettings,
)
from omnivoice.cli.project_studio import ProjectStudioController
from omnivoice.cli.project_studio_pause import (
    PauseAwareQualityPresetProjectStudioController,
)
from omnivoice.hardware_quality import normalize_quality_preset, quality_policy
from omnivoice.project import OmniVoiceProject
from omnivoice.section_history import create_section_snapshot
from omnivoice.section_status import (
    incomplete_section_ids,
    set_section_status,
    write_section_status,
)
from omnivoice.style_bank import StyleBankProjectRunner


class AdvancedSettingsProjectStudioController(
    PauseAwareQualityPresetProjectStudioController
):
    """Keep quality presets as defaults while allowing per-project overrides."""

    def project_advanced_settings(
        self,
        project: OmniVoiceProject | str | Path,
    ) -> AdvancedGenerationSettings:
        loaded = project if isinstance(project, OmniVoiceProject) else self.load_project(project)
        payload = self.load_project_settings(loaded)
        return AdvancedGenerationSettings.from_dict(payload.get(ADVANCED_SETTINGS_KEY))

    def set_project_advanced_settings(
        self,
        project_path: str | Path,
        settings: AdvancedGenerationSettings,
    ) -> AdvancedGenerationSettings:
        settings.validate()
        project = self.load_project(project_path)
        payload = self.load_project_settings(project)
        payload[ADVANCED_SETTINGS_KEY] = settings.to_dict()
        self._write_project_settings_payload(project, payload)
        return settings

    def reset_project_advanced_settings(
        self,
        project_path: str | Path,
    ) -> AdvancedGenerationSettings:
        project = self.load_project(project_path)
        payload = self.load_project_settings(project)
        payload.pop(ADVANCED_SETTINGS_KEY, None)
        self._write_project_settings_payload(project, payload)
        return AdvancedGenerationSettings()

    def _save_generation_settings(
        self,
        project: OmniVoiceProject,
        *,
        voice_name: str,
        voice_variant: str,
        language: Optional[str],
        quality_preset: str,
    ) -> None:
        # The legacy writer replaces studio.json. Preserve advanced settings
        # across Generate/Resume calls instead of silently resetting the UI.
        existing = self.load_project_settings(project)
        advanced = existing.get(ADVANCED_SETTINGS_KEY)
        super()._save_generation_settings(
            project,
            voice_name=voice_name,
            voice_variant=voice_variant,
            language=language,
            quality_preset=quality_preset,
        )
        if advanced is not None:
            payload = self.load_project_settings(project)
            payload[ADVANCED_SETTINGS_KEY] = advanced
            self._write_project_settings_payload(project, payload)

    def generate(
        self,
        project_path: str | Path,
        *,
        voice_name: str,
        voice_variant: str = "AUTO",
        language: Optional[str] = "en",
        section_ids: Optional[Iterable[str]] = None,
        resume: bool = True,
        strict: bool = False,
        quality_preset: Optional[str] = None,
    ) -> OmniVoiceProject:
        self._wait_for_resume(project_path)
        if not voice_name:
            raise ValueError("Select a saved voice before generation")

        project = self.load_project(project_path)
        requested = (
            [item.upper() for item in section_ids]
            if section_ids is not None
            else [section.id for section in project.manifest.sections]
        )
        targets = incomplete_section_ids(project, requested) if resume else requested
        selected_preset = self._resolve_quality_preset(project, quality_preset)
        selected_variant = (voice_variant or "AUTO").upper()
        advanced = self.project_advanced_settings(project)

        self._save_generation_settings(
            project,
            voice_name=voice_name,
            voice_variant=selected_variant,
            language=language,
            quality_preset=selected_preset,
        )

        if not resume:
            for section_id in targets:
                create_section_snapshot(
                    project,
                    section_id,
                    reason="before forced section regeneration",
                )

        if not targets:
            write_section_status(project)
            return project

        for section_id in targets:
            set_section_status(
                project,
                section_id,
                "queued",
                save_manifest=False,
            )
        project.save()

        policy = quality_policy(normalize_quality_preset(selected_preset))
        generation_config = advanced.apply_generation_config(policy.generation_config())
        robust_config = advanced.apply_robust_config(
            policy.robust_config(strict=strict)
        )
        runner = StyleBankProjectRunner(
            self.model,
            self.voices,
            voice_name=voice_name,
            preferred_variant=selected_variant,
            quality_config=policy.adaptive_config(),
        )

        try:
            runner.generate(
                project,
                robust_config=robust_config,
                generation_config=generation_config,
                section_ids=targets,
                resume=resume,
                language=language or None,
                **advanced.generation_kwargs(),
            )
        except Exception:
            try:
                failed = ProjectStudioController.load_project(self, project.root)
                write_section_status(failed)
            except Exception:
                pass
            raise

        write_section_status(project)
        return project
