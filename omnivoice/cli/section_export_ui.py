#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Gradio UI for exporting Project Studio sections as individual MP3 files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from omnivoice.cli.project_studio import ProjectStudioController
from omnivoice.section_export import export_section_mp3s, section_ids


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

    def selection_for(project_path: str | None):
        if not project_path:
            return [], 0, 0
        project = controller.load_project(project_path)
        ids = section_ids(project)
        generated = sum(
            bool(section.audio_file and (project.root / section.audio_file).exists())
            for section in project.manifest.sections
        )
        return ids, generated, len(ids)

    projects = project_items()
    initial_project = projects[0] if projects else None
    initial_sections, initial_generated, initial_total = selection_for(initial_project)

    def show_project(project_path):
        if not project_path:
            return (
                gr.update(choices=[], value=[]),
                [],
                "Select a project.",
            )
        try:
            ids, generated, total = selection_for(project_path)
            return (
                gr.update(choices=ids, value=ids),
                [],
                f"Selected all **{total}** sections by default · generated audio available for **{generated}/{total}**.",
            )
        except Exception as exc:
            raise gr.Error(f"Cannot load project: {type(exc).__name__}: {exc}")

    def refresh_projects():
        items = project_items()
        selected = items[0] if items else None
        if selected:
            ids, generated, total = selection_for(selected)
            message = (
                f"Selected all **{total}** sections by default · generated audio available for "
                f"**{generated}/{total}**."
            )
        else:
            ids, message = [], "No projects found."
        return (
            gr.update(choices=items, value=selected),
            gr.update(choices=ids, value=ids),
            [],
            message,
        )

    def select_all(project_path):
        ids, _, _ = selection_for(project_path)
        return gr.update(choices=ids, value=ids)

    def clear_selection(project_path):
        ids, _, _ = selection_for(project_path)
        return gr.update(choices=ids, value=[])

    def prepare_downloads(project_path, selected_sections):
        if not project_path:
            raise gr.Error("Select a project first.")
        if not selected_sections:
            raise gr.Error("Select at least one section.")
        try:
            project = controller.load_project(project_path)
            result = export_section_mp3s(project, selected_sections)
        except Exception as exc:
            raise gr.Error(f"MP3 export failed: {type(exc).__name__}: {exc}")

        files = [str(path) for path in result.files]
        message = f"Prepared **{len(files)}** MP3 file(s)."
        if result.reused:
            message += f" Reused cached exports: {', '.join(result.reused)}."
        if result.skipped:
            message += " Skipped: " + "; ".join(result.skipped) + "."
        if not files:
            message += " Generate the selected sections first, then try again."
        return files, message

    with gr.Blocks(title="Section MP3 Downloads") as demo:
        gr.Markdown(
            "# Download section MP3 files\n"
            "Choose a project, keep all sections checked or uncheck the ones you do not need, "
            "then prepare individual MP3 files. Original WAV/checkpoint/history files are untouched."
        )

        with gr.Row():
            project = gr.Dropdown(
                label="Project",
                choices=projects,
                value=initial_project,
                scale=4,
            )
            refresh = gr.Button("Refresh projects")

        sections = gr.CheckboxGroup(
            label="Sections to download as MP3",
            choices=initial_sections,
            value=initial_sections,
        )

        with gr.Row():
            all_button = gr.Button("Select all")
            none_button = gr.Button("Clear")
            export_button = gr.Button("Prepare selected MP3s", variant="primary")

        status = gr.Markdown(
            (
                f"Selected all **{initial_total}** sections by default · generated audio available "
                f"for **{initial_generated}/{initial_total}**."
            )
            if initial_project
            else "No projects found."
        )
        files = gr.Files(
            label="MP3 files",
            file_count="multiple",
            type="filepath",
        )

        project.change(
            show_project,
            inputs=project,
            outputs=[sections, files, status],
        )
        refresh.click(
            refresh_projects,
            outputs=[project, sections, files, status],
        )
        all_button.click(select_all, inputs=project, outputs=sections)
        none_button.click(clear_selection, inputs=project, outputs=sections)
        export_button.click(
            prepare_downloads,
            inputs=[project, sections],
            outputs=[files, status],
        )

    return demo
