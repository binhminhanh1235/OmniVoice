#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Durable hosted-runtime persistence for the complete Studio workspace.

Generation stays on the hosted runtime's local SSD. Durable state is mirrored
out-of-band so Voice Library entries, projects, queue/jobs, settings and audio
artifacts survive a discarded Colab/Kaggle session.

Colab uses an already-mounted Google Drive directory. Kaggle can use Google
Drive through rclone when three one-time Kaggle Secrets are configured:
``OMNIVOICE_GDRIVE_CLIENT_ID``, ``OMNIVOICE_GDRIVE_CLIENT_SECRET`` and
``OMNIVOICE_GDRIVE_TOKEN_JSON``. Credentials are copied only into the existing
runtime-only rclone credential store; they are never written into the Studio
workspace or repository.
"""

from __future__ import annotations

import atexit
import os
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from omnivoice.data_management import (
    _normalise_destination,
    _run_rclone,
    drive_connected,
    rclone_available,
    save_drive_connection,
)
from omnivoice.runtime_rclone import install_rclone_runtime
from omnivoice.runtime_workspace import RuntimeWorkspace

PERSISTENCE_INTERVAL_ENV = "OMNIVOICE_PERSISTENCE_INTERVAL_SECONDS"
PERSISTENCE_MODE_ENV = "OMNIVOICE_PERSISTENCE_MODE"
GDRIVE_CLIENT_ID_ENV = "OMNIVOICE_GDRIVE_CLIENT_ID"
GDRIVE_CLIENT_SECRET_ENV = "OMNIVOICE_GDRIVE_CLIENT_SECRET"
GDRIVE_TOKEN_ENV = "OMNIVOICE_GDRIVE_TOKEN_JSON"
GDRIVE_DESTINATION_ENV = "OMNIVOICE_GDRIVE_DESTINATION"
DEFAULT_DESTINATION = "OmniVoiceStudio"
DEFAULT_INTERVAL_SECONDS = 15.0
_MIRROR_THREAD_NAME = "omnivoice-drive-mirror"

# Startup-cache evidence belongs to the runtime/cache subsystem, not the user
# workspace. Everything else under the workspace is durable Studio state.
_EXCLUDED_TOP_LEVEL = {
    ".startup-cache",
    ".startup-evidence",
    ".runtime-cache.json",
    "startup-cache-evidence.json",
}


def _is_excluded(relative: Path) -> bool:
    if not relative.parts:
        return False
    if relative.parts[0] in _EXCLUDED_TOP_LEVEL:
        return True
    return any(part.endswith(".tmp") or part.startswith(".nfs") for part in relative.parts)


def _rclone_exclude_args() -> list[str]:
    patterns = [
        ".startup-cache/**",
        ".startup-evidence/**",
        ".runtime-cache.json",
        "startup-cache-evidence.json",
        "**/*.tmp",
        "**/.nfs*",
    ]
    args: list[str] = []
    for pattern in patterns:
        args.extend(["--exclude", pattern])
    return args


def _copy_workspace_tree(source: Path, destination: Path, *, delete: bool) -> None:
    """Mirror durable workspace files without copying runtime cache evidence."""

    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    source.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)

    for path in source.rglob("*"):
        if path.is_symlink():
            continue
        relative = path.relative_to(source)
        if _is_excluded(relative):
            continue
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            same = (
                target.is_file()
                and target.stat().st_size == path.stat().st_size
                and int(target.stat().st_mtime_ns) == int(path.stat().st_mtime_ns)
            )
        except OSError:
            same = False
        if not same:
            shutil.copy2(path, target)

    if not delete:
        return

    paths = sorted(destination.rglob("*"), key=lambda item: len(item.parts), reverse=True)
    for path in paths:
        relative = path.relative_to(destination)
        if _is_excluded(relative):
            continue
        source_path = source / relative
        if source_path.exists():
            continue
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass


def _thread_running(name: str = _MIRROR_THREAD_NAME) -> bool:
    return any(thread.name == name and thread.is_alive() for thread in threading.enumerate())


def _read_kaggle_secret(name: str) -> Optional[str]:
    try:
        from kaggle_secrets import UserSecretsClient

        value = UserSecretsClient().get_secret(name)
    except Exception:
        return None
    cleaned = str(value or "").strip()
    return cleaned or None


def _value_from_environment_or_kaggle_secret(
    name: str,
    environ: Mapping[str, str],
) -> Optional[str]:
    value = str(environ.get(name, "") or "").strip()
    return value or _read_kaggle_secret(name)


def configure_kaggle_drive_connection(
    workspace: str | Path,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> tuple[bool, str]:
    """Load one-time Kaggle Secrets into the runtime-only Drive connection."""

    if drive_connected(workspace):
        return True, "Google Drive connection is already available in this runtime."

    env = os.environ if environ is None else environ
    client_id = _value_from_environment_or_kaggle_secret(GDRIVE_CLIENT_ID_ENV, env)
    client_secret = _value_from_environment_or_kaggle_secret(GDRIVE_CLIENT_SECRET_ENV, env)
    token_json = _value_from_environment_or_kaggle_secret(GDRIVE_TOKEN_ENV, env)
    if not client_id or not client_secret or not token_json:
        return (
            False,
            "Kaggle local storage is ephemeral. Configure Kaggle Secrets "
            f"{GDRIVE_CLIENT_ID_ENV}, {GDRIVE_CLIENT_SECRET_ENV}, and {GDRIVE_TOKEN_ENV} "
            "once to enable automatic full-workspace restore and backup.",
        )

    try:
        save_drive_connection(
            workspace,
            client_id=client_id,
            client_secret=client_secret,
            token_json=token_json,
        )
    except Exception as exc:
        return False, f"Could not load Kaggle Google Drive persistence secrets: {exc}"
    return True, "Loaded Google Drive persistence credentials from Kaggle Secrets."


@dataclass
class HostedWorkspacePersistence:
    runtime: RuntimeWorkspace
    workspace: Path
    backend: str
    destination: str = DEFAULT_DESTINATION
    persistent_root: Optional[Path] = None
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS
    available: bool = True
    message: str = ""
    externally_managed: bool = False
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: Optional[threading.Thread] = field(default=None, init=False, repr=False)
    _sync_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def remote_path(self) -> str:
        return f"omnivoice_drive:{self.destination}"

    def restore(self) -> None:
        if not self.available or self.externally_managed:
            return
        self.workspace.mkdir(parents=True, exist_ok=True)
        with self._sync_lock:
            if self.backend == "colab-drive":
                if self.persistent_root is None:
                    raise RuntimeError("Colab persistence root is missing")
                _copy_workspace_tree(self.persistent_root, self.workspace, delete=False)
                return
            if self.backend == "google-drive-rclone":
                _run_rclone(self.workspace, ["mkdir", self.remote_path])
                _run_rclone(
                    self.workspace,
                    [
                        "copy",
                        self.remote_path,
                        str(self.workspace),
                        "--create-empty-src-dirs",
                        *_rclone_exclude_args(),
                    ],
                )
                return
            raise RuntimeError(f"Unsupported persistence backend: {self.backend}")

    def sync_now(self) -> None:
        if not self.available or self.externally_managed or self._closed:
            return
        self.workspace.mkdir(parents=True, exist_ok=True)
        with self._sync_lock:
            if self.backend == "colab-drive":
                if self.persistent_root is None:
                    raise RuntimeError("Colab persistence root is missing")
                _copy_workspace_tree(self.workspace, self.persistent_root, delete=True)
                return
            if self.backend == "google-drive-rclone":
                _run_rclone(
                    self.workspace,
                    [
                        "sync",
                        str(self.workspace),
                        self.remote_path,
                        "--create-empty-src-dirs",
                        *_rclone_exclude_args(),
                    ],
                )
                return
            raise RuntimeError(f"Unsupported persistence backend: {self.backend}")

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.sync_now()
            except Exception:
                # Background persistence must never crash TTS generation. The
                # next interval retries; explicit startup/close sync still raises.
                continue

    def start(self) -> None:
        if not self.available or self.externally_managed or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop,
            name=_MIRROR_THREAD_NAME,
            daemon=True,
        )
        self._thread.start()
        atexit.register(self.close)

    def close(self) -> None:
        if self._closed:
            return
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=min(max(self.interval_seconds, 1.0), 5.0))
        if self.available and not self.externally_managed:
            # Do the final sync before marking closed; sync_now intentionally
            # refuses work after _closed becomes true.
            self.sync_now()
        self._closed = True


def prepare_hosted_workspace_persistence(
    runtime: RuntimeWorkspace,
    workspace: str | Path,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> HostedWorkspacePersistence:
    """Restore durable hosted state and start automatic mirroring when possible."""

    env = os.environ if environ is None else environ
    workspace_path = Path(workspace).expanduser()
    mode = str(env.get(PERSISTENCE_MODE_ENV, "auto") or "auto").strip().lower()
    try:
        interval = float(env.get(PERSISTENCE_INTERVAL_ENV, DEFAULT_INTERVAL_SECONDS))
    except (TypeError, ValueError):
        interval = DEFAULT_INTERVAL_SECONDS
    interval = max(5.0, interval)

    if mode in {"off", "disabled", "none"}:
        return HostedWorkspacePersistence(
            runtime=runtime,
            workspace=workspace_path,
            backend="disabled",
            interval_seconds=interval,
            available=False,
            message="Hosted workspace persistence was explicitly disabled.",
        )

    existing_mirror = _thread_running()

    if runtime.environment == "colab":
        persistent_root = Path("/content/drive/MyDrive/OmniVoiceStudio")
        if persistent_root.exists() and persistent_root.resolve() != workspace_path.resolve():
            session = HostedWorkspacePersistence(
                runtime=runtime,
                workspace=workspace_path,
                backend="colab-drive",
                persistent_root=persistent_root,
                interval_seconds=interval,
                externally_managed=existing_mirror,
                message=(
                    "Using mounted Google Drive as the persistent mirror for the complete Studio workspace."
                    if not existing_mirror
                    else "The Colab notebook already owns the Google Drive workspace mirror."
                ),
            )
            if not existing_mirror:
                session.restore()
                session.start()
            return session
        return HostedWorkspacePersistence(
            runtime=runtime,
            workspace=workspace_path,
            backend="none",
            interval_seconds=interval,
            available=False,
            message=(
                "Colab Google Drive is not mounted, so this Studio workspace is ephemeral. "
                "Use the maintained Colab notebook or mount Drive before starting Studio."
            ),
        )

    if runtime.environment == "kaggle":
        connected, detail = configure_kaggle_drive_connection(workspace_path, environ=env)
        if not connected:
            return HostedWorkspacePersistence(
                runtime=runtime,
                workspace=workspace_path,
                backend="none",
                interval_seconds=interval,
                available=False,
                message=detail,
            )
        if not rclone_available():
            try:
                install_rclone_runtime()
            except Exception as exc:
                return HostedWorkspacePersistence(
                    runtime=runtime,
                    workspace=workspace_path,
                    backend="none",
                    interval_seconds=interval,
                    available=False,
                    message=f"Google Drive persistence is configured but rclone install failed: {exc}",
                )
        destination = _normalise_destination(
            str(env.get(GDRIVE_DESTINATION_ENV, DEFAULT_DESTINATION) or DEFAULT_DESTINATION)
        )
        session = HostedWorkspacePersistence(
            runtime=runtime,
            workspace=workspace_path,
            backend="google-drive-rclone",
            destination=destination,
            interval_seconds=interval,
            message=(
                f"Automatic Kaggle full-workspace persistence enabled at Google Drive/{destination}. "
                "Saved voices, projects, queue/jobs, settings and artifacts will be restored and mirrored."
            ),
        )
        session.restore()
        session.start()
        return session

    return HostedWorkspacePersistence(
        runtime=runtime,
        workspace=workspace_path,
        backend="local",
        interval_seconds=interval,
        available=False,
        message="Local runtime workspace is already persistent; no hosted mirror is required.",
    )
