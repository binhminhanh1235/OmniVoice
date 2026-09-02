#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Hardware capability detection and quality presets for Project Studio.

The goal of this module is to reduce knobs rather than add them.  It exposes
three named policies, SAFE / BALANCED / FAST, and a small hardware summary that
can recommend a sensible policy for the current Colab/runtime.

Important safety rule: every preset keeps ASR text verification enabled.  FAST
trades generation effort and automatic repair depth for speed, but it still
flags text mismatches as unverified instead of silently accepting them.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from omnivoice.adaptive_quality import AdaptiveQualityConfig
from omnivoice.models.omnivoice import OmniVoiceGenerationConfig
from omnivoice.robust_longform import RobustLongFormConfig

QUALITY_PRESETS = ("SAFE", "BALANCED", "FAST")
HARDWARE_SETTINGS_FILE = "hardware-quality.json"


def normalize_quality_preset(value: Optional[str]) -> str:
    name = (value or "SAFE").strip().upper()
    if name not in QUALITY_PRESETS:
        raise ValueError(
            f"Unknown quality preset {value!r}; choose one of {', '.join(QUALITY_PRESETS)}"
        )
    return name


@dataclass(frozen=True)
class HardwareCapabilities:
    cuda_available: bool
    device_count: int = 0
    device_index: Optional[int] = None
    device_name: str = "CPU"
    total_vram_gb: float = 0.0
    compute_capability: Optional[tuple[int, int]] = None
    recommended_asr_device: str = "cpu"
    recommended_preset: str = "SAFE"
    notes: tuple[str, ...] = ()

    @property
    def compute_capability_text(self) -> str:
        if self.compute_capability is None:
            return "n/a"
        major, minor = self.compute_capability
        return f"{major}.{minor}"

    def summary(self) -> str:
        if not self.cuda_available:
            return (
                "CUDA not detected. OmniVoice generation may be unsupported or very slow. "
                f"Recommended preset={self.recommended_preset}; ASR={self.recommended_asr_device}."
            )
        return (
            f"GPU={self.device_name} · VRAM={self.total_vram_gb:.1f} GB · "
            f"compute={self.compute_capability_text} · "
            f"recommended preset={self.recommended_preset} · "
            f"recommended ASR={self.recommended_asr_device}"
        )


@dataclass(frozen=True)
class QualityPresetPolicy:
    name: str
    description: str
    num_step: int
    max_retries: int
    max_split_depth: int
    adaptive_retry: bool
    pacing_guard: bool

    def generation_config(self) -> OmniVoiceGenerationConfig:
        return OmniVoiceGenerationConfig(
            num_step=self.num_step,
            guidance_scale=2.0,
            position_temperature=1.0,
            class_temperature=0.0,
            audio_chunk_threshold=1e9,
            pad_duration=0.0,
            fade_duration=0.0,
            postprocess_output=True,
            output_min_silence_ms=650,
            output_keep_silence_ms=180,
            output_lead_silence_ms=80,
            output_trail_silence_ms=130,
            output_target_lead_silence_ms=80,
            output_target_trail_silence_ms=130,
        )

    def robust_config(
        self,
        *,
        strict: bool = False,
        max_chunk_words: int = 24,
        max_chunk_chars: int = 220,
        asr_model_name: str = "openai/whisper-small.en",
        asr_device: str = "cpu",
    ) -> RobustLongFormConfig:
        return RobustLongFormConfig(
            max_chunk_words=max_chunk_words,
            max_chunk_chars=max_chunk_chars,
            max_retries=self.max_retries,
            max_split_depth=self.max_split_depth,
            # Even FAST keeps textual verification on.  It simply spends less
            # decoder/retry effort repairing a failed candidate automatically.
            verify_with_asr=True,
            asr_model_name=asr_model_name,
            asr_device=asr_device,
            max_wer=0.18,
            min_similarity=0.82,
            min_word_ratio=0.74,
            max_word_ratio=1.30,
            pause_ms=320,
            paragraph_pause_ms=460,
            strict=strict,
            exact_chunk_edges=False,
        )

    def adaptive_config(self) -> AdaptiveQualityConfig:
        return AdaptiveQualityConfig(
            adaptive_retry=self.adaptive_retry,
            pacing_guard=self.pacing_guard,
        )

    def comparison_row(self) -> list[Any]:
        return [
            self.name,
            self.num_step,
            self.max_retries,
            self.max_split_depth,
            "ON",
            "ON" if self.adaptive_retry else "OFF",
            "ON" if self.pacing_guard else "OFF",
            self.description,
        ]


_PRESET_POLICIES = {
    "SAFE": QualityPresetPolicy(
        name="SAFE",
        description="Maximum repair effort for final narration and unattended overnight queues.",
        num_step=32,
        max_retries=3,
        max_split_depth=2,
        adaptive_retry=True,
        pacing_guard=True,
    ),
    "BALANCED": QualityPresetPolicy(
        name="BALANCED",
        description="Conservative speed-up while retaining adaptive retry, pacing guard and ASR verification.",
        num_step=28,
        max_retries=2,
        max_split_depth=2,
        adaptive_retry=True,
        pacing_guard=True,
    ),
    "FAST": QualityPresetPolicy(
        name="FAST",
        description="Preview/throughput mode: fewer diffusion steps and no automatic adaptive repair, but ASR verification stays on.",
        num_step=24,
        max_retries=1,
        max_split_depth=1,
        adaptive_retry=False,
        pacing_guard=False,
    ),
}


def quality_policy(value: Optional[str]) -> QualityPresetPolicy:
    return _PRESET_POLICIES[normalize_quality_preset(value)]


def quality_preset_rows() -> list[list[Any]]:
    return [quality_policy(name).comparison_row() for name in QUALITY_PRESETS]


def detect_hardware(torch_module: Any = None, *, device_index: int = 0) -> HardwareCapabilities:
    """Inspect local CUDA devices without allocating a model.

    The primary ``device_index`` is assumed to host OmniVoice.  When another
    CUDA GPU with at least 4 GB VRAM is available, it is preferred for Whisper
    ASR so verification does not compete with the TTS decoder for VRAM.  This
    maps well to Kaggle's common dual-T4 runtime: ``cuda:0`` for OmniVoice and
    ``cuda:1`` for ASR.
    """

    if torch_module is None:
        import torch as torch_module  # type: ignore

    cuda = getattr(torch_module, "cuda", None)
    available = bool(cuda is not None and cuda.is_available())
    if not available:
        return HardwareCapabilities(
            cuda_available=False,
            recommended_asr_device="cpu",
            recommended_preset="SAFE",
            notes=("Enable a CUDA GPU runtime for practical OmniVoice generation.",),
        )

    count = int(cuda.device_count())
    if count <= 0:
        return HardwareCapabilities(cuda_available=False)
    index = min(max(0, int(device_index)), count - 1)
    name = str(cuda.get_device_name(index))
    properties = cuda.get_device_properties(index)
    total_memory = float(getattr(properties, "total_memory", 0.0))
    vram_gb = total_memory / (1024**3) if total_memory > 0 else 0.0
    try:
        capability = tuple(int(item) for item in cuda.get_device_capability(index))
    except Exception:
        capability = None

    notes: list[str] = []
    # Primary-device policy.  A single 16 GB-class GPU keeps ASR on CPU so it
    # cannot steal decoder VRAM from OmniVoice.
    if vram_gb <= 18.0:
        preset = "BALANCED"
        asr_device = "cpu"
        notes.append("16 GB-class primary GPU: BALANCED protects long-running decoder stability.")
    elif vram_gb < 32.0:
        preset = "SAFE"
        asr_device = "cpu"
        notes.append("Enough primary VRAM for SAFE; CPU ASR remains the conservative single-GPU default.")
    else:
        preset = "SAFE"
        asr_device = f"cuda:{index}"
        notes.append("High-VRAM primary GPU: ASR can share CUDA if lower latency is preferred.")

    lowered = name.lower()
    if "t4" in lowered:
        preset = "BALANCED"
        notes.append("Tesla T4 detected: BALANCED is recommended for long continuous queues.")

    # Prefer a dedicated secondary accelerator for ASR.  This intentionally
    # happens after the single-GPU policy above so a dual T4 becomes
    # cuda:0=OmniVoice, cuda:1=Whisper rather than falling back to CPU.
    secondary_index: Optional[int] = None
    secondary_vram_gb = 0.0
    if count >= 2:
        for candidate in range(count):
            if candidate == index:
                continue
            try:
                candidate_properties = cuda.get_device_properties(candidate)
                candidate_memory = float(
                    getattr(candidate_properties, "total_memory", 0.0)
                )
                candidate_vram_gb = (
                    candidate_memory / (1024**3) if candidate_memory > 0 else 0.0
                )
            except Exception:
                candidate_vram_gb = 0.0
            if candidate_vram_gb >= 4.0:
                secondary_index = candidate
                secondary_vram_gb = candidate_vram_gb
                break

    if secondary_index is not None:
        asr_device = f"cuda:{secondary_index}"
        secondary_name = str(cuda.get_device_name(secondary_index))
        notes.append(
            f"Dedicated ASR GPU detected: use {asr_device} ({secondary_name}, "
            f"{secondary_vram_gb:.1f} GB) for Whisper and keep cuda:{index} for OmniVoice."
        )

    return HardwareCapabilities(
        cuda_available=True,
        device_count=count,
        device_index=index,
        device_name=name,
        total_vram_gb=vram_gb,
        compute_capability=capability,
        recommended_asr_device=asr_device,
        recommended_preset=preset,
        notes=tuple(dict.fromkeys(notes)),
    )


@dataclass
class HardwareQualitySettings:
    version: int = 1
    default_preset: str = "SAFE"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "HardwareQualitySettings":
        return cls(
            version=int(payload.get("version", 1)),
            default_preset=normalize_quality_preset(payload.get("default_preset", "SAFE")),
        )


class HardwareQualitySettingsStore:
    """Small workspace-level default. Per-project overrides remain in studio.json."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser()
        self.path = self.workspace / HARDWARE_SETTINGS_FILE
        self.workspace.mkdir(parents=True, exist_ok=True)

    def load(self) -> HardwareQualitySettings:
        if not self.path.exists():
            return HardwareQualitySettings()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return HardwareQualitySettings.from_dict(payload)
        except Exception:
            return HardwareQualitySettings()

    def save(self, settings: HardwareQualitySettings) -> Path:
        settings.default_preset = normalize_quality_preset(settings.default_preset)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(self.path)
        return self.path

    def set_default(self, preset: str) -> HardwareQualitySettings:
        settings = HardwareQualitySettings(default_preset=normalize_quality_preset(preset))
        self.save(settings)
        return settings
