#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Narration-focused project parsing helpers used by Project Studio.

This module keeps the base project format stable while adding two presentation
options that are useful for long-form narration:

* keep sentence-initial conjunctions such as ``Or`` with the preceding short
  sentence when the combined chunk remains within configured limits;
* optionally speak Markdown ``###`` section titles as a dedicated first beat.

The original script is still saved unchanged.  Only the generated manifest is
adjusted before project files are written.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from omnivoice.project import (
    OmniVoiceProject,
    ProjectBeat,
    ProjectChunk,
    ProjectManifest,
    _build_chunks,
    parse_project_script,
)

_LEADING_CONNECTOR_RE = re.compile(
    r"^(?:and|but|or|so|yet|nor)\b",
    flags=re.IGNORECASE,
)


def _within_limits(text: str, max_words: int, max_chars: int) -> bool:
    return len(text.split()) <= max_words and len(text) <= max_chars


def _merge_leading_connector_chunks(
    chunks: list[ProjectChunk],
    *,
    max_words: int,
    max_chars: int,
) -> list[ProjectChunk]:
    """Avoid fragile chunks that begin with a context-dependent conjunction."""

    merged: list[ProjectChunk] = []
    for chunk in chunks:
        if merged and _LEADING_CONNECTOR_RE.match(chunk.text):
            previous = merged[-1]
            combined = f"{previous.text.rstrip()} {chunk.text.lstrip()}"
            if not previous.paragraph_end and _within_limits(
                combined,
                max_words,
                max_chars,
            ):
                previous.text = combined
                previous.paragraph_end = chunk.paragraph_end
                continue
        merged.append(chunk)
    return merged


def _speakable_title(title: str) -> str:
    title = title.strip()
    if title and title[-1] not in ".!?":
        title += "."
    return title


def _rebuild_section(
    section,
    *,
    max_chunk_words: int,
    max_chunk_chars: int,
    speak_section_titles: bool,
) -> None:
    beats = list(section.beats)
    if speak_section_titles and section.title:
        beats.insert(
            0,
            ProjectBeat(
                id="",
                style=section.default_style,
                text=_speakable_title(section.title),
                directives=["SECTION_TITLE"],
            ),
        )

    for beat_index, beat in enumerate(beats, start=1):
        beat.id = f"B{beat_index:02d}"
        beat.chunks = _build_chunks(
            beat.id,
            beat.text,
            beat.style,
            max_chunk_words,
            max_chunk_chars,
        )
        beat.chunks = _merge_leading_connector_chunks(
            beat.chunks,
            max_words=max_chunk_words,
            max_chars=max_chunk_chars,
        )
        for chunk_index, chunk in enumerate(beat.chunks, start=1):
            chunk.id = f"{beat.id}-C{chunk_index:02d}"

    section.beats = beats


def parse_narration_project_script(
    script: str,
    *,
    max_chunk_words: int = 24,
    max_chunk_chars: int = 220,
    speak_section_titles: bool = False,
) -> ProjectManifest:
    """Parse a script and apply Project Studio narration safeguards."""

    manifest = parse_project_script(
        script,
        max_chunk_words=max_chunk_words,
        max_chunk_chars=max_chunk_chars,
    )
    for section in manifest.sections:
        _rebuild_section(
            section,
            max_chunk_words=max_chunk_words,
            max_chunk_chars=max_chunk_chars,
            speak_section_titles=bool(speak_section_titles),
        )

    option_prefix = f"speak_section_titles={int(bool(speak_section_titles))}\0"
    manifest.source_hash = hashlib.sha256(
        (option_prefix + script).encode("utf-8")
    ).hexdigest()
    return manifest


def create_narration_project(
    script: str,
    root: str | Path,
    *,
    max_chunk_words: int = 24,
    max_chunk_chars: int = 220,
    speak_section_titles: bool = False,
    overwrite: bool = False,
) -> OmniVoiceProject:
    """Create a persistent project from the narration-adjusted manifest."""

    root_path = Path(root)
    if root_path.exists() and any(root_path.iterdir()):
        if not overwrite:
            raise FileExistsError(
                f"Project directory is not empty: {root_path}. "
                "Use overwrite=True to replace it."
            )
        shutil.rmtree(root_path)

    manifest = parse_narration_project_script(
        script,
        max_chunk_words=max_chunk_words,
        max_chunk_chars=max_chunk_chars,
        speak_section_titles=speak_section_titles,
    )
    project = OmniVoiceProject(root_path, manifest)
    project.root.mkdir(parents=True, exist_ok=True)
    (project.root / "script.md").write_text(script, encoding="utf-8")
    (project.root / "output").mkdir(parents=True, exist_ok=True)

    for section in manifest.sections:
        section_dir = project._section_dir(section)
        (section_dir / "chunks").mkdir(parents=True, exist_ok=True)
        (section_dir / "beats").mkdir(parents=True, exist_ok=True)
        (section_dir / "text.txt").write_text(
            section.spoken_text,
            encoding="utf-8",
        )

    project.save()
    return project
