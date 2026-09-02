import json
import subprocess
from pathlib import Path

import pytest

from omnivoice.cli.data_management_ui import build_data_management_demo
from omnivoice.data_management import (
    authorize_command,
    delete_projects,
    disconnect_drive,
    drive_connected,
    list_project_paths,
    save_drive_connection,
    sync_projects_to_drive,
    verify_drive_connection,
)
from omnivoice.project import OmniVoiceProject
from omnivoice.project_queue import ProjectQueueItem, ProjectQueueStore


SCRIPT = """# Data Management Demo

## S01 — 0:00–0:10

A short project section.
"""


class FakeModel:
    sampling_rate = 24000


def _project(workspace: Path, name: str) -> OmniVoiceProject:
    return OmniVoiceProject.create(SCRIPT, workspace / "projects" / name)


def test_delete_multiple_projects_and_cleanup_queue(tmp_path):
    workspace = tmp_path / "studio"
    first = _project(workspace, "first")
    second = _project(workspace, "second")

    store = ProjectQueueStore(workspace)
    manifest = store.load()
    manifest.items.append(
        ProjectQueueItem(
            id="queued-one",
            project_path=str(first.root.resolve()),
            project_title="First",
            voice_name="Narrator",
            status="pending",
        )
    )
    store.save(manifest)

    result = delete_projects(workspace, [first.root, second.root])

    assert result.deleted == ("first", "second")
    assert result.removed_queue_items == 1
    assert not first.root.exists()
    assert not second.root.exists()
    assert list_project_paths(workspace) == []
    assert store.load().items == []


def test_delete_rejects_running_queue_project_and_path_escape(tmp_path):
    workspace = tmp_path / "studio"
    project = _project(workspace, "running")

    store = ProjectQueueStore(workspace)
    manifest = store.load()
    manifest.items.append(
        ProjectQueueItem(
            id="running-one",
            project_path=str(project.root.resolve()),
            project_title="Running",
            voice_name="Narrator",
            status="running",
        )
    )
    store.save(manifest)

    with pytest.raises(ValueError, match="actively generating"):
        delete_projects(workspace, [project.root])
    assert project.root.exists()

    outside = OmniVoiceProject.create(SCRIPT, tmp_path / "outside")
    with pytest.raises(ValueError, match="direct child"):
        delete_projects(workspace, [outside.root])
    assert outside.root.exists()


def test_delete_rejects_direct_inflight_section_generation(tmp_path):
    workspace = tmp_path / "studio"
    project = _project(workspace, "direct-running")
    (project.root / "section-status.json").write_text(
        json.dumps(
            {
                "version": 1,
                "sections": {
                    "S01": {
                        "status": "generating",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="in-progress section generation"):
        delete_projects(workspace, [project.root])
    assert project.root.exists()


def test_drive_credentials_are_runtime_only_and_switchable(tmp_path):
    workspace = tmp_path / "studio"
    token_one = json.dumps({"access_token": "one", "refresh_token": "refresh-one"})
    token_two = json.dumps({"access_token": "two", "refresh_token": "refresh-two"})

    command = authorize_command("client-id", "client-secret")
    assert command.startswith("rclone authorize drive ")
    assert "client-id" in command

    secret_path = save_drive_connection(
        workspace,
        client_id="client-id",
        client_secret="client-secret",
        token_json=token_one,
    )
    assert drive_connected(workspace)
    assert not str(secret_path).startswith(str(workspace.resolve()))
    if hasattr(secret_path.stat(), "st_mode"):
        assert secret_path.stat().st_mode & 0o777 == 0o600

    save_drive_connection(
        workspace,
        client_id="client-id",
        client_secret="client-secret",
        token_json=token_two,
    )
    assert "two" in secret_path.read_text(encoding="utf-8")

    disconnect_drive(workspace)
    assert not drive_connected(workspace)


def test_drive_sync_uses_env_credentials_not_command_line(tmp_path, monkeypatch):
    workspace = tmp_path / "studio"
    project = _project(workspace, "project-one")
    voices = workspace / "voices"
    voices.mkdir(parents=True)
    (voices / "voice.json").write_text("{}", encoding="utf-8")
    (workspace / "hardware-quality.json").write_text("{}", encoding="utf-8")

    save_drive_connection(
        workspace,
        client_id="client-id-secret-value",
        client_secret="client-secret-value",
        token_json=json.dumps(
            {"access_token": "access-secret-value", "refresh_token": "refresh-secret-value"}
        ),
    )

    calls = []

    def fake_run(command, **kwargs):
        calls.append((list(command), dict(kwargs.get("env") or {})))
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("omnivoice.data_management._rclone_binary", lambda explicit=None: "/usr/bin/rclone")
    monkeypatch.setattr("omnivoice.data_management.subprocess.run", fake_run)

    assert verify_drive_connection(workspace) == "Google Drive connection verified."
    result = sync_projects_to_drive(
        workspace,
        [project.root],
        destination="Backups/OmniVoice",
        include_voices=True,
        include_hardware_settings=True,
    )

    assert result.synced_projects == ("project-one",)
    assert result.destination == "Backups/OmniVoice"
    commands = [" ".join(call[0]) for call in calls]
    assert any("lsd omnivoice_drive:" in command for command in commands)
    assert any("copy" in command and "project-one" in command for command in commands)
    assert any("/voices" in command for command in commands)
    assert any("copyto" in command and "hardware-quality.json" in command for command in commands)

    combined_commands = "\n".join(commands)
    assert "client-secret-value" not in combined_commands
    assert "access-secret-value" not in combined_commands
    assert "refresh-secret-value" not in combined_commands

    env = calls[0][1]
    assert env["RCLONE_CONFIG_OMNIVOICE_DRIVE_TYPE"] == "drive"
    assert env["RCLONE_CONFIG_OMNIVOICE_DRIVE_CLIENT_ID"] == "client-id-secret-value"
    assert "refresh-secret-value" in env["RCLONE_CONFIG_OMNIVOICE_DRIVE_TOKEN"]


def test_data_management_gradio_smoke(tmp_path):
    demo = build_data_management_demo(FakeModel(), tmp_path / "studio")
    assert demo is not None
