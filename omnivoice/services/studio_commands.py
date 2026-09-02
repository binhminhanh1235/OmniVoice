#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Write-capable application commands executed by the Studio Job Manager.

Protocol adapters (REST/MCP/CLI) submit durable jobs. This service owns the
actual Project Studio command semantics and deliberately renders one section at
a time so cancellation and progress checkpoints occur only at safe boundaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from omnivoice.project_status import summarize_project
from omnivoice.section_status import incomplete_section_ids
from omnivoice.services.job_manager import JobContext


class StudioCommandService:
    """Protocol-neutral write commands for OmniVoice Studio."""

    def __init__(
        self,
        model: Any,
        workspace: str | Path,
        *,
        controller: Optional[Any] = None,
    ) -> None:
        self.model = model
        self.workspace = Path(workspace).expanduser().resolve()
        self.projects_root = (self.workspace / "projects").resolve()
        if controller is None:
            # Temporary adapter around the mature Project Studio controller.
            # Keeping this import here prevents REST/MCP layers from depending
            # directly on Gradio callbacks while the controller is moved into a
            # dedicated application module in a later refactor.
            from omnivoice.cli.project_studio_quality import (
                QualityPresetProjectStudioController,
            )

            controller = QualityPresetProjectStudioController(model, self.workspace)
        self.controller = controller

    @staticmethod
    def _normalized_sections(project: Any, requested: Optional[list[str]]) -> list[str]:
        available = [section.id for section in project.manifest.sections]
        if requested is None:
            return available
        selected = [str(item).strip().upper() for item in requested if str(item).strip()]
        unknown = sorted(set(selected) - set(available))
        if unknown:
            raise ValueError("Unknown sections: " + ", ".join(unknown))
        selected_set = set(selected)
        return [section_id for section_id in available if section_id in selected_set]

    def _validated_project_path(self, value: Any) -> Path:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("project_path is required")
        project_path = Path(raw).expanduser().resolve()
        if project_path.parent != self.projects_root:
            raise ValueError("project_path must be a direct child of the Studio projects directory")
        if not (project_path / "project.json").exists():
            raise ValueError("project_path does not contain a Studio project")
        return project_path

    def generate_project_job(self, ctx: JobContext) -> dict[str, Any]:
        payload = ctx.payload
        project_path = self._validated_project_path(payload.get("project_path"))

        project = self.controller.load_project(project_path)
        settings = self.controller.load_project_settings(project)

        voice_name = str(
            payload.get("voice_name") or settings.get("voice_name") or ""
        ).strip()
        if not voice_name:
            raise ValueError(
                "Project has no saved voice. Supply voice_name or save a voice in Studio first."
            )
        voice_variant = str(
            payload.get("voice_variant") or settings.get("voice_variant") or "AUTO"
        ).strip().upper()
        language_value = payload.get("language")
        language = (
            str(language_value)
            if language_value is not None
            else str(settings.get("language") or "en")
        )
        quality_preset = payload.get("quality_preset")
        if quality_preset is None:
            quality_preset = settings.get("quality_preset")
        quality_preset = str(quality_preset).upper() if quality_preset else None

        resume = bool(payload.get("resume", True))
        strict = bool(payload.get("strict", False))
        requested = self._normalized_sections(project, payload.get("sections"))
        targets = incomplete_section_ids(project, requested) if resume else requested

        total = len(targets)
        if total == 0:
            summary = summarize_project(project.root)
            ctx.emit(
                "No sections require generation.",
                progress=1.0,
                event="project.skipped",
                data={"project_id": project.root.name},
            )
            return {
                "project_id": project.root.name,
                "project_title": project.manifest.title,
                "project_status": summary.status,
                "generated_sections": [],
                "skipped": True,
            }

        generated: list[dict[str, str]] = []
        ctx.emit(
            f"Starting {project.manifest.title}: {total} section(s) to generate.",
            progress=0.0,
            event="project.started",
            data={
                "project_id": project.root.name,
                "sections": targets,
                "quality_preset": quality_preset,
            },
        )

        for index, section_id in enumerate(targets, start=1):
            # Safe cooperative cancellation boundary. Never interrupt model
            # inference in the middle of a section.
            ctx.checkpoint()
            ctx.emit(
                f"Generating {section_id} ({index}/{total}).",
                progress=(index - 1) / total,
                event="section.started",
                data={
                    "project_id": project.root.name,
                    "section_id": section_id,
                    "index": index,
                    "total": total,
                },
            )

            self.controller.generate(
                project.root,
                voice_name=voice_name,
                voice_variant=voice_variant,
                language=language,
                section_ids=[section_id],
                resume=resume,
                strict=strict,
                quality_preset=quality_preset,
            )

            project = self.controller.load_project(project.root)
            section = project.get_section(section_id)
            generated.append({"section_id": section_id, "status": section.status})
            ctx.emit(
                f"Finished {section_id}: {section.status}.",
                progress=index / total,
                event="section.finished",
                data={
                    "project_id": project.root.name,
                    "section_id": section_id,
                    "status": section.status,
                    "index": index,
                    "total": total,
                },
            )

        summary = summarize_project(project.root)
        ctx.emit(
            f"Project generation finished with status {summary.status}.",
            progress=1.0,
            event="project.finished",
            data={
                "project_id": project.root.name,
                "project_status": summary.status,
                "completed_sections": summary.completed_sections,
                "total_sections": summary.total_sections,
            },
        )
        return {
            "project_id": project.root.name,
            "project_title": project.manifest.title,
            "project_status": summary.status,
            "generated_sections": generated,
            "completed_sections": summary.completed_sections,
            "total_sections": summary.total_sections,
            "skipped": False,
        }
