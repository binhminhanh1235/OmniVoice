#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Read-only catalog of generated OmniVoice Studio audio artifacts.

The catalog is intentionally derived from durable workspace files instead of a
second database. Project chunk/beat/section audio, merged project audio,
project previews, and standalone AI-native audio jobs all become discoverable
through one stable schema. Historical section snapshots are excluded so agents
see only currently selected project artifacts.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable, Optional

import soundfile as sf


class ArtifactCatalog:
    """Discover current generated WAV files below one Studio workspace."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.projects_root = (self.workspace / "projects").resolve()
        self.standalone_root = (self.workspace / "artifacts").resolve()
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.standalone_root.mkdir(parents=True, exist_ok=True)

    def _project_root(self, project_id: str) -> Path:
        value = str(project_id or "").strip()
        if not value or Path(value).name != value or value in {".", ".."}:
            raise ValueError("Invalid project id")
        root = (self.projects_root / value).resolve()
        if root.parent != self.projects_root:
            raise ValueError("Invalid project id")
        if not (root / "project.json").exists():
            raise KeyError(value)
        return root

    @staticmethod
    def _artifact_id(relative_path: str) -> str:
        digest = hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]
        return f"art_{digest}"

    def _classify_project_path(
        self,
        project_root: Path,
        path: Path,
    ) -> tuple[str, Optional[str], Optional[str]]:
        relative = path.relative_to(project_root)
        parts = relative.parts
        if parts and parts[0] == "previews":
            return "preview_audio", None, None
        if len(parts) >= 2 and parts[0] == "output":
            return "project_audio", None, None
        if len(parts) >= 3 and parts[0] == "sections":
            section_id = parts[1]
            if "chunks" in parts:
                return "chunk_audio", section_id, path.stem
            if "beats" in parts:
                return "beat_audio", section_id, path.stem
            return "section_audio", section_id, None
        return "project_audio", None, None

    def _classify_standalone_path(self, path: Path) -> str:
        relative = path.relative_to(self.standalone_root)
        if relative.parts and relative.parts[0] == "previews":
            return "preview_audio"
        return "generated_audio"

    def describe(
        self,
        path: str | Path,
        *,
        project_id: Optional[str] = None,
        kind: Optional[str] = None,
        section_id: Optional[str] = None,
        chunk_id: Optional[str] = None,
    ) -> dict[str, Any]:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file() or not resolved.is_relative_to(self.workspace):
            raise ValueError("Artifact must be an existing file inside the Studio workspace")

        relative_path = resolved.relative_to(self.workspace).as_posix()
        info = sf.info(str(resolved))
        frames = int(info.frames)
        sample_rate = int(info.samplerate)
        duration = (frames / sample_rate) if sample_rate > 0 else 0.0
        return {
            "id": self._artifact_id(relative_path),
            "kind": kind or "audio",
            "project_id": project_id,
            "section_id": section_id,
            "chunk_id": chunk_id,
            "filename": resolved.name,
            "path": str(resolved),
            "relative_path": relative_path,
            "format": resolved.suffix.lower().lstrip(".") or None,
            "size_bytes": int(resolved.stat().st_size),
            "duration_seconds": round(float(duration), 3),
            "sample_rate": sample_rate,
            "channels": int(info.channels),
        }

    def _project_artifacts(self, project_root: Path) -> list[dict[str, Any]]:
        project_id = project_root.name
        items: list[dict[str, Any]] = []
        for path in sorted(project_root.rglob("*.wav")):
            if not path.is_file():
                continue
            relative = path.relative_to(project_root)
            # Section Version History is recovery state, not a currently selected
            # artifact. Exposing it would create duplicate chunk/section choices
            # and could make an agent download stale audio after regeneration.
            if "history" in relative.parts:
                continue
            try:
                kind, section_id, chunk_id = self._classify_project_path(
                    project_root,
                    path,
                )
                items.append(
                    self.describe(
                        path,
                        project_id=project_id,
                        kind=kind,
                        section_id=section_id,
                        chunk_id=chunk_id,
                    )
                )
            except (OSError, RuntimeError, ValueError):
                continue
        return items

    def _standalone_artifacts(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.standalone_root.rglob("*.wav")):
            if not path.is_file():
                continue
            try:
                items.append(
                    self.describe(
                        path,
                        kind=self._classify_standalone_path(path),
                    )
                )
            except (OSError, RuntimeError, ValueError):
                continue
        return items

    def list(
        self,
        *,
        project_id: Optional[str] = None,
        kinds: Optional[Iterable[str]] = None,
    ) -> list[dict[str, Any]]:
        """Return current generated audio, optionally filtered by project/kind."""

        if project_id is not None:
            items = self._project_artifacts(self._project_root(project_id))
        else:
            items = self._standalone_artifacts()
            for project_root in sorted(self.projects_root.iterdir()):
                if not project_root.is_dir() or not (project_root / "project.json").exists():
                    continue
                items.extend(self._project_artifacts(project_root))

        selected = None
        if kinds:
            selected = {str(value).strip().lower() for value in kinds if str(value).strip()}
        if selected:
            items = [item for item in items if str(item["kind"]).lower() in selected]

        items.sort(key=lambda item: (item["project_id"] or "", item["relative_path"]))
        return items
