#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Application-facing OmniVoice Studio service.

This module is deliberately UI/protocol agnostic. Gradio, REST and MCP should
call this service layer rather than reaching directly into Gradio callbacks.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Optional

from omnivoice.hardware_quality import detect_hardware, quality_preset_rows
from omnivoice.project_queue import ProjectQueueStore
from omnivoice.project_status import (
    PROJECT_STATUSES,
    filter_project_statuses,
    scan_project_statuses,
    summarize_project,
)
from omnivoice.runtime_workspace import (
    RuntimeWorkspace,
    detect_runtime_environment,
    detect_runtime_workspace,
)


class StudioService:
    """Protocol-neutral facade over Studio runtime/project/queue metadata."""

    def __init__(
        self,
        model: Any,
        workspace: str | Path,
        *,
        runtime: Optional[RuntimeWorkspace] = None,
    ) -> None:
        self.model = model
        self.workspace = Path(workspace).expanduser().resolve()
        self.projects_root = self.workspace / "projects"
        self.voices_root = self.workspace / "voices"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.voices_root.mkdir(parents=True, exist_ok=True)

        if runtime is None:
            detected = detect_runtime_workspace()
            runtime = RuntimeWorkspace(
                environment=detected.environment,
                root=self.workspace,
                ephemeral=detected.ephemeral,
                input_root=detected.input_root,
                persistence_backend=detected.persistence_backend,
                notes=detected.notes,
            )
        self.runtime = runtime
        self.queue_store = ProjectQueueStore(self.workspace)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "omnivoice-studio",
            "model_loaded": self.model is not None,
            "runtime": self.runtime.environment,
            "workspace": str(self.workspace),
            "ephemeral": self.runtime.ephemeral,
            "persistence_backend": self.runtime.persistence_backend,
        }

    def hardware(self) -> dict[str, Any]:
        hardware = detect_hardware()
        payload = asdict(hardware)
        payload["compute_capability_text"] = hardware.compute_capability_text
        payload["summary"] = hardware.summary()
        return payload

    def capabilities(self) -> dict[str, Any]:
        return {
            "service": "omnivoice-studio",
            "api_version": "v1",
            "runtime": {
                "environment": self.runtime.environment,
                "workspace": str(self.workspace),
                "ephemeral": self.runtime.ephemeral,
                "input_root": str(self.runtime.input_root) if self.runtime.input_root else None,
                "persistence_backend": self.runtime.persistence_backend,
                "notes": list(self.runtime.notes),
            },
            "features": {
                "web_ui": True,
                "rest_api": True,
                "mcp": False,
                "project_queue": True,
                "section_resume": True,
                "voice_library": True,
                "voice_doctor": True,
                "voice_stability": True,
                "hardware_quality_presets": True,
            },
            "project_statuses": list(PROJECT_STATUSES),
            "quality_presets": quality_preset_rows(),
            "endpoints": {
                "ui": "/ui",
                "api": "/api/v1",
                "health": "/health",
                "openapi": "/docs",
                "mcp": None,
            },
        }

    def _project_payload(self, summary) -> dict[str, Any]:
        root = Path(summary.path)
        return {
            "id": root.name,
            "title": summary.title,
            "status": summary.status,
            "completed_sections": summary.completed_sections,
            "total_sections": summary.total_sections,
            "progress": summary.progress,
            "current_sections": list(summary.current_sections),
            "updated_at": summary.updated_at,
            "path": summary.path,
        }

    def list_projects(
        self,
        statuses: Optional[Iterable[str]] = None,
    ) -> list[dict[str, Any]]:
        summaries = scan_project_statuses(self.projects_root)
        if statuses:
            selected = [str(value).upper() for value in statuses if str(value).strip()]
            unknown = sorted(set(selected) - set(PROJECT_STATUSES))
            if unknown:
                raise ValueError(
                    "Unknown project status: " + ", ".join(unknown)
                )
            summaries = filter_project_statuses(summaries, selected)
        return [self._project_payload(item) for item in summaries]

    def _resolve_project_root(self, project_id: str) -> Path:
        project_id = str(project_id or "").strip()
        if not project_id or Path(project_id).name != project_id or project_id in {".", ".."}:
            raise ValueError("Invalid project id")
        root = (self.projects_root / project_id).resolve()
        if root.parent != self.projects_root.resolve():
            raise ValueError("Invalid project id")
        if not (root / "project.json").exists():
            raise KeyError(project_id)
        return root

    def get_project(self, project_id: str) -> dict[str, Any]:
        root = self._resolve_project_root(project_id)
        summary = summarize_project(root)
        return self._project_payload(summary)

    def queue_summary(self) -> dict[str, Any]:
        manifest = self.queue_store.load()
        items = []
        for item in manifest.items:
            items.append(
                {
                    "id": item.id,
                    "project_id": Path(item.project_path).name,
                    "project_title": item.project_title,
                    "status": item.status.upper(),
                    "current_section": item.current_section,
                    "completed_sections": item.completed_sections,
                    "total_sections": item.total_sections,
                    "voice_name": item.voice_name,
                    "voice_variant": item.voice_variant,
                    "language": item.language,
                    "quality_preset": getattr(item, "quality_preset", None),
                    "auto_merge": item.auto_merge,
                    "error": item.error,
                }
            )
        return {
            "paused": manifest.paused,
            "updated_at": manifest.updated_at,
            "items": items,
        }
