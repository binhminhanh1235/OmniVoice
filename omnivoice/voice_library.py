#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Persistent reusable voice prompts for OmniVoice Studio.

A voice is stored once and can then be reused across projects without
re-transcribing or re-encoding the reference audio on every Colab session.
The storage format intentionally keeps variants generic (DEFAULT, WARM, SOFT,
etc.) so a later Style Bank can select a matching prompt without changing the
project script format.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from omnivoice.models.omnivoice import VoiceClonePrompt

_VOICE_FORMAT_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "voice"


def _normalise_variant(value: str | None) -> str:
    value = (value or "DEFAULT").strip().upper()
    value = re.sub(r"[^A-Z0-9]+", "_", value).strip("_")
    return value or "DEFAULT"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


@dataclass
class VoiceVariant:
    name: str
    prompt_file: str
    ref_text: str
    language: Optional[str] = None
    reference_file: Optional[str] = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)


@dataclass
class VoiceEntry:
    name: str
    slug: str
    variants: dict[str, VoiceVariant] = field(default_factory=dict)
    version: int = _VOICE_FORMAT_VERSION
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    @property
    def default_variant(self) -> str:
        if "DEFAULT" in self.variants:
            return "DEFAULT"
        if not self.variants:
            raise ValueError(f"Voice {self.name!r} has no variants")
        return sorted(self.variants)[0]


class VoiceLibrary:
    """Filesystem-backed library of reusable :class:`VoiceClonePrompt` objects."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _voice_dir(self, slug: str) -> Path:
        return self.root / slug

    def _manifest_path(self, slug: str) -> Path:
        return self._voice_dir(slug) / "voice.json"

    def list_voices(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for manifest_path in sorted(self.root.glob("*/voice.json")):
            try:
                entry = self._read_entry(manifest_path)
            except Exception:
                continue
            rows.append(
                {
                    "name": entry.name,
                    "slug": entry.slug,
                    "variants": sorted(entry.variants),
                    "updated_at": entry.updated_at,
                }
            )
        return rows

    def voice_names(self) -> list[str]:
        return [row["name"] for row in self.list_voices()]

    def _find_slug(self, name_or_slug: str) -> str:
        direct = _slugify(name_or_slug)
        if self._manifest_path(direct).exists():
            return direct
        for row in self.list_voices():
            if row["name"].casefold() == name_or_slug.casefold():
                return row["slug"]
        raise KeyError(f"Unknown voice: {name_or_slug}")

    def _read_entry(self, manifest_path: Path) -> VoiceEntry:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        variants = {
            key: VoiceVariant(**value)
            for key, value in data.get("variants", {}).items()
        }
        data = dict(data)
        data["variants"] = variants
        entry = VoiceEntry(**data)
        if entry.version != _VOICE_FORMAT_VERSION:
            raise ValueError(
                f"Unsupported voice format {entry.version}; "
                f"expected {_VOICE_FORMAT_VERSION}"
            )
        return entry

    def get(self, name_or_slug: str) -> VoiceEntry:
        slug = self._find_slug(name_or_slug)
        return self._read_entry(self._manifest_path(slug))

    def save_prompt(
        self,
        name: str,
        prompt: VoiceClonePrompt,
        *,
        variant: str = "DEFAULT",
        language: Optional[str] = None,
        reference_audio: Optional[str | Path] = None,
        overwrite_variant: bool = True,
    ) -> VoiceEntry:
        """Store one encoded prompt and optional reference copy."""

        if not name or not name.strip():
            raise ValueError("voice name must be non-empty")
        slug = _slugify(name)
        variant_key = _normalise_variant(variant)
        voice_dir = self._voice_dir(slug)
        prompt_dir = voice_dir / "prompts"
        ref_dir = voice_dir / "references"
        prompt_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = self._manifest_path(slug)
        if manifest_path.exists():
            entry = self._read_entry(manifest_path)
        else:
            entry = VoiceEntry(name=name.strip(), slug=slug)

        if variant_key in entry.variants and not overwrite_variant:
            raise FileExistsError(
                f"Voice {entry.name!r} already has variant {variant_key!r}"
            )

        prompt_path = prompt_dir / f"{variant_key.lower()}.pt"
        prompt.save(str(prompt_path))

        reference_file: Optional[str] = None
        if reference_audio is not None:
            source = Path(reference_audio)
            if not source.exists():
                raise FileNotFoundError(source)
            ref_dir.mkdir(parents=True, exist_ok=True)
            suffix = source.suffix.lower() or ".wav"
            destination = ref_dir / f"{variant_key.lower()}{suffix}"
            shutil.copy2(source, destination)
            reference_file = str(destination.relative_to(voice_dir))

        now = _utc_now()
        entry.name = name.strip()
        entry.updated_at = now
        entry.variants[variant_key] = VoiceVariant(
            name=variant_key,
            prompt_file=str(prompt_path.relative_to(voice_dir)),
            ref_text=prompt.ref_text,
            language=language,
            reference_file=reference_file,
            created_at=(
                entry.variants[variant_key].created_at
                if variant_key in entry.variants
                else now
            ),
            updated_at=now,
        )
        _write_json(manifest_path, asdict(entry))
        return entry

    def create_from_reference(
        self,
        model: Any,
        *,
        name: str,
        reference_audio: str | Path,
        ref_text: Optional[str] = None,
        variant: str = "DEFAULT",
        language: Optional[str] = None,
        preprocess_prompt: bool = True,
        overwrite_variant: bool = True,
    ) -> VoiceEntry:
        """Encode a reference once, then persist it for later sessions."""

        prompt = model.create_voice_clone_prompt(
            ref_audio=str(reference_audio),
            ref_text=ref_text.strip() if ref_text and ref_text.strip() else None,
            preprocess_prompt=preprocess_prompt,
        )
        return self.save_prompt(
            name,
            prompt,
            variant=variant,
            language=language,
            reference_audio=reference_audio,
            overwrite_variant=overwrite_variant,
        )

    def load_prompt(
        self,
        name_or_slug: str,
        variant: Optional[str] = None,
    ) -> VoiceClonePrompt:
        entry = self.get(name_or_slug)
        variant_key = _normalise_variant(variant or entry.default_variant)
        if variant_key not in entry.variants:
            available = ", ".join(sorted(entry.variants))
            raise KeyError(
                f"Voice {entry.name!r} has no variant {variant_key!r}. "
                f"Available: {available}"
            )
        voice_dir = self._voice_dir(entry.slug)
        prompt_path = voice_dir / entry.variants[variant_key].prompt_file
        return VoiceClonePrompt.load(str(prompt_path))

    def variants(self, name_or_slug: str) -> list[str]:
        return sorted(self.get(name_or_slug).variants)

    def delete_voice(self, name_or_slug: str) -> None:
        entry = self.get(name_or_slug)
        shutil.rmtree(self._voice_dir(entry.slug))
