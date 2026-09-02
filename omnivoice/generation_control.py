#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Persistent cooperative pause control for Project Studio generation."""

from __future__ import annotations

import json
from pathlib import Path


CONTROL_FILE = "generation-control.json"


def _control_path(project_path: str | Path) -> Path:
    return Path(project_path).expanduser() / CONTROL_FILE


def _write(project_path: str | Path, pause_requested: bool) -> Path:
    path = _control_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps({"pause_requested": bool(pause_requested)}, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)
    return path


def request_pause(project_path: str | Path) -> Path:
    """Request a safe pause at the next generation checkpoint."""

    return _write(project_path, True)


def clear_pause(project_path: str | Path) -> Path:
    """Clear an earlier pause request before resuming generation."""

    return _write(project_path, False)


def pause_requested(project_path: str | Path) -> bool:
    """Return whether the project currently requests a cooperative pause."""

    path = _control_path(project_path)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(payload.get("pause_requested", False))
