#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Compatibility export panel for downloading native Project Studio audio ZIPs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from omnivoice.cli.project_studio import ProjectStudioController
from omnivoice.section_export import create_project_audio_archive


def build_section_export_demo(
    model: Any,
    workspace: str | Path,
    *,
    controller_cls=ProjectStudioController,
):
    import gradio as gr

    controller = controller_cls(model, workspace)

    def project_items() -> list[str]:
        return controller.list_projects()

    projects = project_items()
    initial_project = projects[0] if projects else None

    def refresh_projects():
        items = project_items()
        selected = items[0] if items else None
        return gr.update(choices=items, value=selected), gr.update(value=None, visible=False), "Ready."

    def prepare_project_zip(project_path):
        if not project_path:
            raise gr.Error("Select a project first.")
        try:
            project = controller.load_project(project_path)
            result = create_project_audio_archive(project)
        except Exception as exc:
            raise gr.Error(f"Project audio ZIP failed: {type(exc).__name__}: {exc}")

        message = f"Prepared **{len(result.included)}** generated section audio file(s)."
        if result.skipped:
            message += " Skipped: " + "; ".join(result.skipped) + "."
        return gr.update(value=str(result.archive), visible=True), message

    with gr.Blocks(title="Project Audio ZIP") as demo:
        gr.Markdown(
            "# Download generated project audio\n"
            "Creates one ZIP from the section audio files that already exist. "
            "Nothing is merged or converted."
        )
        with gr.Row():
            project = gr.Dropdown(label="Project", choices=projects, value=initial_project, scale=4)
            refresh = gr.Button("Refresh projects")
        prepare = gr.Button("Prepare project audio ZIP", variant="primary")
        download = gr.DownloadButton("Download project audio ZIP", value=None, visible=False, variant="primary")
        status = gr.Markdown("Ready." if initial_project else "No projects found.")

        refresh.click(refresh_projects, outputs=[project, download, status])
        project.change(lambda: (gr.update(value=None, visible=False), "Ready."), outputs=[download, status])
        prepare.click(prepare_project_zip, inputs=project, outputs=[download, status])

    return demo
