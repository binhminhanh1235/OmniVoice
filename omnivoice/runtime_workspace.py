#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Runtime-local execution workspace selection.

This module intentionally models only *execution* storage. Persistent/remote
storage (Google Drive, rclone, object storage, etc.) is a separate concern and
must not leak into Project/Queue generation paths.

For Kaggle the execution workspace is always local SSD under
``/kaggle/working``. ``/kaggle/input`` is treated as read-only source material,
never as a writable Project Studio workspace.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional


@dataclass(frozen=True)
class RuntimeWorkspace:
    environment: str
    root: Path
    ephemeral: bool
    input_root: Optional[Path] = None
    persistence_backend: str = "none"
    notes: tuple[str, ...] = ()

    def summary(self) -> str:
        persistence = self.persistence_backend.upper()
        return (
            f"environment={self.environment} · root={self.root} · "
            f"ephemeral={'yes' if self.ephemeral else 'no'} · persistence={persistence}"
        )


def _default_exists(path: Path) -> bool:
    return path.exists()


def detect_runtime_environment(
    *,
    environ: Optional[Mapping[str, str]] = None,
    path_exists: Callable[[Path], bool] = _default_exists,
) -> str:
    """Return ``kaggle``, ``colab`` or ``local`` without importing platform SDKs."""

    env = os.environ if environ is None else environ

    if env.get("KAGGLE_KERNEL_RUN_TYPE") or env.get("KAGGLE_URL_BASE"):
        return "kaggle"
    if path_exists(Path("/kaggle/working")):
        return "kaggle"

    if env.get("COLAB_RELEASE_TAG") or env.get("COLAB_GPU"):
        return "colab"
    if path_exists(Path("/content")):
        return "colab"

    return "local"


def detect_runtime_workspace(
    *,
    environ: Optional[Mapping[str, str]] = None,
    path_exists: Callable[[Path], bool] = _default_exists,
    cwd: Optional[Path] = None,
) -> RuntimeWorkspace:
    """Resolve the execution workspace for the current runtime.

    ``OMNIVOICE_STUDIO_HOME`` always wins. This keeps automation/tests and
    advanced users deterministic while still giving Kaggle a zero-config local
    SSD default.
    """

    env = os.environ if environ is None else environ
    configured = env.get("OMNIVOICE_STUDIO_HOME")
    environment = detect_runtime_environment(environ=env, path_exists=path_exists)

    if configured:
        root = Path(configured).expanduser()
        return RuntimeWorkspace(
            environment=environment,
            root=root,
            ephemeral=(environment in {"kaggle", "colab"}),
            input_root=(Path("/kaggle/input") if environment == "kaggle" else None),
            notes=("Workspace overridden by OMNIVOICE_STUDIO_HOME.",),
        )

    if environment == "kaggle":
        return RuntimeWorkspace(
            environment="kaggle",
            root=Path("/kaggle/working/OmniVoiceStudio"),
            ephemeral=True,
            input_root=Path("/kaggle/input"),
            persistence_backend="none",
            notes=(
                "Using Kaggle local SSD for all Project Studio writes.",
                "This workspace is ephemeral and is lost when the Kaggle session is discarded.",
                "/kaggle/input is read-only and should only be used as an import source.",
            ),
        )

    if environment == "colab":
        drive = Path("/content/drive/MyDrive")
        if path_exists(drive):
            return RuntimeWorkspace(
                environment="colab",
                root=drive / "OmniVoiceStudio",
                ephemeral=False,
                persistence_backend="google-drive-mounted",
                notes=("Using the existing mounted Colab Google Drive workspace.",),
            )
        return RuntimeWorkspace(
            environment="colab",
            root=Path("/content/OmniVoiceStudio"),
            ephemeral=True,
            persistence_backend="none",
            notes=("Google Drive is not mounted; using Colab local runtime storage.",),
        )

    root = (cwd or Path.cwd()) / "OmniVoiceStudio"
    return RuntimeWorkspace(
        environment="local",
        root=root,
        ephemeral=False,
        persistence_backend="none",
        notes=("Using local filesystem execution workspace.",),
    )


def default_execution_workspace(**kwargs) -> Path:
    return detect_runtime_workspace(**kwargs).root


def ensure_runtime_workspace(info: RuntimeWorkspace) -> RuntimeWorkspace:
    """Create the writable execution tree without touching any remote storage."""

    info.root.mkdir(parents=True, exist_ok=True)
    for name in ("projects", "voices"):
        (info.root / name).mkdir(parents=True, exist_ok=True)
    return info
