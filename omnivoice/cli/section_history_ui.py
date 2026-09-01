#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Gradio panel for section audio/checkpoint version history."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Type

from omnivoice.cli.project_studio import ProjectStudioController


HISTORY_HEADERS = ["Version", "Created", "Reason", "Saved status"]


def build_section_history_demo(
    model: Any,
    workspace: str | Path,
    *,
    controller_cls: Type[ProjectStudioController],
):
    import gradio as gr

    controller = controller_cls(model, workspace)
    projects = controller.list_projects()
    initial_project = projects[0] if projects else None

    def section_choices(project_path):
        if not project_path:
            return []
        project = controller.load_project(project_path)
        return [section.id for section in project.manifest.sections]

    initial_sections = section_choices(initial_project) if initial_project else []
    initial_section = initial_sections[0] if initial_sections else None

    def version_payload(project_path, section_id):
        if not project_path or not section_id:
            return [], [], None
        versions = controller.section_versions(project_path, section_id)
        rows = [
            [item.id, item.created_at, item.reason, item.status]
            for item in versions
        ]
        choices = [item.id for item in versions]
        value = choices[0] if choices else None
        return rows, choices, value

    initial_rows, initial_versions, initial_version = version_payload(
        initial_project, initial_section
    ) if initial_project and initial_section else ([], [], None)

    def refresh_all(project_path=None):
        choices = controller.list_projects()
        selected_project = project_path if project_path in choices else (choices[0] if choices else None)
        sections = section_choices(selected_project) if selected_project else []
        selected_section = sections[0] if sections else None
        rows, versions, selected_version = (
            version_payload(selected_project, selected_section)
            if selected_project and selected_section
            else ([], [], None)
        )
        return (
            gr.update(choices=choices, value=selected_project),
            gr.update(choices=sections, value=selected_section),
            rows,
            gr.update(choices=versions, value=selected_version),
            None,
            f"Found {len(choices)} projects. {len(versions)} versions for {selected_section or 'no section'}.",
        )

    def project_changed(project_path):
        sections = section_choices(project_path) if project_path else []
        selected_section = sections[0] if sections else None
        rows, versions, selected_version = (
            version_payload(project_path, selected_section)
            if project_path and selected_section
            else ([], [], None)
        )
        return (
            gr.update(choices=sections, value=selected_section),
            rows,
            gr.update(choices=versions, value=selected_version),
            None,
            f"Loaded {selected_section or 'project without sections'}.",
        )

    def section_changed(project_path, section_id):
        rows, versions, selected_version = version_payload(project_path, section_id)
        return (
            rows,
            gr.update(choices=versions, value=selected_version),
            None,
            f"{len(versions)} archived versions for {section_id}.",
        )

    def play_version(project_path, section_id, version_id):
        if not project_path or not section_id or not version_id:
            return None
        try:
            return str(
                controller.section_version_audio(
                    project_path,
                    section_id,
                    version_id,
                )
            )
        except Exception as exc:
            raise gr.Error(f"Cannot play version: {type(exc).__name__}: {exc}")

    def snapshot(project_path, section_id, reason):
        if not project_path or not section_id:
            raise gr.Error("Select a project and section first.")
        try:
            version = controller.snapshot_section(
                project_path,
                section_id,
                reason=(reason or "manual snapshot"),
            )
        except Exception as exc:
            raise gr.Error(f"Snapshot failed: {type(exc).__name__}: {exc}")
        if version is None:
            raise gr.Error(f"{section_id} has no final WAV to snapshot yet.")
        rows, versions, selected_version = version_payload(project_path, section_id)
        return (
            rows,
            gr.update(choices=versions, value=version.id),
            str(controller.section_version_audio(project_path, section_id, version.id)),
            f"Saved {section_id}/{version.id}: {version.reason}",
        )

    def restore(project_path, section_id, version_id, keep_current):
        if not project_path or not section_id or not version_id:
            raise gr.Error("Select project, section, and version first.")
        try:
            project = controller.restore_section_version(
                project_path,
                section_id,
                version_id,
                snapshot_current=bool(keep_current),
            )
            current_audio = str(controller.section_audio(project.root, section_id))
        except Exception as exc:
            raise gr.Error(f"Restore failed: {type(exc).__name__}: {exc}")
        rows, versions, selected_version = version_payload(project.root, section_id)
        return (
            rows,
            gr.update(choices=versions, value=selected_version),
            current_audio,
            f"Restored {section_id} from {version_id}. Resume checkpoints were synchronized.",
        )

    with gr.Blocks(title="Section Version History") as demo:
        gr.Markdown(
            "# Section Version History\n"
            "Before a generated section is regenerated, OmniVoice Studio archives the previous "
            "section WAV **and its beat/chunk checkpoints**. Listen to old versions or restore one "
            "without losing resume consistency."
        )
        with gr.Row():
            project = gr.Dropdown(
                label="Project",
                choices=projects,
                value=initial_project,
            )
            section = gr.Dropdown(
                label="Section",
                choices=initial_sections,
                value=initial_section,
            )
            refresh = gr.Button("Refresh")

        history_table = gr.Dataframe(
            value=initial_rows,
            headers=HISTORY_HEADERS,
            interactive=False,
            wrap=True,
        )

        with gr.Row():
            version = gr.Dropdown(
                label="Archived version",
                choices=initial_versions,
                value=initial_version,
            )
            play = gr.Button("Play archived version")
        archived_audio = gr.Audio(label="Archived section audio", type="filepath")

        gr.Markdown("## Manual checkpoint")
        with gr.Row():
            reason = gr.Textbox(
                label="Snapshot note",
                value="manual snapshot before editing",
            )
            snapshot_button = gr.Button("Snapshot current section")

        gr.Markdown("## Restore")
        keep_current = gr.Checkbox(
            label="Snapshot current section before restore (recommended)",
            value=True,
        )
        restore_button = gr.Button("Restore selected version", variant="primary")
        restored_audio = gr.Audio(label="Current section after restore", type="filepath")
        status = gr.Markdown("Ready.")

        refresh.click(
            refresh_all,
            inputs=project,
            outputs=[project, section, history_table, version, archived_audio, status],
        )
        project.change(
            project_changed,
            inputs=project,
            outputs=[section, history_table, version, archived_audio, status],
        )
        section.change(
            section_changed,
            inputs=[project, section],
            outputs=[history_table, version, archived_audio, status],
        )
        version.change(
            play_version,
            inputs=[project, section, version],
            outputs=archived_audio,
        )
        play.click(
            play_version,
            inputs=[project, section, version],
            outputs=archived_audio,
        )
        snapshot_button.click(
            snapshot,
            inputs=[project, section, reason],
            outputs=[history_table, version, archived_audio, status],
        )
        restore_button.click(
            restore,
            inputs=[project, section, version, keep_current],
            outputs=[history_table, version, restored_audio, status],
        )

    return demo
