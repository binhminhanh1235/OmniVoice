#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Gradio controls for pausing/resuming Project Studio generation safely."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from omnivoice.generation_control import clear_pause, pause_requested, request_pause


def build_generation_control_demo(
    model: Any,
    workspace: str | Path,
    *,
    controller_cls,
):
    import gradio as gr

    controller = controller_cls(model, workspace)

    def projects():
        return controller.list_projects()

    items = projects()
    initial = items[0] if items else None

    def state_message(project_path):
        if not project_path:
            return "No project selected."
        if pause_requested(project_path):
            return (
                "⏸ **PAUSED / pause requested.** If a section is already generating, it will "
                "finish safely first. The next section waits until you press **Resume**."
            )
        return "▶ **RUNNING / ready.** No pause is requested for this project."

    def refresh(project_path=None):
        choices = projects()
        selected = project_path if project_path in choices else (choices[0] if choices else None)
        return (
            gr.update(choices=choices, value=selected),
            state_message(selected),
        )

    def pause(project_path):
        if not project_path:
            raise gr.Error("Select a project first.")
        request_pause(project_path)
        return (
            "⏸ **Pause requested.** The current section, if any, will finish first. "
            "Generation will then wait before starting the next section."
        )

    def resume(project_path):
        if not project_path:
            raise gr.Error("Select a project first.")
        clear_pause(project_path)
        return (
            "▶ **Resume requested.** A paused Generate/Resume job will continue automatically "
            "from the next section/checkpoint."
        )

    with gr.Blocks(title="Pause / Resume") as demo:
        gr.Markdown(
            "# Pause / Resume generation\n"
            "Pause is cooperative and checkpoint-safe. OmniVoice never cuts a section in the middle "
            "of TTS inference. The active section completes, then the next section waits."
        )

        with gr.Row():
            project = gr.Dropdown(
                label="Project",
                choices=items,
                value=initial,
                scale=4,
            )
            refresh_button = gr.Button("Refresh", scale=1)

        with gr.Row():
            pause_button = gr.Button("⏸ Pause", variant="stop")
            resume_button = gr.Button("▶ Resume", variant="primary")

        status = gr.Markdown(state_message(initial))

        project.change(state_message, inputs=project, outputs=status)
        refresh_button.click(refresh, inputs=project, outputs=[project, status], queue=False)
        pause_button.click(pause, inputs=project, outputs=status, queue=False)
        resume_button.click(resume, inputs=project, outputs=status, queue=False)

    return demo
