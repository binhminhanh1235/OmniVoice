#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0

"""Controller used by the consolidated Project Workspace UI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from omnivoice.cli.project_studio_advanced import AdvancedSettingsProjectStudioController
from omnivoice.project import OmniVoiceProject


_GENERATION_SETTING_KEYS = {
    "voice_name",
    "voice_variant",
    "language",
    "quality_preset",
}


class UnifiedWorkspaceController(AdvancedSettingsProjectStudioController):
    """Keep project-shaping metadata stable across later render settings saves.

    Legacy generation settings historically replaced ``studio.json``. The
    unified UI stores project-shaping choices such as ``speak_section_titles``
    there too, so generation must preserve non-generation keys.
    """

    def _merge_project_metadata(
        self,
        project: OmniVoiceProject,
        **updates,
    ) -> None:
        payload = self.load_project_settings(project)
        payload.update(updates)
        self._write_project_settings_payload(project, payload)

    def create_project(
        self,
        script: str,
        *,
        speak_section_titles: bool = False,
        overwrite: bool = False,
    ) -> OmniVoiceProject:
        project = super().create_project(
            script,
            speak_section_titles=speak_section_titles,
            overwrite=overwrite,
        )
        self._merge_project_metadata(
            project,
            speak_section_titles=bool(speak_section_titles),
        )
        return project

    def _save_generation_settings(
        self,
        project: OmniVoiceProject,
        *,
        voice_name: str,
        voice_variant: str,
        language: Optional[str],
        quality_preset: str,
    ) -> None:
        before = self.load_project_settings(project)
        preserved = {
            key: value
            for key, value in before.items()
            if key not in _GENERATION_SETTING_KEYS
        }
        super()._save_generation_settings(
            project,
            voice_name=voice_name,
            voice_variant=voice_variant,
            language=language,
            quality_preset=quality_preset,
        )
        if preserved:
            payload = self.load_project_settings(project)
            payload.update(preserved)
            self._write_project_settings_payload(project, payload)
