#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Persistent project workflow for long-form narration.

The project layer turns a Markdown-like narration script into stable generation
units:

    Project -> Section -> Beat -> Chunk

Section headers use the form::

    ## S01 — 0:00–0:45

A leading directive such as ``[WARM]`` is metadata and is never sent to TTS.
The first style directive in a section becomes that section's default style.
Later directives start a new beat. Generic style intents (WARM, SOFT,
EMPHASIZE) remain model-agnostic; the OmniVoice adapter translates them into
safe delivery controls without inventing unsupported ``instruct`` values.

Each chunk is checkpointed independently. A resumed project skips chunks that
are already verified, so interrupted Colab sessions do not need to regenerate
completed work.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import soundfile as sf

from omnivoice.models.omnivoice import OmniVoiceGenerationConfig
from omnivoice.robust_longform import (
    RobustLongFormConfig,
    RobustLongFormGenerator,
    semantic_chunk_text,
)

logger = logging.getLogger(__name__)

_PROJECT_FORMAT_VERSION = 1
_SECTION_RE = re.compile(
    r"^##\s+(S\d{1,3})\s*[—–-]\s*"
    r"(\d{1,2}:\d{2}(?::\d{2})?)\s*[—–-]\s*"
    r"(\d{1,2}:\d{2}(?::\d{2})?)\s*$",
    flags=re.IGNORECASE,
)
_DIRECTIVE_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(.*)$")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$")
_H3_RE = re.compile(r"^###\s+(.+?)\s*$")

_STYLE_ALIASES = {
    "NORMAL": "DEFAULT",
    "NEUTRAL": "DEFAULT",
    "DEFAULT": "DEFAULT",
    "WARM": "WARM",
    "SOFT": "SOFT",
    "EMPHASIZE": "EMPHASIZE",
    "EMPHASISE": "EMPHASIZE",
    "WHISPER": "WHISPER",
    "LOW_PITCH": "LOW_PITCH",
    "HIGH_PITCH": "HIGH_PITCH",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "omnivoice-project"


def _parse_time(value: str) -> float:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return float(minutes * 60 + seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return float(hours * 3600 + minutes * 60 + seconds)
    raise ValueError(f"Unsupported timestamp: {value!r}")


def _normalise_directive_token(token: str) -> str:
    return re.sub(r"\s+", "_", token.strip().upper())


def _split_directives(raw: str) -> list[str]:
    return [
        _normalise_directive_token(token)
        for token in raw.split(",")
        if token.strip()
    ]


def _strip_markdown_line(line: str) -> str:
    line = line.rstrip()
    if line.endswith("\\"):
        line = line[:-1].rstrip()
    return line


@dataclass
class ProjectChunk:
    id: str
    text: str
    style: str
    paragraph_end: bool = False
    status: str = "pending"
    audio_file: Optional[str] = None
    report_file: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class ProjectBeat:
    id: str
    style: str
    text: str
    directives: list[str] = field(default_factory=list)
    chunks: list[ProjectChunk] = field(default_factory=list)
    status: str = "pending"
    audio_file: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class ProjectSection:
    id: str
    start_time: str
    end_time: str
    start_seconds: float
    end_seconds: float
    title: Optional[str] = None
    default_style: str = "DEFAULT"
    beats: list[ProjectBeat] = field(default_factory=list)
    status: str = "pending"
    audio_file: Optional[str] = None
    updated_at: Optional[str] = None

    @property
    def expected_duration(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)

    @property
    def spoken_text(self) -> str:
        return "\n\n".join(beat.text for beat in self.beats if beat.text.strip())


@dataclass
class ProjectManifest:
    title: str
    slug: str
    source_hash: str
    sections: list[ProjectSection]
    max_chunk_words: int = 24
    max_chunk_chars: int = 220
    version: int = _PROJECT_FORMAT_VERSION
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    @property
    def all_verified(self) -> bool:
        return all(section.status == "verified" for section in self.sections)


@dataclass(frozen=True)
class StyleProfile:
    """Model-agnostic narration intent resolved for OmniVoice."""

    name: str
    speed: float = 1.0
    pause_multiplier: float = 1.0
    beat_pause_ms: int = 240
    native_instruct: Optional[str] = None


DEFAULT_STYLE_PROFILES: dict[str, StyleProfile] = {
    "DEFAULT": StyleProfile("DEFAULT"),
    "WARM": StyleProfile(
        "WARM", speed=0.97, pause_multiplier=1.08, beat_pause_ms=280
    ),
    "SOFT": StyleProfile(
        "SOFT", speed=0.92, pause_multiplier=1.18, beat_pause_ms=340
    ),
    "EMPHASIZE": StyleProfile(
        "EMPHASIZE", speed=0.95, pause_multiplier=1.12, beat_pause_ms=300
    ),
    "WHISPER": StyleProfile(
        "WHISPER",
        speed=0.95,
        pause_multiplier=1.12,
        beat_pause_ms=300,
        native_instruct="whisper",
    ),
    "LOW_PITCH": StyleProfile("LOW_PITCH", native_instruct="low pitch"),
    "HIGH_PITCH": StyleProfile("HIGH_PITCH", native_instruct="high pitch"),
}


class OmniVoiceStyleResolver:
    """Resolve generic script styles into conservative OmniVoice controls."""

    def __init__(
        self,
        profiles: Optional[dict[str, StyleProfile]] = None,
    ) -> None:
        merged = dict(DEFAULT_STYLE_PROFILES)
        if profiles:
            merged.update({key.upper(): value for key, value in profiles.items()})
        self.profiles = merged

    def resolve(self, style: str) -> StyleProfile:
        return self.profiles.get(style.upper(), self.profiles["DEFAULT"])


def _build_chunks(
    beat_id: str,
    beat_text: str,
    style: str,
    max_chunk_words: int,
    max_chunk_chars: int,
) -> list[ProjectChunk]:
    chunks = semantic_chunk_text(
        beat_text,
        max_words=max_chunk_words,
        max_chars=max_chunk_chars,
    )
    return [
        ProjectChunk(
            id=f"{beat_id}-C{index:02d}",
            text=chunk.text,
            style=style,
            paragraph_end=chunk.paragraph_end,
        )
        for index, chunk in enumerate(chunks, start=1)
    ]


def _parse_section_body(
    section: ProjectSection,
    lines: list[str],
    max_chunk_words: int,
    max_chunk_chars: int,
) -> None:
    active_style = "DEFAULT"
    default_style_locked = False
    current_lines: list[str] = []
    current_directives: list[str] = []
    beats: list[ProjectBeat] = []

    def flush_beat() -> None:
        nonlocal current_lines, current_directives
        raw = "\n".join(current_lines).strip()
        text = re.sub(r"\n{3,}", "\n\n", raw)
        if not text:
            current_lines = []
            current_directives = []
            return

        beat_id = f"B{len(beats) + 1:02d}"
        beat = ProjectBeat(
            id=beat_id,
            style=active_style,
            text=text,
            directives=list(current_directives),
        )
        beat.chunks = _build_chunks(
            beat_id,
            beat.text,
            beat.style,
            max_chunk_words,
            max_chunk_chars,
        )
        beats.append(beat)
        current_lines = []
        current_directives = []

    for raw_line in lines:
        line = _strip_markdown_line(raw_line)

        h3 = _H3_RE.match(line)
        if h3:
            if section.title is None:
                section.title = h3.group(1).strip()
            continue

        if line.lstrip().startswith("#"):
            continue

        directive_match = _DIRECTIVE_RE.match(line)
        if directive_match:
            if current_lines and any(part.strip() for part in current_lines):
                flush_beat()

            tokens = _split_directives(directive_match.group(1))
            remainder = directive_match.group(2).strip()
            current_directives.extend(tokens)

            style_token = next(
                (_STYLE_ALIASES[token] for token in tokens if token in _STYLE_ALIASES),
                None,
            )
            if style_token is not None:
                active_style = style_token
                if not default_style_locked and not beats:
                    section.default_style = active_style
                    default_style_locked = True

            if remainder:
                current_lines.append(remainder)
            continue

        if not line.strip():
            if current_lines and current_lines[-1] != "":
                current_lines.append("")
            continue

        current_lines.append(line)

    flush_beat()
    section.beats = beats
    if not section.beats:
        raise ValueError(f"{section.id} contains no speakable text")


def parse_project_script(
    script: str,
    *,
    max_chunk_words: int = 24,
    max_chunk_chars: int = 220,
) -> ProjectManifest:
    """Parse a Markdown narration script into a project manifest."""

    if not isinstance(script, str) or not script.strip():
        raise ValueError("script must be a non-empty string")
    if max_chunk_words < 4:
        raise ValueError("max_chunk_words must be >= 4")
    if max_chunk_chars < 40:
        raise ValueError("max_chunk_chars must be >= 40")

    lines = script.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title = "OmniVoice Project"
    for line in lines:
        match = _H1_RE.match(line.strip())
        if match:
            title = match.group(1).strip()
            break

    sections: list[ProjectSection] = []
    current_section: Optional[ProjectSection] = None
    current_body: list[str] = []

    def finish_section() -> None:
        nonlocal current_section, current_body
        if current_section is None:
            return
        _parse_section_body(
            current_section,
            current_body,
            max_chunk_words,
            max_chunk_chars,
        )
        sections.append(current_section)
        current_section = None
        current_body = []

    for raw_line in lines:
        stripped = raw_line.strip()
        section_match = _SECTION_RE.match(stripped)
        if section_match:
            finish_section()
            section_id = section_match.group(1).upper()
            start_time = section_match.group(2)
            end_time = section_match.group(3)
            current_section = ProjectSection(
                id=section_id,
                start_time=start_time,
                end_time=end_time,
                start_seconds=_parse_time(start_time),
                end_seconds=_parse_time(end_time),
            )
            continue

        if current_section is not None:
            current_body.append(raw_line)

    finish_section()

    if not sections:
        raise ValueError(
            "No sections found. Expected headers like '## S01 — 0:00–0:45'."
        )

    ids = [section.id for section in sections]
    if len(ids) != len(set(ids)):
        raise ValueError("Section IDs must be unique")

    source_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()
    return ProjectManifest(
        title=title,
        slug=_slugify(title),
        source_hash=source_hash,
        sections=sections,
        max_chunk_words=max_chunk_words,
        max_chunk_chars=max_chunk_chars,
    )


def _manifest_to_dict(manifest: ProjectManifest) -> dict[str, Any]:
    return asdict(manifest)


def _manifest_from_dict(data: dict[str, Any]) -> ProjectManifest:
    sections = []
    for section_data in data.get("sections", []):
        beats = []
        for beat_data in section_data.get("beats", []):
            chunks = [
                ProjectChunk(**chunk_data)
                for chunk_data in beat_data.get("chunks", [])
            ]
            beat_fields = dict(beat_data)
            beat_fields["chunks"] = chunks
            beats.append(ProjectBeat(**beat_fields))
        section_fields = dict(section_data)
        section_fields["beats"] = beats
        sections.append(ProjectSection(**section_fields))

    manifest_fields = dict(data)
    manifest_fields["sections"] = sections
    return ProjectManifest(**manifest_fields)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


def _read_audio(path: Path) -> tuple[np.ndarray, int]:
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio.reshape(-1), int(sample_rate)


def _concat_audio(
    audios: Iterable[np.ndarray],
    sample_rate: int,
    pause_ms: int,
) -> np.ndarray:
    items = [np.asarray(audio, dtype=np.float32).reshape(-1) for audio in audios]
    if not items:
        return np.zeros(0, dtype=np.float32)

    pause = np.zeros(int(sample_rate * pause_ms / 1000), dtype=np.float32)
    output: list[np.ndarray] = []
    for index, audio in enumerate(items):
        output.append(audio)
        if index < len(items) - 1 and pause.size:
            output.append(pause)
    return np.concatenate(output).astype(np.float32)


class OmniVoiceProject:
    """Persistent project manager for sectioned narration."""

    MANIFEST_NAME = "project.json"

    def __init__(self, root: str | Path, manifest: ProjectManifest) -> None:
        self.root = Path(root)
        self.manifest = manifest

    @classmethod
    def create(
        cls,
        script: str,
        root: str | Path,
        *,
        max_chunk_words: int = 24,
        max_chunk_chars: int = 220,
        overwrite: bool = False,
    ) -> "OmniVoiceProject":
        root_path = Path(root)
        if root_path.exists() and any(root_path.iterdir()):
            if not overwrite:
                raise FileExistsError(
                    f"Project directory is not empty: {root_path}. "
                    "Use overwrite=True to replace it."
                )
            shutil.rmtree(root_path)

        manifest = parse_project_script(
            script,
            max_chunk_words=max_chunk_words,
            max_chunk_chars=max_chunk_chars,
        )
        project = cls(root_path, manifest)
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

    @classmethod
    def load(cls, root: str | Path) -> "OmniVoiceProject":
        root_path = Path(root)
        manifest_path = root_path / cls.MANIFEST_NAME
        if not manifest_path.exists():
            raise FileNotFoundError(f"Project manifest not found: {manifest_path}")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = _manifest_from_dict(data)
        if manifest.version != _PROJECT_FORMAT_VERSION:
            raise ValueError(
                f"Unsupported project version {manifest.version}; "
                f"expected {_PROJECT_FORMAT_VERSION}"
            )
        return cls(root_path, manifest)

    def save(self) -> None:
        self.manifest.updated_at = _utc_now()
        _write_json(
            self.root / self.MANIFEST_NAME,
            _manifest_to_dict(self.manifest),
        )
        for section in self.manifest.sections:
            self._write_section_metadata(section)

    def _section_dir(self, section: ProjectSection) -> Path:
        return self.root / "sections" / section.id

    def _write_section_metadata(self, section: ProjectSection) -> None:
        section_dir = self._section_dir(section)
        section_dir.mkdir(parents=True, exist_ok=True)
        _write_json(section_dir / "metadata.json", asdict(section))

    def get_section(self, section_id: str) -> ProjectSection:
        key = section_id.upper()
        for section in self.manifest.sections:
            if section.id == key:
                return section
        raise KeyError(f"Unknown section: {section_id}")

    def get_chunk(self, section_id: str, chunk_id: str) -> ProjectChunk:
        section = self.get_section(section_id)
        for beat in section.beats:
            for chunk in beat.chunks:
                if chunk.id == chunk_id:
                    return chunk
        raise KeyError(f"Unknown chunk {section_id}/{chunk_id}")

    def summary(self) -> list[dict[str, Any]]:
        return [
            {
                "section": section.id,
                "title": section.title,
                "style": section.default_style,
                "start": section.start_time,
                "end": section.end_time,
                "expected_seconds": section.expected_duration,
                "beats": len(section.beats),
                "chunks": sum(len(beat.chunks) for beat in section.beats),
                "status": section.status,
            }
            for section in self.manifest.sections
        ]

    def mark_chunk_for_regeneration(
        self,
        section_id: str,
        chunk_id: str,
    ) -> None:
        chunk = self.get_chunk(section_id, chunk_id)
        chunk.status = "pending"
        chunk.updated_at = _utc_now()

        section = self.get_section(section_id)
        section.status = "pending"
        section.updated_at = _utc_now()
        for beat in section.beats:
            if any(item.id == chunk_id for item in beat.chunks):
                beat.status = "pending"
                beat.updated_at = _utc_now()
                break
        self.save()

    def _chunk_paths(
        self,
        section: ProjectSection,
        chunk: ProjectChunk,
    ) -> tuple[Path, Path]:
        chunk_dir = self._section_dir(section) / "chunks"
        return (
            chunk_dir / f"{chunk.id}.wav",
            chunk_dir / f"{chunk.id}.json",
        )

    def _assemble_beat(
        self,
        section: ProjectSection,
        beat: ProjectBeat,
        sample_rate: int,
        profile: StyleProfile,
    ) -> None:
        chunk_audios = []
        for chunk in beat.chunks:
            if not chunk.audio_file:
                raise RuntimeError(
                    f"Cannot assemble {section.id}/{beat.id}; "
                    f"{chunk.id} has no audio"
                )
            audio, sr = _read_audio(self.root / chunk.audio_file)
            if sr != sample_rate:
                raise RuntimeError(
                    f"Sample-rate mismatch in {section.id}/{chunk.id}: "
                    f"{sr} != {sample_rate}"
                )
            chunk_audios.append(audio)

        beat_audio = _concat_audio(
            chunk_audios,
            sample_rate,
            pause_ms=max(0, int(220 * profile.pause_multiplier)),
        )
        beat_path = self._section_dir(section) / "beats" / f"{beat.id}.wav"
        sf.write(beat_path, beat_audio, sample_rate, subtype="PCM_16")
        beat.audio_file = str(beat_path.relative_to(self.root))
        beat.status = (
            "verified"
            if all(chunk.status == "verified" for chunk in beat.chunks)
            else "unverified"
        )
        beat.updated_at = _utc_now()

    def _assemble_section(
        self,
        section: ProjectSection,
        sample_rate: int,
        resolver: OmniVoiceStyleResolver,
    ) -> None:
        pieces: list[np.ndarray] = []
        for index, beat in enumerate(section.beats):
            if not beat.audio_file:
                raise RuntimeError(
                    f"Cannot assemble {section.id}; {beat.id} has no audio"
                )
            audio, sr = _read_audio(self.root / beat.audio_file)
            if sr != sample_rate:
                raise RuntimeError(
                    f"Sample-rate mismatch in {section.id}/{beat.id}: "
                    f"{sr} != {sample_rate}"
                )
            pieces.append(audio)
            if index < len(section.beats) - 1:
                profile = resolver.resolve(beat.style)
                pieces.append(
                    np.zeros(
                        int(sample_rate * profile.beat_pause_ms / 1000),
                        dtype=np.float32,
                    )
                )

        section_audio = np.concatenate(pieces).astype(np.float32)
        section_path = self._section_dir(section) / f"{section.id}.wav"
        sf.write(section_path, section_audio, sample_rate, subtype="PCM_16")
        section.audio_file = str(section_path.relative_to(self.root))
        section.status = (
            "verified"
            if all(beat.status == "verified" for beat in section.beats)
            else "unverified"
        )
        section.updated_at = _utc_now()

    def generate(
        self,
        model: Any,
        *,
        voice_clone_prompt: Any = None,
        robust_config: Optional[RobustLongFormConfig] = None,
        generation_config: Optional[OmniVoiceGenerationConfig] = None,
        style_profiles: Optional[dict[str, StyleProfile]] = None,
        section_ids: Optional[Iterable[str]] = None,
        resume: bool = True,
        **generate_kwargs: Any,
    ) -> ProjectManifest:
        """Generate selected sections with chunk-level checkpoint/resume."""

        sample_rate = int(model.sampling_rate)
        base_robust = robust_config or RobustLongFormConfig(
            max_chunk_words=self.manifest.max_chunk_words,
            max_chunk_chars=self.manifest.max_chunk_chars,
        )
        base_generation = generation_config or OmniVoiceGenerationConfig()
        resolver = OmniVoiceStyleResolver(style_profiles)

        selected = None
        if section_ids is not None:
            selected = {item.upper() for item in section_ids}

        for section in self.manifest.sections:
            if selected is not None and section.id not in selected:
                continue

            for beat in section.beats:
                profile = resolver.resolve(beat.style)
                style_robust = replace(
                    base_robust,
                    pause_ms=max(
                        0,
                        int(base_robust.pause_ms * profile.pause_multiplier),
                    ),
                    paragraph_pause_ms=max(
                        0,
                        int(
                            base_robust.paragraph_pause_ms
                            * profile.pause_multiplier
                        ),
                    ),
                )

                for chunk in beat.chunks:
                    audio_path, report_path = self._chunk_paths(section, chunk)
                    if (
                        resume
                        and chunk.status == "verified"
                        and audio_path.exists()
                    ):
                        chunk.audio_file = str(audio_path.relative_to(self.root))
                        chunk.report_file = str(report_path.relative_to(self.root))
                        continue

                    kwargs = dict(generate_kwargs)
                    if voice_clone_prompt is not None:
                        kwargs["voice_clone_prompt"] = voice_clone_prompt

                    if "duration" not in kwargs and "speed" not in kwargs:
                        kwargs["speed"] = profile.speed

                    # WARM/SOFT/EMPHASIZE never become unsupported instruct text.
                    if profile.native_instruct and "instruct" not in kwargs:
                        kwargs["instruct"] = profile.native_instruct

                    generator = RobustLongFormGenerator(model, style_robust)
                    result = generator.generate(
                        chunk.text,
                        generation_config=base_generation,
                        **kwargs,
                    )

                    audio_path.parent.mkdir(parents=True, exist_ok=True)
                    sf.write(
                        audio_path,
                        result.audio,
                        result.sampling_rate,
                        subtype="PCM_16",
                    )
                    report_payload = {
                        "section": section.id,
                        "beat": beat.id,
                        "chunk": chunk.id,
                        "style": chunk.style,
                        "all_verified": result.all_verified,
                        "source_text": chunk.text,
                        "generated_chunks": result.chunks,
                        "reports": [asdict(report) for report in result.reports],
                    }
                    _write_json(report_path, report_payload)

                    chunk.audio_file = str(audio_path.relative_to(self.root))
                    chunk.report_file = str(report_path.relative_to(self.root))
                    chunk.status = (
                        "verified" if result.all_verified else "unverified"
                    )
                    chunk.updated_at = _utc_now()
                    self.save()

                self._assemble_beat(section, beat, sample_rate, profile)
                self.save()

            self._assemble_section(section, sample_rate, resolver)
            self.save()

        return self.manifest

    def merge(
        self,
        output_path: str | Path | None = None,
        *,
        section_pause_ms: int = 300,
        require_verified: bool = True,
    ) -> Path:
        """Merge section WAV files and write an actual-duration timeline."""

        if section_pause_ms < 0:
            raise ValueError("section_pause_ms must be >= 0")
        if require_verified and not self.manifest.all_verified:
            pending = [
                section.id
                for section in self.manifest.sections
                if section.status != "verified"
            ]
            raise RuntimeError(
                "Cannot merge an unverified project. "
                f"Pending/unverified sections: {', '.join(pending)}"
            )

        sample_rate: Optional[int] = None
        section_audios: list[np.ndarray] = []
        timeline = []
        cursor_seconds = 0.0

        for section in self.manifest.sections:
            if not section.audio_file:
                raise RuntimeError(f"{section.id} has not been generated")
            audio, sr = _read_audio(self.root / section.audio_file)
            if sample_rate is None:
                sample_rate = sr
            elif sr != sample_rate:
                raise RuntimeError(
                    f"Sample-rate mismatch for {section.id}: {sr} != {sample_rate}"
                )

            actual_start = cursor_seconds
            actual_end = actual_start + len(audio) / sample_rate
            timeline.append(
                {
                    "section": section.id,
                    "planned_start": section.start_time,
                    "planned_end": section.end_time,
                    "actual_start_seconds": actual_start,
                    "actual_end_seconds": actual_end,
                    "actual_duration_seconds": actual_end - actual_start,
                }
            )
            section_audios.append(audio)
            cursor_seconds = actual_end + section_pause_ms / 1000

        assert sample_rate is not None
        merged = _concat_audio(
            section_audios,
            sample_rate,
            pause_ms=section_pause_ms,
        )

        destination = (
            Path(output_path)
            if output_path is not None
            else self.root / "output" / "full.wav"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        sf.write(destination, merged, sample_rate, subtype="PCM_16")
        _write_json(self.root / "output" / "timeline.json", timeline)
        return destination
