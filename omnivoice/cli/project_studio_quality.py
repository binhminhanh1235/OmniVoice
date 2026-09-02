#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Quality-aware Project Studio controller and Hardware / Quality UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

from omnivoice.cli import project_studio as studio_module
from omnivoice.cli import project_studio_live as live_module
from omnivoice.cli import project_studio_plus as plus_module
from omnivoice.cli.project_studio import ProjectStudioController
from omnivoice.cli.project_studio_resume import SectionResumeProjectStudioController
from omnivoice.cli.section_history_ui import build_section_history_demo
from omnivoice.hardware_quality import (
    QUALITY_PRESETS,
    HardwareCapabilities,
    HardwareQualitySettingsStore,
    detect_hardware,
    normalize_quality_preset,
    quality_policy,
    quality_preset_rows,
)
from omnivoice.project import OmniVoiceProject
from omnivoice.section_history import create_section_snapshot
from omnivoice.section_status import (
    incomplete_section_ids,
    set_section_status,
    write_section_status,
)
from omnivoice.style_bank import StyleBankProjectRunner

_PROJECT_SETTINGS = "studio.json"


class QualityPresetProjectStudioController(SectionResumeProjectStudioController):
    """Section-resume controller with one named quality policy per project."""

    def __init__(self, model: Any, workspace: str | Path) -> None:
        super().__init__(model, workspace)
        self.quality_settings = HardwareQualitySettingsStore(self.workspace)

    def set_workspace(self, workspace: str | Path) -> None:
        super().set_workspace(workspace)
        self.quality_settings = HardwareQualitySettingsStore(self.workspace)

    def workspace_quality_preset(self) -> str:
        return self.quality_settings.load().default_preset

    def set_workspace_quality_preset(self, preset: str) -> str:
        return self.quality_settings.set_default(preset).default_preset

    def _settings_path(self, project: OmniVoiceProject) -> Path:
        return project.root / _PROJECT_SETTINGS

    def _write_project_settings_payload(
        self,
        project: OmniVoiceProject,
        payload: dict[str, Any],
    ) -> None:
        path = self._settings_path(project)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)

    def project_quality_preset(
        self,
        project: OmniVoiceProject | str | Path,
    ) -> tuple[str, str]:
        loaded = project if isinstance(project, OmniVoiceProject) else self.load_project(project)
        settings = self.load_project_settings(loaded)
        explicit = settings.get("quality_preset")
        if explicit:
            return normalize_quality_preset(str(explicit)), "project"
        return self.workspace_quality_preset(), "workspace"

    def set_project_quality_preset(
        self,
        project_path: str | Path,
        preset: Optional[str],
    ) -> tuple[str, str]:
        project = self.load_project(project_path)
        payload = self.load_project_settings(project)
        if preset is None or str(preset).strip().upper() in {"", "INHERIT", "WORKSPACE"}:
            payload.pop("quality_preset", None)
            self._write_project_settings_payload(project, payload)
            return self.workspace_quality_preset(), "workspace"
        normalized = normalize_quality_preset(preset)
        payload["quality_preset"] = normalized
        self._write_project_settings_payload(project, payload)
        return normalized, "project"

    def _resolve_quality_preset(
        self,
        project: OmniVoiceProject,
        requested: Optional[str],
    ) -> str:
        if requested:
            return normalize_quality_preset(requested)
        return self.project_quality_preset(project)[0]

    def generation_config(self, quality_preset: Optional[str] = None):
        return quality_policy(quality_preset or self.workspace_quality_preset()).generation_config()

    def robust_config(
        self,
        *,
        strict: bool = False,
        quality_preset: Optional[str] = None,
    ):
        return quality_policy(quality_preset or self.workspace_quality_preset()).robust_config(
            strict=strict
        )

    def adaptive_quality_config(self, quality_preset: Optional[str] = None):
        return quality_policy(quality_preset or self.workspace_quality_preset()).adaptive_config()

    def _save_generation_settings(
        self,
        project: OmniVoiceProject,
        *,
        voice_name: str,
        voice_variant: str,
        language: Optional[str],
        quality_preset: str,
    ) -> None:
        # Reuse the existing stable Studio settings writer, then add the preset
        # without changing the legacy method signature used by older callers.
        ProjectStudioController.save_project_settings(
            self,
            project,
            voice_name=voice_name,
            voice_variant=voice_variant,
            language=language,
        )
        payload = self.load_project_settings(project)
        payload["quality_preset"] = normalize_quality_preset(quality_preset)
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

        policy = quality_policy(selected_preset)
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
                robust_config=policy.robust_config(strict=strict),
                generation_config=policy.generation_config(),
                section_ids=targets,
                resume=resume,
                language=language or None,
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

    def regenerate_chunk(
        self,
        project_path: str | Path,
        chunk_choice: str,
        *,
        voice_name: str,
        voice_variant: str = "AUTO",
        language: Optional[str] = "en",
        strict: bool = False,
        quality_preset: Optional[str] = None,
    ) -> OmniVoiceProject:
        if not chunk_choice or "/" not in chunk_choice:
            raise ValueError("Select a chunk to regenerate")
        target = chunk_choice.split(" ", 1)[0]
        section_id, chunk_id = target.split("/", 1)

        project = self.load_project(project_path)
        create_section_snapshot(
            project,
            section_id,
            reason=f"before regenerating {chunk_id}",
        )
        set_section_status(
            project,
            section_id,
            "pending",
            save_manifest=False,
        )
        project.mark_chunk_for_regeneration(section_id, chunk_id)
        return self.generate(
            project.root,
            voice_name=voice_name,
            voice_variant=voice_variant,
            language=language,
            section_ids=[section_id],
            resume=True,
            strict=strict,
            quality_preset=quality_preset,
        )


def install_quality_controller() -> None:
    """Inject the quality-aware controller into existing thin Studio builders."""

    studio_module.ProjectStudioController = QualityPresetProjectStudioController
    live_module.ProjectStudioController = QualityPresetProjectStudioController
    plus_module.ProjectStudioController = QualityPresetProjectStudioController


def build_quality_project_demo(model: Any, workspace: str | Path):
    import gradio as gr

    install_quality_controller()
    studio = live_module.build_demo(model, workspace)
    history = build_section_history_demo(
        model,
        workspace,
        controller_cls=QualityPresetProjectStudioController,
    )
    return gr.TabbedInterface(
        [studio, history],
        ["Studio", "Section History"],
        title="OmniVoice Project Studio",
    )


def _hardware_markdown(capabilities: HardwareCapabilities) -> str:
    notes = "\n".join(f"- {item}" for item in capabilities.notes)
    if notes:
        notes = "\n\n" + notes
    return f"**{capabilities.summary()}**{notes}"


def build_hardware_quality_demo(
    model: Any,
    workspace: str | Path,
    *,
    detector=detect_hardware,
):
    import gradio as gr

    controller = QualityPresetProjectStudioController(model, workspace)
    initial_hw = detector()
    initial_default = controller.workspace_quality_preset()
    projects = controller.list_projects()
    initial_project = projects[0] if projects else None
    if initial_project:
        initial_effective, initial_source = controller.project_quality_preset(initial_project)
    else:
        initial_effective, initial_source = initial_default, "workspace"

    def refresh_hardware():
        hw = detector()
        return _hardware_markdown(hw), hw.recommended_preset

    def save_workspace(preset):
        selected = controller.set_workspace_quality_preset(preset)
        return (
            f"Workspace default saved: **{selected}**. Projects without an explicit override inherit it.",
            selected,
        )

    def use_recommended():
        hw = detector()
        selected = controller.set_workspace_quality_preset(hw.recommended_preset)
        return (
            gr.update(value=selected),
            f"Applied hardware recommendation: **{selected}**. Recommended ASR device: `{hw.recommended_asr_device}`.",
        )

    def refresh_projects():
        items = controller.list_projects()
        value = items[0] if items else None
        if value:
            effective, source = controller.project_quality_preset(value)
            message = f"Effective preset: **{effective}** from {source}."
        else:
            effective, source, message = controller.workspace_quality_preset(), "workspace", "No projects yet."
        return (
            gr.update(choices=items, value=value),
            gr.update(value="INHERIT" if source == "workspace" else effective),
            message,
        )

    def show_project(project_path):
        if not project_path:
            return gr.update(value="INHERIT"), "Select a project."
        effective, source = controller.project_quality_preset(project_path)
        value = "INHERIT" if source == "workspace" else effective
        return gr.update(value=value), f"Effective preset: **{effective}** from {source}."

    def save_project(project_path, preset):
        if not project_path:
            raise gr.Error("Select a project first.")
        effective, source = controller.set_project_quality_preset(project_path, preset)
        return f"Project preset saved. Effective preset: **{effective}** from {source}."

    with gr.Blocks(title="Hardware & Quality") as demo:
        gr.Markdown(
            "# Hardware & Quality\n"
            "One quality policy controls decoder effort, retries and verification. "
            "No preset silently disables ASR text verification."
        )
        hardware_summary = gr.Markdown(_hardware_markdown(initial_hw))
        with gr.Row():
            recommended = gr.Textbox(
                label="Hardware recommendation",
                value=initial_hw.recommended_preset,
                interactive=False,
            )
            refresh_hw = gr.Button("Refresh hardware")

        gr.Markdown("## Preset comparison")
        gr.Dataframe(
            headers=[
                "Preset",
                "Diffusion steps",
                "Retries",
                "Split depth",
                "ASR verification",
                "Adaptive retry",
                "Pacing guard",
                "Use",
            ],
            value=quality_preset_rows(),
            interactive=False,
            wrap=True,
        )

        gr.Markdown("## Workspace default")
        with gr.Row():
            workspace_preset = gr.Dropdown(
                label="Default quality preset",
                choices=list(QUALITY_PRESETS),
                value=initial_default,
            )
            save_workspace_button = gr.Button("Save workspace default", variant="primary")
            recommended_button = gr.Button("Use hardware recommendation")
        workspace_status = gr.Markdown(
            f"Current workspace default: **{initial_default}**."
        )

        gr.Markdown(
            "## Optional per-project override\n"
            "Use `INHERIT` for the workspace default. This setting is saved in the project's `studio.json`, "
            "so Project Queue automatically uses it later."
        )
        with gr.Row():
            project = gr.Dropdown(
                label="Project",
                choices=projects,
                value=initial_project,
                scale=3,
            )
            refresh_projects_button = gr.Button("Refresh projects")
        with gr.Row():
            project_preset = gr.Dropdown(
                label="Project quality preset",
                choices=["INHERIT", *QUALITY_PRESETS],
                value="INHERIT" if initial_source == "workspace" else initial_effective,
            )
            save_project_button = gr.Button("Save project override")
        project_status = gr.Markdown(
            f"Effective preset: **{initial_effective}** from {initial_source}."
            if initial_project
            else "No projects yet."
        )

        refresh_hw.click(
            refresh_hardware,
            outputs=[hardware_summary, recommended],
        )
        save_workspace_button.click(
            save_workspace,
            inputs=workspace_preset,
            outputs=[workspace_status, workspace_preset],
        )
        recommended_button.click(
            use_recommended,
            outputs=[workspace_preset, workspace_status],
        )
        refresh_projects_button.click(
            refresh_projects,
            outputs=[project, project_preset, project_status],
        )
        project.change(
            show_project,
            inputs=project,
            outputs=[project_preset, project_status],
        )
        save_project_button.click(
            save_project,
            inputs=[project, project_preset],
            outputs=project_status,
        )

    return demo
