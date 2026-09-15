#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Write-capable application commands executed by the Studio Job Manager.

Protocol adapters (REST/MCP/CLI) submit durable jobs. This service owns the
actual Studio command semantics and keeps all GPU-bound mutations behind one
single-worker job lifecycle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import soundfile as sf

from omnivoice.artifacts import ArtifactCatalog
from omnivoice.preview import generate_project_previews
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
        self.artifacts = ArtifactCatalog(self.workspace)
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

    def _project_generation_options(
        self,
        project: Any,
        payload: dict[str, Any],
    ) -> tuple[str, str, str, Optional[str], bool]:
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
        strict = bool(payload.get("strict", False))
        return voice_name, voice_variant, language, quality_preset, strict

    @staticmethod
    def _write_sidecar(path: Path, payload: dict[str, Any]) -> Path:
        sidecar = path.with_suffix(".json")
        temp = sidecar.with_suffix(sidecar.suffix + ".tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(sidecar)
        return sidecar

    def _generate_standalone_audio(
        self,
        ctx: JobContext,
        *,
        preview: bool,
    ) -> dict[str, Any]:
        payload = ctx.payload
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")

        voice_name = str(payload.get("voice_name") or "").strip() or None
        voice_variant = str(payload.get("voice_variant") or "AUTO").strip().upper()
        style = str(payload.get("style") or "DEFAULT").strip().upper()
        language = payload.get("language")
        language = str(language) if language is not None else "en"
        instruct = str(payload.get("instruct") or "").strip() or None
        speed_value = payload.get("speed")
        speed = float(speed_value) if speed_value is not None else None
        requested_quality = payload.get("quality_preset")
        if requested_quality is None:
            requested_quality = "FAST" if preview else self.controller.workspace_quality_preset()
        quality_preset = str(requested_quality).strip().upper()

        resolution = None
        voice_prompt = None
        if voice_name:
            resolution = self.controller.voices.resolve_prompt(
                voice_name,
                style=style,
                preferred_variant=voice_variant,
            )
            voice_prompt = resolution.prompt

        ctx.emit(
            "Generating preview audio." if preview else "Generating standalone audio.",
            progress=0.05,
            event="audio.started",
            data={
                "preview": preview,
                "voice_name": voice_name,
                "quality_preset": quality_preset,
            },
        )
        ctx.checkpoint()

        generation_config = self.controller.generation_config(quality_preset)
        audios = self.model.generate(
            text=text,
            language=language,
            voice_clone_prompt=voice_prompt,
            instruct=instruct,
            speed=speed,
            generation_config=generation_config,
        )
        if not audios:
            raise RuntimeError("OmniVoice returned no audio")

        category = "previews" if preview else "audio"
        output_dir = self.workspace / "artifacts" / category
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{ctx.job_id}.wav"
        sf.write(
            output_path,
            audios[0],
            int(self.model.sampling_rate),
            subtype="PCM_16",
        )
        sidecar = self._write_sidecar(
            output_path,
            {
                "job_id": ctx.job_id,
                "kind": "preview_audio" if preview else "generated_audio",
                "text": text,
                "language": language,
                "voice_name": resolution.voice_name if resolution else None,
                "voice_variant": resolution.variant if resolution else None,
                "voice_variant_fallback": resolution.used_fallback if resolution else False,
                "quality_preset": quality_preset,
                "style": style,
                "instruct": instruct,
                "speed": speed,
            },
        )
        artifact = self.artifacts.describe(
            output_path,
            kind="preview_audio" if preview else "generated_audio",
        )
        ctx.emit(
            "Preview audio ready." if preview else "Standalone audio ready.",
            progress=1.0,
            event="audio.finished",
            data={"artifact_id": artifact["id"]},
        )
        return {
            "artifact": artifact,
            "metadata_file": str(sidecar),
            "voice_name": resolution.voice_name if resolution else None,
            "voice_variant": resolution.variant if resolution else None,
            "quality_preset": quality_preset,
            "preview": preview,
        }

    def generate_audio_job(self, ctx: JobContext) -> dict[str, Any]:
        """Generate one independent WAV without creating or mutating a project."""

        return self._generate_standalone_audio(ctx, preview=False)

    def preview_audio_job(self, ctx: JobContext) -> dict[str, Any]:
        """Generate a direct short preview or non-destructive project previews."""

        payload = ctx.payload
        if str(payload.get("text") or "").strip():
            return self._generate_standalone_audio(ctx, preview=True)

        project_path = self._validated_project_path(payload.get("project_path"))
        project = self.controller.load_project(project_path)
        voice_name, voice_variant, language, quality_preset, strict = (
            self._project_generation_options(project, payload)
        )
        selected_preset = quality_preset or self.controller.project_quality_preset(project)[0]
        labels = payload.get("labels") or ["opening", "middle", "ending"]
        labels = [str(value).strip().lower() for value in labels if str(value).strip()]
        if not labels:
            labels = ["opening", "middle", "ending"]

        results = []
        total = len(labels)
        for index, label in enumerate(labels, start=1):
            ctx.checkpoint()
            ctx.emit(
                f"Generating project preview {label} ({index}/{total}).",
                progress=(index - 1) / total,
                event="preview.started",
                data={"project_id": project.root.name, "label": label},
            )
            generated = generate_project_previews(
                project,
                self.model,
                self.controller.voices,
                voice_name=voice_name,
                preferred_variant=voice_variant,
                robust_config=self.controller.robust_config(
                    strict=strict,
                    quality_preset=selected_preset,
                ),
                generation_config=self.controller.generation_config(selected_preset),
                labels=[label],
                language=language,
                strict=strict,
            )
            results.extend(generated)
            ctx.emit(
                f"Finished project preview {label}.",
                progress=index / total,
                event="preview.finished",
                data={"project_id": project.root.name, "label": label},
            )

        artifacts = []
        for result in results:
            artifacts.append(
                self.artifacts.describe(
                    result.audio_file,
                    project_id=project.root.name,
                    kind="preview_audio",
                )
            )
        return {
            "project_id": project.root.name,
            "artifacts": artifacts,
            "preview_count": len(artifacts),
            "quality_preset": selected_preset,
        }

    def generate_project_job(self, ctx: JobContext) -> dict[str, Any]:
        payload = ctx.payload
        project_path = self._validated_project_path(payload.get("project_path"))

        project = self.controller.load_project(project_path)
        voice_name, voice_variant, language, quality_preset, strict = (
            self._project_generation_options(project, payload)
        )

        resume = bool(payload.get("resume", True))
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

    def regenerate_section_job(self, ctx: JobContext) -> dict[str, Any]:
        payload = ctx.payload
        project_path = self._validated_project_path(payload.get("project_path"))
        project = self.controller.load_project(project_path)
        section_id = str(payload.get("section_id") or "").strip().upper()
        if not section_id:
            raise ValueError("section_id is required")
        project.get_section(section_id)
        voice_name, voice_variant, language, quality_preset, strict = (
            self._project_generation_options(project, payload)
        )

        ctx.emit(
            f"Regenerating {section_id}.",
            progress=0.0,
            event="section.regeneration.started",
            data={"project_id": project.root.name, "section_id": section_id},
        )
        ctx.checkpoint()
        self.controller.generate(
            project.root,
            voice_name=voice_name,
            voice_variant=voice_variant,
            language=language,
            section_ids=[section_id],
            resume=False,
            strict=strict,
            quality_preset=quality_preset,
        )
        project = self.controller.load_project(project.root)
        section = project.get_section(section_id)
        artifacts = [
            item
            for item in self.artifacts.list(project_id=project.root.name)
            if item.get("section_id") == section_id
        ]
        ctx.emit(
            f"Regenerated {section_id}: {section.status}.",
            progress=1.0,
            event="section.regeneration.finished",
            data={"project_id": project.root.name, "section_id": section_id},
        )
        return {
            "project_id": project.root.name,
            "section_id": section_id,
            "status": section.status,
            "artifacts": artifacts,
        }

    def regenerate_chunk_job(self, ctx: JobContext) -> dict[str, Any]:
        payload = ctx.payload
        project_path = self._validated_project_path(payload.get("project_path"))
        project = self.controller.load_project(project_path)
        section_id = str(payload.get("section_id") or "").strip().upper()
        chunk_id = str(payload.get("chunk_id") or "").strip()
        if not section_id or not chunk_id:
            raise ValueError("section_id and chunk_id are required")
        project.get_chunk(section_id, chunk_id)
        voice_name, voice_variant, language, quality_preset, strict = (
            self._project_generation_options(project, payload)
        )

        ctx.emit(
            f"Regenerating {section_id}/{chunk_id}.",
            progress=0.0,
            event="chunk.regeneration.started",
            data={
                "project_id": project.root.name,
                "section_id": section_id,
                "chunk_id": chunk_id,
            },
        )
        ctx.checkpoint()
        self.controller.regenerate_chunk(
            project.root,
            f"{section_id}/{chunk_id}",
            voice_name=voice_name,
            voice_variant=voice_variant,
            language=language,
            strict=strict,
            quality_preset=quality_preset,
        )
        project = self.controller.load_project(project.root)
        chunk = project.get_chunk(section_id, chunk_id)
        artifacts = [
            item
            for item in self.artifacts.list(project_id=project.root.name)
            if item.get("section_id") == section_id
            and (
                item.get("chunk_id") == chunk_id
                or item.get("kind") in {"section_audio", "beat_audio"}
            )
        ]
        ctx.emit(
            f"Regenerated {section_id}/{chunk_id}: {chunk.status}.",
            progress=1.0,
            event="chunk.regeneration.finished",
            data={
                "project_id": project.root.name,
                "section_id": section_id,
                "chunk_id": chunk_id,
            },
        )
        return {
            "project_id": project.root.name,
            "section_id": section_id,
            "chunk_id": chunk_id,
            "status": chunk.status,
            "artifacts": artifacts,
        }
