#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Persistent per-project advanced generation overrides.

Quality presets remain the primary, safe configuration surface. Advanced
settings are opt-in and only replace the small set of decoder/verification
values exposed by the Web UI. When disabled, Project Studio behaves exactly as
before and style profiles keep control of speaking speed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from omnivoice.models.omnivoice import OmniVoiceGenerationConfig
from omnivoice.robust_longform import RobustLongFormConfig

ADVANCED_SETTINGS_KEY = "advanced_settings"


@dataclass(frozen=True)
class AdvancedGenerationSettings:
    enabled: bool = False
    speed: float = 1.0
    num_step: int = 32
    guidance_scale: float = 2.0
    position_temperature: float = 1.0
    max_retries: int = 3
    max_wer: float = 0.18
    pause_ms: int = 320
    paragraph_pause_ms: int = 460

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AdvancedGenerationSettings":
        data = payload or {}
        settings = cls(
            enabled=bool(data.get("enabled", False)),
            speed=float(data.get("speed", 1.0)),
            num_step=int(data.get("num_step", 32)),
            guidance_scale=float(data.get("guidance_scale", 2.0)),
            position_temperature=float(data.get("position_temperature", 1.0)),
            max_retries=int(data.get("max_retries", 3)),
            max_wer=float(data.get("max_wer", 0.18)),
            pause_ms=int(data.get("pause_ms", 320)),
            paragraph_pause_ms=int(data.get("paragraph_pause_ms", 460)),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not 0.50 <= self.speed <= 1.50:
            raise ValueError("Speed must be between 0.50x and 1.50x")
        if not 16 <= self.num_step <= 64:
            raise ValueError("Diffusion steps must be between 16 and 64")
        if not 0.5 <= self.guidance_scale <= 5.0:
            raise ValueError("Guidance scale must be between 0.5 and 5.0")
        if not 0.20 <= self.position_temperature <= 2.00:
            raise ValueError("Position temperature must be between 0.20 and 2.00")
        if not 1 <= self.max_retries <= 6:
            raise ValueError("Max retries must be between 1 and 6")
        if not 0.01 <= self.max_wer <= 0.50:
            raise ValueError("Max WER must be between 0.01 and 0.50")
        if not 0 <= self.pause_ms <= 2000:
            raise ValueError("Pause must be between 0 and 2000 ms")
        if not 0 <= self.paragraph_pause_ms <= 3000:
            raise ValueError("Paragraph pause must be between 0 and 3000 ms")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def apply_generation_config(
        self,
        base: OmniVoiceGenerationConfig,
    ) -> OmniVoiceGenerationConfig:
        if not self.enabled:
            return base
        return replace(
            base,
            num_step=self.num_step,
            guidance_scale=self.guidance_scale,
            position_temperature=self.position_temperature,
        )

    def apply_robust_config(
        self,
        base: RobustLongFormConfig,
    ) -> RobustLongFormConfig:
        if not self.enabled:
            return base
        return replace(
            base,
            max_retries=self.max_retries,
            max_wer=self.max_wer,
            pause_ms=self.pause_ms,
            paragraph_pause_ms=self.paragraph_pause_ms,
        )

    def generation_kwargs(self) -> dict[str, Any]:
        # Supplying speed intentionally overrides StyleProfile.speed. When
        # advanced mode is disabled, no speed kwarg is returned and existing
        # [WARM]/[SOFT]/etc. style speed behavior remains untouched.
        return {"speed": self.speed} if self.enabled else {}
