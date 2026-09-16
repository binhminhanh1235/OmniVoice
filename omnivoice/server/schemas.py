# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImportProjectRequest(BaseModel):
    """Synchronously import one native OmniVoice Markdown narration project."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    script: str
    speak_section_titles: bool = False
    max_chunk_words: int = Field(default=24, ge=4)
    max_chunk_chars: int = Field(default=220, ge=40)


class GenerateProjectRequest(BaseModel):
    """Submit resumable project/section generation to the GPU job queue."""

    voice_name: Optional[str] = None
    voice_variant: Optional[str] = None
    language: Optional[str] = None
    sections: Optional[list[str]] = None
    resume: bool = True
    strict: bool = False
    quality_preset: Optional[str] = Field(
        default=None,
        description="SAFE, BALANCED or FAST. Omit to use saved project/workspace policy.",
    )


class GenerateAudioRequest(BaseModel):
    """Submit one standalone audio generation without creating a project."""

    text: str = Field(min_length=1)
    voice_name: Optional[str] = None
    voice_variant: Optional[str] = None
    language: Optional[str] = "en"
    instruct: Optional[str] = None
    speed: Optional[float] = Field(default=None, gt=0)
    quality_preset: Optional[str] = None
    style: Optional[str] = "DEFAULT"


class PreviewAudioRequest(BaseModel):
    """Submit direct-text or project representative preview generation."""

    text: Optional[str] = None
    project_id: Optional[str] = None
    voice_name: Optional[str] = None
    voice_variant: Optional[str] = None
    language: Optional[str] = None
    labels: Optional[list[str]] = None
    instruct: Optional[str] = None
    speed: Optional[float] = Field(default=None, gt=0)
    quality_preset: Optional[str] = None
    strict: bool = False
    style: Optional[str] = "DEFAULT"

    @model_validator(mode="after")
    def validate_target(self):
        if not str(self.text or "").strip() and not str(self.project_id or "").strip():
            raise ValueError("preview requires text or project_id")
        return self


class RegenerateRequest(BaseModel):
    """Shared voice/quality overrides for section or chunk regeneration."""

    voice_name: Optional[str] = None
    voice_variant: Optional[str] = None
    language: Optional[str] = None
    strict: bool = False
    quality_preset: Optional[str] = None
