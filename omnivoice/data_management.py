#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Safe Project Studio data management and optional Google Drive sync."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from omnivoice.project_queue import ProjectQueueStore

_DRIVE_REMOTE = "omnivoice_drive"
_CREDENTIAL_FILE = "google-drive.json"
_REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class DeleteProjectsResult:
    deleted: tuple[str, ...]
    removed_queue_items: int


@dataclass(frozen=True)
class DriveSyncResult:
    synced_projects: tuple[str, ...]
    included_voices: bool
    included_hardware_settings: bool
    destination: str


def _projects_root(workspace: str | Path) -> Path:
    root = Path(workspace).expanduser() / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _validate_project_path(workspace: str | Path, project_path: str | Path) -> Path:
    root = _projects_root(workspace)
    raw = Path(project_path).expanduser()
    candidate = raw if raw.is_absolute() else root / raw
    if candidate.is_symlink():
        raise ValueError(f"Refusing symlink project path: {candidate}")
    resolved = candidate.resolve()
    if resolved.parent != root:
        raise ValueError(f"Project must be a direct child of {root}: {candidate}")
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"Project does not exist: {resolved}")
    if not (resolved / "project.json").exists():
        raise ValueError(f"Not an OmniVoice project: {resolved}")
    return resolved


def list_project_paths(workspace: str | Path) -> list[str]:
    root = _projects_root(workspace)
    items: list[str] = []
    for path in sorted(root.iterdir()):
        if path.is_dir() and not path.is_symlink() and (path / "project.json").exists():
            items.append(str(path.resolve()))
    return items


def delete_projects(
    workspace: str | Path,
    selected: Iterable[str | Path],
) -> DeleteProjectsResult:
    targets = [_validate_project_path(workspace, item) for item in selected]
    if not targets:
        raise ValueError("Select at least one project to delete")

    target_set = {str(path) for path in targets}
    queue_store = ProjectQueueStore(workspace)
    manifest = queue_store.load()
    running = [
        item.project_title
        for item in manifest.items
        if str(Path(item.project_path).expanduser().resolve()) in target_set
        and item.status == "running"
    ]
    if running:
        raise ValueError(
            "Cannot delete a project while it is actively generating in Project Queue: "
            + ", ".join(running)
        )

    before = len(manifest.items)
    manifest.items = [
        item
        for item in manifest.items
        if str(Path(item.project_path).expanduser().resolve()) not in target_set
    ]
    removed_queue_items = before - len(manifest.items)
    if removed_queue_items:
        queue_store.save(manifest)

    deleted: list[str] = []
    for path in targets:
        name = path.name
        shutil.rmtree(path)
        deleted.append(name)

    return DeleteProjectsResult(
        deleted=tuple(deleted),
        removed_queue_items=removed_queue_items,
    )


def _runtime_secret_dir(workspace: str | Path) -> Path:
    workspace_key = str(Path(workspace).expanduser().resolve())
    digest = hashlib.sha256(workspace_key.encode("utf-8")).hexdigest()[:12]
    root = Path(tempfile.gettempdir()) / f"omnivoice-drive-{digest}"
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _credential_path(workspace: str | Path) -> Path:
    return _runtime_secret_dir(workspace) / _CREDENTIAL_FILE


def _validate_token_json(token_json: str) -> dict:
    try:
        payload = json.loads((token_json or "").strip())
    except json.JSONDecodeError as exc:
        raise ValueError("Authorization token must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Authorization token JSON must be an object")
    if not payload.get("access_token") and not payload.get("refresh_token"):
        raise ValueError("Authorization token must contain access_token or refresh_token")
    return payload


def authorize_command(client_id: str, client_secret: str) -> str:
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not client_id or not client_secret:
        raise ValueError("Enter Google OAuth Client ID and Client Secret first")
    return "rclone authorize drive " + shlex.quote(client_id) + " " + shlex.quote(client_secret)


def save_drive_connection(
    workspace: str | Path,
    *,
    client_id: str,
    client_secret: str,
    token_json: str,
) -> Path:
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not client_id or not client_secret:
        raise ValueError("Google OAuth Client ID and Client Secret are required")
    token = _validate_token_json(token_json)
    path = _credential_path(workspace)
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "token": token,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    temp.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def disconnect_drive(workspace: str | Path) -> None:
    _credential_path(workspace).unlink(missing_ok=True)


def drive_connected(workspace: str | Path) -> bool:
    return _credential_path(workspace).exists()


def _load_drive_connection(workspace: str | Path) -> dict:
    path = _credential_path(workspace)
    if not path.exists():
        raise RuntimeError("Google Drive is not connected for this runtime")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Saved Google Drive connection is unreadable") from exc
    token = payload.get("token")
    if not isinstance(token, dict):
        raise RuntimeError("Saved Google Drive token is invalid")
    return payload


def _rclone_binary(explicit: Optional[str] = None) -> str:
    candidate = explicit or shutil.which("rclone")
    if not candidate:
        raise RuntimeError(
            "rclone is required for Google Drive sync. Install rclone in the runtime first."
        )
    return str(candidate)


def rclone_available(explicit: Optional[str] = None) -> bool:
    try:
        _rclone_binary(explicit)
        return True
    except RuntimeError:
        return False


def _rclone_env(workspace: str | Path) -> dict[str, str]:
    state = _load_drive_connection(workspace)
    remote = _DRIVE_REMOTE.upper()
    if not _REMOTE_NAME_RE.fullmatch(remote):
        raise RuntimeError("Invalid internal rclone remote name")
    env = os.environ.copy()
    env.update(
        {
            f"RCLONE_CONFIG_{remote}_TYPE": "drive",
            f"RCLONE_CONFIG_{remote}_CLIENT_ID": str(state["client_id"]),
            f"RCLONE_CONFIG_{remote}_CLIENT_SECRET": str(state["client_secret"]),
            f"RCLONE_CONFIG_{remote}_SCOPE": "drive",
            f"RCLONE_CONFIG_{remote}_TOKEN": json.dumps(state["token"], separators=(",", ":")),
        }
    )
    return env


def _empty_rclone_config(workspace: str | Path) -> Path:
    path = _runtime_secret_dir(workspace) / "rclone-empty.conf"
    if not path.exists():
        path.write_text("", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path


def _run_rclone(
    workspace: str | Path,
    args: list[str],
    *,
    rclone_binary: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    binary = _rclone_binary(rclone_binary)
    command = [binary, "--config", str(_empty_rclone_config(workspace)), *args]
    completed = subprocess.run(
        command,
        env=_rclone_env(workspace),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        detail = detail[-1200:] if detail else f"exit code {completed.returncode}"
        raise RuntimeError(f"rclone failed: {detail}")
    return completed


def verify_drive_connection(
    workspace: str | Path,
    *,
    rclone_binary: Optional[str] = None,
) -> str:
    _run_rclone(
        workspace,
        ["lsd", f"{_DRIVE_REMOTE}:", "--max-depth", "1"],
        rclone_binary=rclone_binary,
    )
    return "Google Drive connection verified."


def _normalise_destination(value: str) -> str:
    cleaned = (value or "OmniVoiceStudio").strip().strip("/")
    if not cleaned:
        cleaned = "OmniVoiceStudio"
    parts = [part for part in cleaned.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise ValueError("Google Drive destination cannot contain . or .. path segments")
    return "/".join(parts)


def sync_projects_to_drive(
    workspace: str | Path,
    selected: Iterable[str | Path],
    *,
    destination: str = "OmniVoiceStudio",
    include_voices: bool = True,
    include_hardware_settings: bool = True,
    rclone_binary: Optional[str] = None,
) -> DriveSyncResult:
    projects = [_validate_project_path(workspace, item) for item in selected]
    if not projects:
        raise ValueError("Select at least one project to sync")
    destination = _normalise_destination(destination)

    synced: list[str] = []
    for project in projects:
        remote_path = f"{_DRIVE_REMOTE}:{destination}/projects/{project.name}"
        _run_rclone(
            workspace,
            [
                "copy",
                str(project),
                remote_path,
                "--create-empty-src-dirs",
                "--stats-one-line",
                "--stats",
                "2s",
            ],
            rclone_binary=rclone_binary,
        )
        synced.append(project.name)

    workspace_path = Path(workspace).expanduser()
    if include_voices:
        voices = workspace_path / "voices"
        if voices.exists() and voices.is_dir():
            _run_rclone(
                workspace,
                [
                    "copy",
                    str(voices),
                    f"{_DRIVE_REMOTE}:{destination}/voices",
                    "--create-empty-src-dirs",
                ],
                rclone_binary=rclone_binary,
            )

    if include_hardware_settings:
        settings = workspace_path / "hardware-quality.json"
        if settings.exists() and settings.is_file():
            _run_rclone(
                workspace,
                [
                    "copyto",
                    str(settings),
                    f"{_DRIVE_REMOTE}:{destination}/hardware-quality.json",
                ],
                rclone_binary=rclone_binary,
            )

    return DriveSyncResult(
        synced_projects=tuple(synced),
        included_voices=bool(include_voices),
        included_hardware_settings=bool(include_hardware_settings),
        destination=destination,
    )
