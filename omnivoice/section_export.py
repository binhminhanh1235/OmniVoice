#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Create fast ZIP downloads from generated Project Studio section audio."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from omnivoice.project import OmniVoiceProject


@dataclass(frozen=True)
class ProjectAudioArchiveResult:
    archive: Path
    included: tuple[str, ...]
    skipped: tuple[str, ...]


def section_ids(project: OmniVoiceProject) -> list[str]:
    """Return project section IDs in manifest order."""

    return [section.id for section in project.manifest.sections]


def create_project_audio_archive(project: OmniVoiceProject) -> ProjectAudioArchiveResult:
    """Bundle generated section audio into one ZIP without merging or re-encoding.

    Files are included in manifest order and keep their original bytes. The ZIP
    uses ``ZIP_STORED`` because WAV/other generated audio should not spend CPU on
    another compression pass. Sections without generated audio are reported as
    skipped rather than blocking the download.
    """

    root = project.root.resolve()
    included: list[tuple[str, Path]] = []
    skipped: list[str] = []

    for section in project.manifest.sections:
        if not section.audio_file:
            skipped.append(f"{section.id}: no generated section audio")
            continue

        source = (project.root / section.audio_file).resolve()
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"Section audio is outside project root: {section.id}: {source}"
            ) from exc

        if not source.exists() or not source.is_file() or source.stat().st_size <= 0:
            skipped.append(f"{section.id}: source audio is missing or empty")
            continue

        included.append((section.id, source))

    if not included:
        raise ValueError("This project has no generated section audio to download")

    export_dir = project.root / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    archive = export_dir / f"{project.root.name}-section-audio.zip"
    temp = archive.with_suffix(".tmp.zip")
    temp.unlink(missing_ok=True)

    try:
        with zipfile.ZipFile(temp, mode="w", compression=zipfile.ZIP_STORED) as bundle:
            for section_id, source in included:
                bundle.write(source, arcname=f"{section_id}{source.suffix.lower()}")
        temp.replace(archive)
    except Exception:
        temp.unlink(missing_ok=True)
        raise

    return ProjectAudioArchiveResult(
        archive=archive,
        included=tuple(section_id for section_id, _ in included),
        skipped=tuple(skipped),
    )
