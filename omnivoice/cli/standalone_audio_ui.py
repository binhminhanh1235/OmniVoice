#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Standalone paragraph generation UI for OmniVoice Studio.

This surface intentionally does not create or mutate a Project Studio project.
It reuses ``StudioCommandService.generate_audio_job`` so saved voices, robust
quality verification, artifact metadata and output layout stay aligned with
REST/MCP/CLI.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from omnivoice.cli.project_studio import _LANGUAGE_CHOICES
from omnivoice.hardware_quality import QUALITY_PRESETS
from omnivoice.services.studio_commands import StudioCommandService


class _StandaloneUiContext:
    """Minimal JobContext-compatible adapter for an interactive Gradio request."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.job_id = f"ui_{uuid.uuid4().hex}"
        self.payload = payload
        self.messages: list[str] = []

    def emit(
        self,
        message: str,
        *,
        progress: Optional[float] = None,
        event: str = "progress",
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        del progress, event, data
        self.messages.append(str(message))

    def checkpoint(self) -> None:
        return None


def standalone_audio_payload(
    text: str,
    *,
    voice_name: Optional[str] = None,
    voice_variant: Optional[str] = "AUTO",
    language: Optional[str] = "en",
    instruct: Optional[str] = None,
    speed: Optional[float] = 1.0,
    quality_preset: Optional[str] = None,
) -> dict[str, Any]:
    """Build the protocol-neutral payload used by standalone audio generation."""

    normalized_text = str(text or "").strip()
    if not normalized_text:
        raise ValueError("Enter a paragraph to generate.")

    payload: dict[str, Any] = {
        "text": normalized_text,
        "voice_variant": str(voice_variant or "AUTO").strip().upper(),
        "language": str(language or "en").strip() or "en",
        "style": "DEFAULT",
    }
    if voice_name and str(voice_name).strip():
        payload["voice_name"] = str(voice_name).strip()
    if instruct and str(instruct).strip():
        payload["instruct"] = str(instruct).strip()
    if speed is not None:
        payload["speed"] = float(speed)
    if quality_preset and str(quality_preset).strip():
        payload["quality_preset"] = str(quality_preset).strip().upper()
    return payload


def standalone_audio_status(
    result: dict[str, Any],
    *,
    requested_quality: Optional[str] = None,
) -> str:
    """Render a truthful quality summary for a completed Quick Audio run."""

    resolved_voice = result.get("voice_name") or "model default"
    resolved_variant = result.get("voice_variant") or "default"
    quality = result.get("quality_preset") or requested_quality or "workspace default"
    chunk_count = max(1, int(result.get("chunk_count") or 1))
    unverified_chunks = max(0, int(result.get("unverified_chunks") or 0))

    if result.get("verified"):
        verification = f"ASR verified across **{chunk_count}** semantic chunk(s)"
    else:
        verification = (
            f"⚠️ **Needs review**: {unverified_chunks or 1}/{chunk_count} chunk(s) "
            "did not pass ASR verification. Regenerate with **SAFE** before final use"
        )

    return (
        f"{verification} · voice **{resolved_voice}/{resolved_variant}** · "
        f"quality **{quality}** · saved under `artifacts/audio` · "
        "no project was created."
    )


def build_standalone_audio_demo(
    model: Any,
    workspace: str | Path,
    *,
    controller_cls: type,
):
    """Build a small independent-text tab backed by StudioCommandService."""

    import gradio as gr

    controller = controller_cls(model, workspace)
    commands = StudioCommandService(model, workspace, controller=controller)
    voices = controller.voices.voice_names()
    initial_voice = voices[0] if voices else None
    initial_variants = (
        controller.voices.variant_choices(initial_voice) if initial_voice else []
    )
    initial_variant = (
        "AUTO"
        if "AUTO" in initial_variants
        else (initial_variants[0] if initial_variants else None)
    )
    initial_quality = controller.workspace_quality_preset()

    def variants_for_voice(name):
        variants = controller.voices.variant_choices(name) if name else []
        value = "AUTO" if "AUTO" in variants else (variants[0] if variants else None)
        return gr.update(choices=variants, value=value)

    def refresh_voices(current):
        items = controller.voices.voice_names()
        value = current if current in items else (items[0] if items else None)
        variants = controller.voices.variant_choices(value) if value else []
        variant = "AUTO" if "AUTO" in variants else (variants[0] if variants else None)
        return (
            gr.update(choices=items, value=value),
            gr.update(choices=variants, value=variant),
        )

    def generate(text, voice_name, voice_variant, language, instruct, speed, quality):
        try:
            payload = standalone_audio_payload(
                text,
                voice_name=voice_name,
                voice_variant=voice_variant,
                language=language,
                instruct=instruct,
                speed=speed,
                quality_preset=quality,
            )
            ctx = _StandaloneUiContext(payload)
            result = commands.generate_audio_job(ctx)
            artifact = result.get("artifact") or {}
            output_path = artifact.get("path")
            if not output_path:
                raise RuntimeError("Standalone generation completed without an audio artifact")
            return (
                str(output_path),
                standalone_audio_status(result, requested_quality=quality),
            )
        except Exception as exc:
            raise gr.Error(f"Quick Audio failed: {type(exc).__name__}: {exc}") from exc

    with gr.Blocks(title="Quick Audio") as demo:
        gr.Markdown(
            """
## Quick Audio
Generate one independent paragraph without creating a project. Longer text is
split into semantic chunks, checked with ASR and retried before the WAV is saved.
"""
        )
        with gr.Row():
            with gr.Column(scale=3):
                text = gr.Textbox(
                    label="Paragraph",
                    lines=12,
                    placeholder="Paste or type the paragraph you want OmniVoice to read...",
                )
                with gr.Row():
                    voice = gr.Dropdown(
                        label="Saved voice",
                        choices=voices,
                        value=initial_voice,
                        info="Optional. Add or manage voices in Voice Library.",
                    )
                    variant = gr.Dropdown(
                        label="Variant",
                        choices=initial_variants,
                        value=initial_variant,
                    )
                    refresh = gr.Button("Refresh voices", scale=0)
                language = gr.Dropdown(
                    label="Language",
                    choices=_LANGUAGE_CHOICES,
                    value="en",
                    allow_custom_value=False,
                    interactive=True,
                    info="English is first; select another supported language when needed.",
                )
                with gr.Accordion("Optional generation settings", open=False):
                    instruct = gr.Textbox(
                        label="Instruct",
                        lines=2,
                        placeholder="Optional speaking instruction...",
                    )
                    with gr.Row():
                        speed = gr.Slider(
                            minimum=0.5,
                            maximum=1.5,
                            value=1.0,
                            step=0.05,
                            label="Speed",
                        )
                        quality = gr.Dropdown(
                            label="Quality preset",
                            choices=list(QUALITY_PRESETS),
                            value=initial_quality,
                        )
                generate_button = gr.Button("Generate Quick Audio", variant="primary")
            with gr.Column(scale=2):
                output = gr.Audio(label="Generated audio", type="filepath")
                status = gr.Markdown("Ready. This mode does not create a project.")

        voice.change(variants_for_voice, inputs=voice, outputs=variant)
        refresh.click(refresh_voices, inputs=voice, outputs=[voice, variant])
        generate_button.click(
            generate,
            inputs=[text, voice, variant, language, instruct, speed, quality],
            outputs=[output, status],
        )

    return demo
