#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Gradio tab for project deletion and optional Google Drive sync."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from omnivoice.cli.project_studio import ProjectStudioController
from omnivoice.data_management import (
    authorize_command,
    delete_projects,
    disconnect_drive,
    drive_connected,
    list_project_paths,
    rclone_available,
    save_drive_connection,
    sync_projects_to_drive,
    verify_drive_connection,
)
from omnivoice.runtime_rclone import install_rclone_runtime


def build_data_management_demo(
    model: Any,
    workspace: str | Path,
    *,
    controller_cls=ProjectStudioController,
):
    import gradio as gr

    # Keep the controller construction consistent with the rest of Studio even
    # though this tab only needs the shared workspace path.
    controller_cls(model, workspace)
    workspace = Path(workspace).expanduser()

    def project_items() -> list[str]:
        return list_project_paths(workspace)

    def connection_message() -> str:
        connected = drive_connected(workspace)
        rclone = rclone_available()
        if connected and rclone:
            return "✅ Google Drive credentials are connected for this runtime and rclone is available."
        if connected:
            return (
                "⚠️ Google Drive credentials are connected, but `rclone` is not installed in this runtime. "
                "Click **Install rclone in this runtime** before syncing."
            )
        if rclone:
            return "rclone is available. Connect a Google account when you want to sync."
        return (
            "rclone is not installed in this runtime. Click **Install rclone in this runtime**; "
            "the binary is installed only under the runtime temporary directory."
        )

    projects = project_items()

    def refresh_projects():
        items = project_items()
        return (
            gr.update(choices=items, value=[]),
            gr.update(choices=items, value=items),
            f"Found **{len(items)}** project(s).",
        )

    def delete_selected(selected, confirmed):
        if not confirmed:
            raise gr.Error("Confirm permanent deletion first.")
        if not selected:
            raise gr.Error("Select at least one project to delete.")
        try:
            result = delete_projects(workspace, selected)
        except Exception as exc:
            raise gr.Error(f"Delete failed: {type(exc).__name__}: {exc}")

        items = project_items()
        message = f"Deleted **{len(result.deleted)}** project(s): {', '.join(result.deleted)}."
        if result.removed_queue_items:
            message += f" Removed **{result.removed_queue_items}** related Project Queue item(s)."
        return (
            gr.update(choices=items, value=[]),
            gr.update(choices=items, value=items),
            gr.update(value=False),
            message,
        )

    def install_runtime_rclone():
        try:
            path, version = install_rclone_runtime()
            return f"✅ {version} · runtime binary: `{path}`. {connection_message()}"
        except Exception as exc:
            raise gr.Error(f"rclone install failed: {type(exc).__name__}: {exc}")

    def make_auth_command(client_id, client_secret):
        try:
            return authorize_command(client_id, client_secret)
        except Exception as exc:
            raise gr.Error(f"Cannot build authorization command: {exc}")

    def connect_account(client_id, client_secret, token_json):
        try:
            save_drive_connection(
                workspace,
                client_id=client_id,
                client_secret=client_secret,
                token_json=token_json,
            )
        except Exception as exc:
            raise gr.Error(f"Could not save Google Drive connection: {exc}")

        if not rclone_available():
            return (
                "Credentials saved in runtime-only storage. Install rclone in this runtime before syncing. "
                "No account is hard-coded; reconnecting with another token switches accounts."
            )
        try:
            verify_drive_connection(workspace)
            return "✅ Connected and verified. Google Drive account can now receive selected Studio data."
        except Exception as exc:
            return (
                "Credentials were saved, but Drive verification failed. "
                f"Check the OAuth token/rclone setup: {type(exc).__name__}: {exc}"
            )

    def disconnect_account():
        disconnect_drive(workspace)
        return "Disconnected Google Drive for this runtime. No OAuth credential remains in runtime storage."

    def check_connection():
        if not drive_connected(workspace):
            return connection_message()
        if not rclone_available():
            return connection_message()
        try:
            verify_drive_connection(workspace)
            return "✅ Google Drive connection verified."
        except Exception as exc:
            return f"⚠️ Google Drive verification failed: {type(exc).__name__}: {exc}"

    def sync_selected(selected, destination, include_voices, include_settings):
        if not selected:
            raise gr.Error("Select at least one project to sync.")
        if not drive_connected(workspace):
            raise gr.Error("Connect a Google Drive account first.")
        if not rclone_available():
            raise gr.Error("rclone is not installed in this runtime.")
        try:
            result = sync_projects_to_drive(
                workspace,
                selected,
                destination=destination,
                include_voices=bool(include_voices),
                include_hardware_settings=bool(include_settings),
            )
        except Exception as exc:
            raise gr.Error(f"Google Drive sync failed: {type(exc).__name__}: {exc}")

        message = (
            f"✅ Synced **{len(result.synced_projects)}** project(s) to "
            f"`Google Drive/{result.destination}/projects`: {', '.join(result.synced_projects)}."
        )
        if result.included_voices:
            message += " Voice Library sync was enabled."
        if result.included_hardware_settings:
            message += " Hardware quality settings sync was enabled."
        return message

    initial_client_id = os.getenv("OMNIVOICE_GDRIVE_CLIENT_ID", "")
    initial_client_secret = os.getenv("OMNIVOICE_GDRIVE_CLIENT_SECRET", "")

    with gr.Blocks(title="Data Management") as demo:
        gr.Markdown(
            "# Data Management\n"
            "Delete one or many projects, or optionally copy selected Studio data to Google Drive. "
            "Google account credentials are never committed to the repository and are stored only for the current runtime."
        )

        gr.Markdown("## Delete projects")
        delete_selection = gr.CheckboxGroup(
            label="Projects to permanently delete",
            choices=projects,
            value=[],
        )
        with gr.Row():
            delete_confirm = gr.Checkbox(
                label="I understand these projects will be permanently deleted",
                value=False,
                scale=3,
            )
            delete_button = gr.Button("Delete selected projects", variant="stop")
        delete_status = gr.Markdown("No project selected for deletion.")

        gr.Markdown(
            "## Optional Google Drive sync\n"
            "This uses rclone OAuth. The OAuth Client ID/Secret identify your Google app, not a fixed Drive account. "
            "When you run the authorization command, Google shows its normal account chooser, so you can connect or switch accounts per runtime."
        )
        drive_status = gr.Markdown(connection_message())

        with gr.Row():
            install_rclone_button = gr.Button("Install rclone in this runtime")
            check_drive_button = gr.Button("Check connection")
            disconnect_button = gr.Button("Disconnect / switch account")

        with gr.Accordion("1. Connect or switch Google account", open=not drive_connected(workspace)):
            client_id = gr.Textbox(
                label="Google OAuth Client ID",
                value=initial_client_id,
                placeholder="...apps.googleusercontent.com",
            )
            client_secret = gr.Textbox(
                label="Google OAuth Client Secret",
                value=initial_client_secret,
                type="password",
            )
            auth_button = gr.Button("Generate rclone authorize command")
            auth_command = gr.Textbox(
                label="Run this command on a computer with a browser",
                interactive=False,
                placeholder="rclone authorize drive ...",
            )
            gr.Markdown(
                "Run the command locally, choose the Google account in the browser, then copy the returned token JSON below. "
                "For headless Kaggle this is the standard remote-authorization pattern."
            )
            token_json = gr.Textbox(
                label="Authorization token JSON",
                type="password",
                placeholder='{"access_token":"...","refresh_token":"...",...}',
            )
            connect_button = gr.Button("Connect / replace Google account", variant="primary")

        gr.Markdown("### Sync selected Studio data")
        sync_selection = gr.CheckboxGroup(
            label="Projects to sync",
            choices=projects,
            value=projects,
        )
        with gr.Row():
            destination = gr.Textbox(
                label="Google Drive destination folder",
                value="OmniVoiceStudio",
                scale=3,
            )
            refresh_button = gr.Button("Refresh projects")
        with gr.Row():
            include_voices = gr.Checkbox(
                label="Include Voice Library",
                value=True,
            )
            include_settings = gr.Checkbox(
                label="Include Hardware & Quality settings",
                value=True,
            )
            sync_button = gr.Button("Sync selected to Google Drive", variant="primary")
        sync_status = gr.Markdown(
            "Sync uses incremental `rclone copy`: it uploads new/changed files and does not delete extra files already on Google Drive."
        )

        refresh_button.click(
            refresh_projects,
            outputs=[delete_selection, sync_selection, delete_status],
        )
        delete_button.click(
            delete_selected,
            inputs=[delete_selection, delete_confirm],
            outputs=[delete_selection, sync_selection, delete_confirm, delete_status],
        )
        install_rclone_button.click(install_runtime_rclone, outputs=drive_status)
        auth_button.click(
            make_auth_command,
            inputs=[client_id, client_secret],
            outputs=auth_command,
        )
        connect_button.click(
            connect_account,
            inputs=[client_id, client_secret, token_json],
            outputs=drive_status,
        )
        disconnect_button.click(disconnect_account, outputs=drive_status)
        check_drive_button.click(check_connection, outputs=drive_status)
        sync_button.click(
            sync_selected,
            inputs=[sync_selection, destination, include_voices, include_settings],
            outputs=sync_status,
        )

    return demo
