#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Project Studio with a non-destructive Preview-before-render panel."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import torch

from omnivoice import OmniVoice
from omnivoice.cli.project_studio import (
    ProjectStudioController,
    build_demo as build_project_demo,
    default_workspace,
)
from omnivoice.preview import ProjectPreviewGenerator
from omnivoice.utils.common import get_best_device

logger = logging.getLogger(__name__)


def build_preview_demo(model: Any, workspace: str | Path):
    import gradio as gr

    controller = ProjectStudioController(model, workspace)

    def project_choices():
        return controller.list_projects()

    def voice_choices():
        return controller.voices.voice_names()

    initial_projects = project_choices()
    initial_voices = voice_choices()
    initial_voice = initial_voices[0] if initial_voices else None
    initial_variants = (
        controller.voices.variant_choices(initial_voice)
        if initial_voice
        else []
    )

    def refresh():
        projects = project_choices()
        voices = voice_choices()
        voice = voices[0] if voices else None
        variants = controller.voices.variant_choices(voice) if voice else []
        return (
            gr.update(choices=projects, value=(projects[0] if projects else None)),
            gr.update(choices=voices, value=voice),
            gr.update(choices=variants, value=("AUTO" if variants else None)),
            f"Found {len(projects)} projects and {len(voices)} voices.",
        )

    def variants_for_voice(name):
        variants = controller.voices.variant_choices(name) if name else []
        return gr.update(
            choices=variants,
            value=("AUTO" if variants else None),
        )

    def generate_previews(project_path, voice_name, variant, language, strict):
        if not project_path:
            return None, None, None, "Select a project first."
        if not voice_name:
            return None, None, None, "Select a saved voice first."

        try:
            project = controller.load_project(project_path)
            preview = ProjectPreviewGenerator(
                model,
                controller.voices,
                voice_name=voice_name,
                preferred_variant=(variant or "AUTO"),
            )
            results = preview.generate(
                project,
                robust_config=controller.robust_config(strict=bool(strict)),
                generation_config=controller.generation_config(),
                language=language or None,
                strict=bool(strict),
            )
            by_label = {item.target.label: item for item in results}

            def audio(label):
                item = by_label.get(label)
                return item.audio_file if item else None

            details = []
            for label in ("opening", "middle", "ending"):
                item = by_label.get(label)
                if item is None:
                    continue
                fallback = " fallback" if item.voice_variant_fallback else ""
                verified = "verified" if item.verified else "unverified"
                details.append(
                    f"{label}: {item.target.section_id}/{item.target.chunk_id} "
                    f"[{item.target.style}] -> {item.voice_variant}{fallback}, {verified}"
                )
            message = "Preview complete. " + " | ".join(details)
            return audio("opening"), audio("middle"), audio("ending"), message
        except Exception as exc:
            logger.exception("Preview generation failed")
            return None, None, None, f"Preview error: {type(exc).__name__}: {exc}"

    with gr.Blocks(title="Preview Before Full Render") as preview_demo:
        gr.Markdown(
            "# Preview Before Full Render\n"
            "Generate three representative samples without changing project "
            "checkpoint/status. Listen first; render the full project only after "
            "the voice + Style Bank setup sounds right."
        )
        with gr.Row():
            project = gr.Dropdown(
                label="Project",
                choices=initial_projects,
                value=(initial_projects[0] if initial_projects else None),
            )
            voice = gr.Dropdown(
                label="Voice",
                choices=initial_voices,
                value=initial_voice,
            )
            variant = gr.Dropdown(
                label="Voice variant",
                info="AUTO follows each preview chunk's [WARM]/[SOFT]/... style.",
                choices=initial_variants,
                value=("AUTO" if initial_variants else None),
            )
            language = gr.Textbox(label="Language", value="en")

        with gr.Row():
            strict = gr.Checkbox(
                label="Exact mode: reject unverified preview",
                value=False,
            )
            refresh_button = gr.Button("Refresh Projects / Voices")
            preview_button = gr.Button("Generate 3 Previews", variant="primary")

        with gr.Row():
            opening = gr.Audio(label="Opening", type="filepath")
            middle = gr.Audio(label="Middle", type="filepath")
            ending = gr.Audio(label="Ending", type="filepath")
        status = gr.Markdown()

        voice.change(variants_for_voice, inputs=voice, outputs=variant)
        refresh_button.click(
            refresh,
            outputs=[project, voice, variant, status],
        )
        preview_button.click(
            generate_previews,
            inputs=[project, voice, variant, language, strict],
            outputs=[opening, middle, ending, status],
        )

    return preview_demo


def build_demo(model: Any, workspace: str | Path):
    import gradio as gr

    studio = build_project_demo(model, workspace)
    preview = build_preview_demo(model, workspace)
    return gr.TabbedInterface(
        [studio, preview],
        ["Project Studio", "Preview Before Render"],
        title="OmniVoice Project Studio",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch OmniVoice Project Studio with preview-before-render"
    )
    parser.add_argument("--model", default="k2-fsa/OmniVoice")
    parser.add_argument("--device", default=None)
    parser.add_argument("--workspace", default=str(default_workspace()))
    parser.add_argument("--asr-model", default="openai/whisper-small.en")
    parser.add_argument("--asr-device", default="cpu")
    parser.add_argument("--ip", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true", default=False)
    return parser


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )
    args = build_parser().parse_args(argv)
    device = args.device or get_best_device()
    model = OmniVoice.from_pretrained(
        args.model,
        device_map=device,
        dtype=torch.float16,
        load_asr=True,
        asr_model_name=args.asr_model,
        asr_device=args.asr_device,
    )
    demo = build_demo(model, args.workspace)
    demo.queue().launch(
        server_name=args.ip,
        server_port=args.port,
        share=args.share,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
