#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Optional runtime-local rclone installer for hosted notebook sessions."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional


def _runtime_bin_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "omnivoice-rclone" / "bin"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _architecture() -> str:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "amd64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    raise RuntimeError(f"Unsupported architecture for automatic rclone install: {machine}")


def _prepend_runtime_path(path: Path) -> None:
    current = os.environ.get("PATH", "")
    entries = current.split(os.pathsep) if current else []
    value = str(path)
    if value not in entries:
        os.environ["PATH"] = value + (os.pathsep + current if current else "")


def install_rclone_runtime(
    *,
    download_url: Optional[str] = None,
) -> tuple[Path, str]:
    """Install rclone into the current runtime's temporary directory.

    This is opt-in and never modifies the repository or Studio workspace. If a
    system rclone already exists, it is reused.
    """

    existing = shutil.which("rclone")
    if existing:
        completed = subprocess.run(
            [existing, "version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        version = (completed.stdout or completed.stderr or "rclone available").splitlines()[0]
        return Path(existing), version

    arch = _architecture()
    url = download_url or f"https://downloads.rclone.org/rclone-current-linux-{arch}.zip"
    bin_dir = _runtime_bin_dir()
    target = bin_dir / "rclone"

    with tempfile.TemporaryDirectory(prefix="omnivoice-rclone-install-") as temp_dir:
        archive_path = Path(temp_dir) / "rclone.zip"
        with urllib.request.urlopen(url, timeout=60) as response, archive_path.open("wb") as output:
            shutil.copyfileobj(response, output)

        with zipfile.ZipFile(archive_path) as archive:
            candidates = [
                name
                for name in archive.namelist()
                if not name.endswith("/") and Path(name).name == "rclone"
            ]
            if len(candidates) != 1:
                raise RuntimeError("Could not find a unique rclone binary in downloaded archive")
            temp_target = target.with_suffix(".tmp")
            temp_target.unlink(missing_ok=True)
            with archive.open(candidates[0]) as source, temp_target.open("wb") as output:
                shutil.copyfileobj(source, output)
            temp_target.chmod(0o755)
            temp_target.replace(target)

    _prepend_runtime_path(bin_dir)
    completed = subprocess.run(
        [str(target), "version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if completed.returncode != 0:
        target.unlink(missing_ok=True)
        raise RuntimeError(
            "Installed rclone could not start: "
            + (completed.stderr or completed.stdout or f"exit code {completed.returncode}").strip()
        )
    version = (completed.stdout or completed.stderr or "rclone installed").splitlines()[0]
    return target, version
