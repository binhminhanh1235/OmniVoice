#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Export generated Project Studio section audio as standalone MP3 files."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from omnivoice.project import OmniVoiceProject


DEFAULT_MP3_BITRATE = "192k"


@dataclass(frozen=True)
class SectionMp3ExportResult:
    files: tuple[Path, ...]
    skipped: tuple[str, ...]
    reused: tuple[str, ...]


def section_ids(project: OmniVoiceProject) -> list[str]:
    """Return project section IDs in manifest order."""

    return [section.id for section in project.manifest.sections]


def _normalise_selected(project: OmniVoiceProject, selected: Iterable[str]) -> list[str]:
    requested = [str(item).strip().upper() for item in selected if str(item).strip()]
    if not requested:
        raise ValueError("Select at least one section to export")

    available = section_ids(project)
    available_set = set(available)
    unknown = sorted(set(requested) - available_set)
    if unknown:
        raise ValueError(f"Unknown sections: {', '.join(unknown)}")

    selected_set = set(requested)
    return [section_id for section_id in available if section_id in selected_set]


def _ffmpeg_binary(binary: str = "ffmpeg") -> str:
    resolved = shutil.which(binary)
    if not resolved:
        raise RuntimeError(
            "ffmpeg is required for MP3 export but was not found on PATH"
        )
    return resolved


def export_section_mp3s(
    project: OmniVoiceProject,
    selected: Iterable[str],
    *,
    bitrate: str = DEFAULT_MP3_BITRATE,
    ffmpeg_binary: str = "ffmpeg",
) -> SectionMp3ExportResult:
    """Export selected generated section WAVs to cached MP3 copies.

    Original Project Studio section WAVs are never modified. MP3 files live in
    ``<project>/exports/mp3``. A cached MP3 is reused when it is newer than its
    source WAV and is non-empty.
    """

    targets = _normalise_selected(project, selected)
    ffmpeg = _ffmpeg_binary(ffmpeg_binary)
    export_dir = project.root / "exports" / "mp3"
    export_dir.mkdir(parents=True, exist_ok=True)

    exported: list[Path] = []
    skipped: list[str] = []
    reused: list[str] = []

    for section_id in targets:
        section = project.get_section(section_id)
        if not section.audio_file:
            skipped.append(f"{section_id}: no generated section audio")
            continue

        source = project.root / section.audio_file
        if not source.exists():
            skipped.append(f"{section_id}: source audio is missing")
            continue

        destination = export_dir / f"{section_id}.mp3"
        if (
            destination.exists()
            and destination.stat().st_size > 0
            and destination.stat().st_mtime_ns >= source.stat().st_mtime_ns
        ):
            exported.append(destination)
            reused.append(section_id)
            continue

        temp = export_dir / f".{section_id}.tmp.mp3"
        temp.unlink(missing_ok=True)
        command = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            str(temp),
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            temp.unlink(missing_ok=True)
            raise RuntimeError(f"Could not start ffmpeg for {section_id}: {exc}") from exc

        if completed.returncode != 0 or not temp.exists() or temp.stat().st_size <= 0:
            temp.unlink(missing_ok=True)
            stderr = (completed.stderr or "").strip()
            detail = stderr[-800:] if stderr else f"exit code {completed.returncode}"
            raise RuntimeError(f"MP3 export failed for {section_id}: {detail}")

        temp.replace(destination)
        exported.append(destination)

    return SectionMp3ExportResult(
        files=tuple(exported),
        skipped=tuple(skipped),
        reused=tuple(reused),
    )


def create_section_mp3_archive(
    project: OmniVoiceProject,
    files: Iterable[str | Path],
) -> Path:
    """Bundle two or more exported section MP3 files into one fast ZIP download.

    MP3 is already compressed, so the archive deliberately uses ``ZIP_STORED``
    rather than spending CPU trying to compress audio again. Only files from the
    project's own ``exports/mp3`` directory are accepted.
    """

    export_dir = (project.root / "exports" / "mp3").resolve()
    selected: list[Path] = []
    seen: set[Path] = set()
    for item in files:
        path = Path(item).expanduser().resolve()
        if path in seen:
            continue
        if path.parent != export_dir:
            raise ValueError(f"Archive input is outside project MP3 exports: {path}")
        if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"Archive input is missing or empty: {path}")
        if path.suffix.lower() != ".mp3":
            raise ValueError(f"Archive input is not MP3: {path}")
        seen.add(path)
        selected.append(path)

    if len(selected) < 2:
        raise ValueError("At least two MP3 files are required for Download all")

    archive_dir = project.root / "exports"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / f"{project.root.name}-selected-sections.zip"
    temp = archive.with_suffix(".tmp.zip")
    temp.unlink(missing_ok=True)

    try:
        with zipfile.ZipFile(temp, mode="w", compression=zipfile.ZIP_STORED) as bundle:
            for path in selected:
                bundle.write(path, arcname=path.name)
        temp.replace(archive)
    except Exception:
        temp.unlink(missing_ok=True)
        raise

    return archive
