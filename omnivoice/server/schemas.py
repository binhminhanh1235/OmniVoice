# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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
