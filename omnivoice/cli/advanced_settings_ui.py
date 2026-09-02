#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Gradio UI for opt-in per-project advanced generation tuning."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from omnivoice.advanced_settings import AdvancedGenerationSettings
from omnivoice.cli.project_studio_advanced import (
    AdvancedSettingsProjectStudioController,
)


def build_advanced_settings_demo(
    model: Any,
    workspace: str | Path,
    *,
    controller_cls=AdvancedSettingsProjectStudioController,
):
    import gradio as gr

    controller = controller_cls(model, workspace)
    projects = controller.list_projects()
    initial_project = projects[0] if projects else None
    initial = (
        controller.project_advanced_settings(initial_project)
        if initial_project
        else AdvancedGenerationSettings()
    )

    def values(settings: AdvancedGenerationSettings):
        return (
            settings.enabled,
            settings.speed,
            settings.num_step,
            settings.guidance_scale,
            settings.position_temperature,
            settings.max_retries,
            settings.max_wer,
            settings.pause_ms,
            settings.paragraph_pause_ms,
        )

    def refresh_projects():
        items = controller.list_projects()
        selected = items[0] if items else None
        settings = (
            controller.project_advanced_settings(selected)
            if selected
            else AdvancedGenerationSettings()
        )
        return (
            gr.update(choices=items, value=selected),
            *values(settings),
            "Loaded project advanced settings." if selected else "No projects yet.",
        )

    def load_project(project_path):
        if not project_path:
            settings = AdvancedGenerationSettings()
            return (*values(settings), "Select a project first.")
        try:
            settings = controller.project_advanced_settings(project_path)
            mode = "CUSTOM" if settings.enabled else "PRESET DEFAULTS"
            return (*values(settings), f"Loaded **{mode}** settings for this project.")
        except Exception as exc:
            raise gr.Error(f"Cannot load advanced settings: {type(exc).__name__}: {exc}")

    def save_settings(
        project_path,
        enabled,
        speed,
        num_step,
        guidance_scale,
        position_temperature,
        max_retries,
        max_wer,
        pause_ms,
        paragraph_pause_ms,
    ):
        if not project_path:
            raise gr.Error("Select a project first.")
        try:
            settings = AdvancedGenerationSettings(
                enabled=bool(enabled),
                speed=float(speed),
                num_step=int(num_step),
                guidance_scale=float(guidance_scale),
                position_temperature=float(position_temperature),
                max_retries=int(max_retries),
                max_wer=float(max_wer),
                pause_ms=int(pause_ms),
                paragraph_pause_ms=int(paragraph_pause_ms),
            )
            controller.set_project_advanced_settings(project_path, settings)
        except Exception as exc:
            raise gr.Error(f"Cannot save advanced settings: {type(exc).__name__}: {exc}")

        if settings.enabled:
            return (
                "✅ **Custom advanced settings enabled.** Future Generate/Resume, targeted regeneration, "
                "and Project Queue runs for this project will use these overrides."
            )
        return (
            "✅ Advanced overrides saved but **disabled**. Quality preset + style defaults remain authoritative."
        )

    def reset_settings(project_path):
        if not project_path:
            raise gr.Error("Select a project first.")
        try:
            settings = controller.reset_project_advanced_settings(project_path)
        except Exception as exc:
            raise gr.Error(f"Cannot reset advanced settings: {type(exc).__name__}: {exc}")
        return (*values(settings), "Reset complete. Project now uses quality preset + style defaults.")

    with gr.Blocks(title="Advanced Settings") as demo:
        gr.Markdown(
            "# Advanced Settings\n"
            "Fine-tune generation for one project without changing the global SAFE/BALANCED/FAST policy. "
            "These overrides are **opt-in** and persist in the project's `studio.json`.\n\n"
            "**Important:** when Custom mode is enabled, the Speed slider becomes a global speed override "
            "for all beats in the project. Voice Style Bank selection still works, but style-specific speed "
            "multipliers are replaced by this value. Disable Custom mode to restore the normal style speeds."
        )

        with gr.Row():
            project = gr.Dropdown(
                label="Project",
                choices=projects,
                value=initial_project,
                scale=4,
            )
            refresh = gr.Button("Refresh projects")

        enabled = gr.Checkbox(
            label="Enable custom advanced overrides",
            value=initial.enabled,
            info="OFF = use Hardware & Quality preset plus normal style-profile speed.",
        )

        with gr.Accordion("Generation controls", open=True):
            speed = gr.Slider(
                minimum=0.50,
                maximum=1.50,
                value=initial.speed,
                step=0.01,
                label="Speed",
                info="1.00 = normal; lower is slower, higher is faster.",
            )
            with gr.Row():
                num_step = gr.Slider(
                    minimum=16,
                    maximum=64,
                    value=initial.num_step,
                    step=1,
                    label="Diffusion steps",
                    info="More steps can improve quality but cost more GPU time.",
                )
                guidance_scale = gr.Slider(
                    minimum=0.5,
                    maximum=5.0,
                    value=initial.guidance_scale,
                    step=0.1,
                    label="Guidance scale",
                )
                position_temperature = gr.Slider(
                    minimum=0.20,
                    maximum=2.00,
                    value=initial.position_temperature,
                    step=0.05,
                    label="Position temperature",
                    info="Lower values are usually more deterministic/stable.",
                )

        with gr.Accordion("Verification & retry", open=False):
            with gr.Row():
                max_retries = gr.Slider(
                    minimum=1,
                    maximum=6,
                    value=initial.max_retries,
                    step=1,
                    label="Max retries per failed chunk",
                )
                max_wer = gr.Slider(
                    minimum=0.01,
                    maximum=0.50,
                    value=initial.max_wer,
                    step=0.01,
                    label="Maximum accepted WER",
                    info="Lower is stricter. Default is 0.18.",
                )

        with gr.Accordion("Pauses", open=False):
            with gr.Row():
                pause_ms = gr.Slider(
                    minimum=0,
                    maximum=2000,
                    value=initial.pause_ms,
                    step=20,
                    label="Chunk pause (ms)",
                )
                paragraph_pause_ms = gr.Slider(
                    minimum=0,
                    maximum=3000,
                    value=initial.paragraph_pause_ms,
                    step=20,
                    label="Paragraph pause (ms)",
                )

        with gr.Row():
            save = gr.Button("Save Advanced Settings", variant="primary")
            reset = gr.Button("Reset to preset defaults")
        status = gr.Markdown(
            "Custom overrides are enabled." if initial.enabled else "Using preset + style defaults."
        )

        setting_outputs = [
            enabled,
            speed,
            num_step,
            guidance_scale,
            position_temperature,
            max_retries,
            max_wer,
            pause_ms,
            paragraph_pause_ms,
        ]

        refresh.click(
            refresh_projects,
            outputs=[project, *setting_outputs, status],
        )
        project.change(
            load_project,
            inputs=project,
            outputs=[*setting_outputs, status],
        )
        save.click(
            save_settings,
            inputs=[project, *setting_outputs],
            outputs=status,
        )
        reset.click(
            reset_settings,
            inputs=project,
            outputs=[*setting_outputs, status],
        )

    return demo
