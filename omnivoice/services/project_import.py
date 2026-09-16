#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Protocol-neutral synchronous import of native OmniVoice narration projects."""

from __future__ import annotations

import errno
import shutil
import tempfile
from pathlib import Path
from typing import Any

from omnivoice.project import OmniVoiceProject
from omnivoice.project_narration import create_narration_project
from omnivoice.project_status import summarize_project


class ProjectImportConflict(ValueError):
    """The requested project id is already occupied by different source/options."""


class StudioProjectImportService:
    """Create/import Studio projects without involving the GPU job manager."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.projects_root = (self.workspace / "projects").resolve()
        self.staging_root = (self.workspace / ".project-import-staging").resolve()
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.staging_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _project_id(value: Any) -> str:
        project_id = str(value or "").strip()
        if (
            not project_id
            or project_id in {".", ".."}
            or "/" in project_id
            or "\\" in project_id
            or Path(project_id).name != project_id
        ):
            raise ValueError("Invalid project id")
        return project_id

    def _destination(self, project_id: str) -> Path:
        destination = (self.projects_root / project_id).resolve()
        if destination.parent != self.projects_root:
            raise ValueError("Invalid project id")
        return destination

    @staticmethod
    def _same_import(
        existing: OmniVoiceProject,
        candidate: OmniVoiceProject,
    ) -> bool:
        return (
            existing.manifest.source_hash == candidate.manifest.source_hash
            and existing.manifest.max_chunk_words
            == candidate.manifest.max_chunk_words
            and existing.manifest.max_chunk_chars
            == candidate.manifest.max_chunk_chars
        )

    @staticmethod
    def _payload(project: OmniVoiceProject, *, created: bool) -> dict[str, Any]:
        summary = summarize_project(project.root)
        return {
            "project_id": project.root.name,
            "title": project.manifest.title,
            "created": created,
            "source_hash": project.manifest.source_hash,
            "status": summary.status,
            "sections": [
                {
                    "id": section.id,
                    "start_time": section.start_time,
                    "end_time": section.end_time,
                    "title": section.title,
                }
                for section in project.manifest.sections
            ],
        }

    def _existing_result(
        self,
        destination: Path,
        candidate: OmniVoiceProject,
    ) -> dict[str, Any]:
        manifest_path = destination / OmniVoiceProject.MANIFEST_NAME
        if not manifest_path.exists():
            raise ProjectImportConflict(
                "Project destination already exists but is not a valid Studio project"
            )
        existing = OmniVoiceProject.load(destination)
        if not self._same_import(existing, candidate):
            raise ProjectImportConflict("Project already exists with different source")
        return self._payload(existing, created=False)

    def import_project(
        self,
        *,
        project_id: str,
        script: str,
        speak_section_titles: bool = False,
        max_chunk_words: int = 24,
        max_chunk_chars: int = 220,
    ) -> dict[str, Any]:
        """Parse, persist, and atomically publish one native narration project."""

        project_id = self._project_id(project_id)
        destination = self._destination(project_id)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f"{project_id}.",
                dir=str(self.staging_root),
            )
        )
        candidate: OmniVoiceProject | None = None
        try:
            candidate = create_narration_project(
                script,
                staging,
                max_chunk_words=max_chunk_words,
                max_chunk_chars=max_chunk_chars,
                speak_section_titles=speak_section_titles,
                overwrite=False,
            )

            if destination.exists():
                return self._existing_result(destination, candidate)

            try:
                staging.rename(destination)
            except OSError as exc:
                if destination.exists() and exc.errno in {
                    errno.EEXIST,
                    errno.ENOTEMPTY,
                    errno.EACCES,
                    errno.EPERM,
                }:
                    return self._existing_result(destination, candidate)
                raise

            candidate = OmniVoiceProject.load(destination)
            return self._payload(candidate, created=True)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
