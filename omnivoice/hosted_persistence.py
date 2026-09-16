#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Hosted-runtime persistence policy for the complete Studio workspace.

Colab keeps the existing local-first + mounted Google Drive mirror because the
Drive mount is native to the notebook runtime.

Kaggle deliberately does not run an automatic Google Drive mirror. User state
stays directly under ``/kaggle/working/OmniVoiceStudio`` and is carried between
sessions/VMs by Kaggle's ``Session Persistence -> Files only`` option. Heavy
startup/model caches live outside ``/kaggle/working`` so the Files-only snapshot
stays focused on saved voices, projects, queue/jobs, settings and artifacts.

Manual Google Drive backup remains available from Studio's Storage & Backup UI;
it is not part of the Kaggle startup path.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

from omnivoice.runtime_workspace import RuntimeWorkspace

logger = logging.getLogger(__name__)

PERSISTENCE_INTERVAL_ENV = "OMNIVOICE_PERSISTENCE_INTERVAL_SECONDS"
PERSISTENCE_MODE_ENV = "OMNIVOICE_PERSISTENCE_MODE"
DEFAULT_INTERVAL_SECONDS = 15.0
_MIRROR_THREAD_NAME = "omnivoice-drive-mirror"
_REBASE_JSON_FILES = ("project-queue.json", "jobs.json")

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


def _rebase_hosted_path(value: str, workspace: Path) -> str:
    """Rebase a default hosted workspace path after moving Colab runtime roots."""

    if not value.startswith("/"):
        return value
    marker = "/OmniVoiceStudio"
    index = value.find(marker)
    if index < 0:
        return value
    marker_end = index + len(marker)
    if marker_end < len(value) and value[marker_end] != "/":
        return value
    suffix = value[marker_end:].lstrip("/")
    root = workspace.expanduser().resolve()
    return str(root / suffix) if suffix else str(root)


def _rebase_payload(value: Any, workspace: Path) -> tuple[Any, int]:
    if isinstance(value, str):
        rebased = _rebase_hosted_path(value, workspace)
        return rebased, int(rebased != value)
    if isinstance(value, list):
        changed = 0
        items = []
        for item in value:
            rebased, count = _rebase_payload(item, workspace)
            items.append(rebased)
            changed += count
        return items, changed
    if isinstance(value, dict):
        changed = 0
        payload: dict[str, Any] = {}
        for key, item in value.items():
            rebased, count = _rebase_payload(item, workspace)
            payload[key] = rebased
            changed += count
        return payload, changed
    return value, 0


def _rebase_restored_runtime_state(workspace: Path) -> int:
    """Make restored queue/job absolute paths portable across hosted roots."""

    total = 0
    for filename in _REBASE_JSON_FILES:
        path = workspace / filename
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rebased, changed = _rebase_payload(payload, workspace)
        if not changed:
            continue
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(rebased, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)
        total += changed
    return total


def _thread_running(name: str = _MIRROR_THREAD_NAME) -> bool:
    return any(thread.name == name and thread.is_alive() for thread in threading.enumerate())


def _under_kaggle_working(path: Path) -> bool:
    try:
        path.resolve().relative_to(Path("/kaggle/working").resolve())
        return True
    except (OSError, ValueError):
        return False


@dataclass
class HostedWorkspacePersistence:
    runtime: RuntimeWorkspace
    workspace: Path
    backend: str
    persistent_root: Optional[Path] = None
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS
    available: bool = True
    message: str = ""
    externally_managed: bool = False
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: Optional[threading.Thread] = field(default=None, init=False, repr=False)
    _sync_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def restore(self) -> None:
        if not self.available or self.externally_managed:
            return
        self.workspace.mkdir(parents=True, exist_ok=True)
        with self._sync_lock:
            if self.backend != "colab-drive":
                raise RuntimeError(f"Unsupported persistence backend: {self.backend}")
            if self.persistent_root is None:
                raise RuntimeError("Colab persistence root is missing")
            _copy_workspace_tree(self.persistent_root, self.workspace, delete=False)
            rebased = _rebase_restored_runtime_state(self.workspace)
            if rebased:
                self.message += f" Rebased {rebased} restored queue/job path value(s) to this runtime."

    def sync_now(self) -> None:
        if not self.available or self.externally_managed or self._closed:
            return
        self.workspace.mkdir(parents=True, exist_ok=True)
        with self._sync_lock:
            if self.backend != "colab-drive":
                raise RuntimeError(f"Unsupported persistence backend: {self.backend}")
            if self.persistent_root is None:
                raise RuntimeError("Colab persistence root is missing")
            _copy_workspace_tree(self.workspace, self.persistent_root, delete=True)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.sync_now()
            except Exception as exc:
                logger.warning(
                    "Hosted workspace background sync failed; retrying next interval: %s: %s",
                    type(exc).__name__,
                    exc,
                )

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
            self.sync_now()
        self._closed = True


def prepare_hosted_workspace_persistence(
    runtime: RuntimeWorkspace,
    workspace: str | Path,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> HostedWorkspacePersistence:
    """Prepare the platform-native Studio persistence contract."""

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
        if persistent_root.exists():
            if persistent_root.resolve() == workspace_path.resolve():
                return HostedWorkspacePersistence(
                    runtime=runtime,
                    workspace=workspace_path,
                    backend="colab-drive-direct",
                    interval_seconds=interval,
                    available=False,
                    message="Studio workspace is already located on mounted Google Drive; no mirror is required.",
                )
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
        workspace_path.mkdir(parents=True, exist_ok=True)
        if _under_kaggle_working(workspace_path):
            message = (
                "Using Kaggle /kaggle/working directly for Studio state. Enable Kaggle "
                "Session Persistence -> Files only to keep saved voices, projects, queue/jobs, "
                "settings and artifacts across sessions/VMs. Heavy startup/model caches are kept "
                "under /tmp, so they are not part of the Files-only snapshot. Automatic Google "
                "Drive mirroring is disabled; Storage & Backup remains available for manual backup."
            )
        else:
            message = (
                f"Kaggle custom workspace {workspace_path} is outside /kaggle/working and will not "
                "be carried by Session Persistence -> Files only. Move OMNIVOICE_STUDIO_HOME under "
                "/kaggle/working to persist saved voices and projects without external storage."
            )
        return HostedWorkspacePersistence(
            runtime=runtime,
            workspace=workspace_path,
            backend="kaggle-files",
            interval_seconds=interval,
            available=False,
            message=message,
        )

    return HostedWorkspacePersistence(
        runtime=runtime,
        workspace=workspace_path,
        backend="local",
        interval_seconds=interval,
        available=False,
        message="Local runtime workspace is already persistent; no hosted mirror is required.",
    )
