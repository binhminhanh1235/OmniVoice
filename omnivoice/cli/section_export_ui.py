#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Gradio UI for downloading generated Project Studio section audio."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from omnivoice.cli.project_studio import ProjectStudioController
from omnivoice.section_export import (
    create_project_audio_archive,
    create_section_mp3_archive,
    export_section_mp3s,
    section_ids,
)


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

    def reset_download():
        return gr.update(value=None, visible=False)

    projects = project_items()
    initial_project = projects[0] if projects else None
    initial_sections, initial_generated, initial_total = selection_for(initial_project)

    def show_project(project_path):
        if not project_path:
            return (
                gr.update(choices=[], value=[]),
                [],
                reset_download(),
                reset_download(),
                "Select a project.",
            )
        try:
            ids, generated, total = selection_for(project_path)
            return (
                gr.update(choices=ids, value=ids),
                [],
                reset_download(),
                reset_download(),
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
            reset_download(),
            reset_download(),
            message,
        )

    def select_all(project_path):
        ids, _, _ = selection_for(project_path)
        return gr.update(choices=ids, value=ids)

    def clear_selection(project_path):
        ids, _, _ = selection_for(project_path)
        return gr.update(choices=ids, value=[])

    def prepare_project_zip(project_path):
        if not project_path:
            raise gr.Error("Select a project first.")
        try:
            project = controller.load_project(project_path)
            result = create_project_audio_archive(project)
        except Exception as exc:
            raise gr.Error(f"Project audio ZIP failed: {type(exc).__name__}: {exc}")

        message = (
            f"Prepared project audio ZIP with **{len(result.included)}** generated section file(s). "
            "Files are archived as-is; no merge or audio re-encoding was performed."
        )
        if result.skipped:
            message += " Skipped: " + "; ".join(result.skipped) + "."
        return (
            gr.update(value=str(result.archive), visible=True),
            message,
        )

    def prepare_downloads(project_path, selected_sections):
        if not project_path:
            raise gr.Error("Select a project first.")
        if not selected_sections:
            raise gr.Error("Select at least one section.")
        try:
            project = controller.load_project(project_path)
            result = export_section_mp3s(project, selected_sections)
            archive = (
                create_section_mp3_archive(project, result.files)
                if len(result.files) > 1
                else None
            )
        except Exception as exc:
            raise gr.Error(f"MP3 export failed: {type(exc).__name__}: {exc}")

        files = [str(path) for path in result.files]
        download_all = gr.update(
            value=str(archive) if archive else None,
            visible=archive is not None,
        )
        message = f"Prepared **{len(files)}** MP3 file(s)."
        if archive:
            message += " Use **Download all selected** to get them in one ZIP."
        if result.reused:
            message += f" Reused cached exports: {', '.join(result.reused)}."
        if result.skipped:
            message += " Skipped: " + "; ".join(result.skipped) + "."
        if not files:
            message += " Generate the selected sections first, then try again."
        return files, download_all, message

    with gr.Blocks(title="Project Audio Downloads") as demo:
        gr.Markdown(
            "# Download project audio\n"
            "Download all currently generated section audio in one ZIP without merging the project. "
            "The original section audio is copied into the archive as-is, so this is fast and does not "
            "re-encode or modify checkpoints/history."
        )

        with gr.Row():
            project = gr.Dropdown(
                label="Project",
                choices=projects,
                value=initial_project,
                scale=4,
            )
            refresh = gr.Button("Refresh projects")

        with gr.Row():
            project_zip_button = gr.Button(
                "Prepare project audio ZIP",
                variant="primary",
            )
            project_zip_download = gr.DownloadButton(
                "Download project audio ZIP",
                value=None,
                visible=False,
                variant="primary",
            )

        status = gr.Markdown(
            (
                f"Generated audio available for **{initial_generated}/{initial_total}** sections."
            )
            if initial_project
            else "No projects found."
        )

        gr.Markdown(
            "## Optional MP3 export\n"
            "If you want converted MP3 files instead, choose individual sections below."
        )
        sections = gr.CheckboxGroup(
            label="Sections to download as MP3",
            choices=initial_sections,
            value=initial_sections,
        )

        with gr.Row():
            all_button = gr.Button("Select all")
            none_button = gr.Button("Clear")
            export_button = gr.Button("Prepare selected MP3s")

        download_all = gr.DownloadButton(
            "Download all selected MP3s",
            value=None,
            visible=False,
        )
        files = gr.Files(
            label="MP3 files",
            file_count="multiple",
            type="filepath",
        )

        project.change(
            show_project,
            inputs=project,
            outputs=[sections, files, download_all, project_zip_download, status],
        )
        refresh.click(
            refresh_projects,
            outputs=[
                project,
                sections,
                files,
                download_all,
                project_zip_download,
                status,
            ],
        )
        project_zip_button.click(
            prepare_project_zip,
            inputs=project,
            outputs=[project_zip_download, status],
        )
        all_button.click(select_all, inputs=project, outputs=sections)
        none_button.click(clear_selection, inputs=project, outputs=sections)
        export_button.click(
            prepare_downloads,
            inputs=[project, sections],
            outputs=[files, download_all, status],
        )

    return demo
