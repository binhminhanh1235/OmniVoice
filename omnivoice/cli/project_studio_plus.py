#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Project Studio with reliable generation and preview-before-render.

The original Project Studio keeps a hidden ``gr.State`` for the loaded project.
That is convenient internally but easy to misuse: selecting a project in the
visible dropdown does not necessarily update the hidden state.  The fixed
Generate panel below deliberately uses the visible project path as its source
of truth, performs preflight checks, surfaces errors as Gradio popups, and
persists a traceback beside the project for post-mortem debugging.
"""

from __future__ import annotations

import argparse
import json
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _split_sections(value: str | None) -> Optional[list[str]]:
    if not value or not value.strip():
        return None
    items = [part.strip().upper() for part in value.replace(";", ",").split(",")]
    return [item for item in items if item]


def _error_path(project_path: str | Path) -> Path:
    return Path(project_path).expanduser() / "generation_error.json"


def _write_generation_error(project_path: str | Path, exc: Exception) -> Path:
    path = _error_path(project_path)
    payload = {
        "timestamp": _utc_now(),
        "error_type": type(exc).__name__,
        "error": str(exc),
        "traceback": traceback.format_exc(),
    }
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Could not persist generation error report")
    return path


def _preflight(
    controller: ProjectStudioController,
    project_path: str,
    voice_name: str,
    variant: str,
    sections: str | None,
) -> tuple[Any, Optional[list[str]], str]:
    if not project_path:
        raise ValueError("Select a project first")
    if not voice_name:
        raise ValueError("Select a saved voice first")

    project = controller.load_project(project_path)
    controller.voices.get(voice_name)
    preferred = (variant or "AUTO").upper()
    selected = _split_sections(sections)
    selected_set = set(selected) if selected else None

    total = 0
    verified = 0
    pending = 0
    styles: set[str] = set()
    resolutions: dict[str, str] = {}

    for section in project.manifest.sections:
        if selected_set is not None and section.id not in selected_set:
            continue
        for beat in section.beats:
            styles.add(beat.style)
            resolved, fallback = controller.voices.resolve_variant(
                voice_name,
                style=beat.style,
                preferred_variant=preferred,
            )
            resolutions[beat.style] = resolved + (" (fallback)" if fallback else "")
            for chunk in beat.chunks:
                total += 1
                if chunk.status == "verified":
                    verified += 1
                else:
                    pending += 1

    if total == 0:
        raise ValueError("The selected project/sections contain no chunks")

    style_text = ", ".join(
        f"{style}->{resolutions[style]}" for style in sorted(styles)
    ) or "DEFAULT"
    summary = (
        f"Preflight OK. chunks={total}, pending={pending}, verified={verified}; "
        f"voice={voice_name}, variant={preferred}; styles: {style_text}."
    )
    return project, selected, summary


def build_fixed_generate_demo(model: Any, workspace: str | Path):
    import gradio as gr

    controller = ProjectStudioController(model, workspace)

    def list_projects():
        return controller.list_projects()

    def list_voices():
        return controller.voices.voice_names()

    projects = list_projects()
    voices = list_voices()
    initial_project = projects[0] if projects else None
    initial_voice = voices[0] if voices else None
    initial_variants = (
        controller.voices.variant_choices(initial_voice) if initial_voice else []
    )

    def refresh():
        project_items = list_projects()
        voice_items = list_voices()
        voice = voice_items[0] if voice_items else None
        variants = controller.voices.variant_choices(voice) if voice else []
        return (
            gr.update(choices=project_items, value=(project_items[0] if project_items else None)),
            gr.update(choices=voice_items, value=voice),
            gr.update(choices=variants, value=("AUTO" if variants else None)),
            "Ready. Select the visible project below; no hidden project state is used.",
        )

    def variants_for_voice(name):
        variants = controller.voices.variant_choices(name) if name else []
        return gr.update(choices=variants, value=("AUTO" if variants else None))

    def preflight(project_path, voice_name, variant, sections):
        try:
            _, _, summary = _preflight(
                controller, project_path, voice_name, variant or "AUTO", sections
            )
            return summary
        except Exception as exc:
            raise gr.Error(f"Preflight failed: {type(exc).__name__}: {exc}")

    def generate(project_path, voice_name, variant, language, sections, resume, strict):
        progress = gr.Progress(track_tqdm=False)
        progress(0.05, desc="Checking project and voice")
        try:
            project, selected, summary = _preflight(
                controller, project_path, voice_name, variant or "AUTO", sections
            )
            progress(0.12, desc="Starting OmniVoice generation")
            logger.info("Project Studio generation: %s", summary)
            project = controller.generate(
                project.root,
                voice_name=voice_name,
                voice_variant=variant or "AUTO",
                language=language or None,
                section_ids=selected,
                resume=bool(resume),
                strict=bool(strict),
            )
            progress(0.95, desc="Refreshing generated outputs")
            rows, chunks, section_ids = controller.project_view(project.root)
            first_section = section_ids[0] if section_ids else None
            first_audio = (
                str(controller.section_audio(project.root, first_section))
                if first_section
                else None
            )
            verified_sections = sum(row[-1] == "verified" for row in rows)
            pending_chunks = sum(
                chunk.status != "verified"
                for section in project.manifest.sections
                for beat in section.beats
                for chunk in beat.chunks
            )
            progress(1.0, desc="Done")
            message = (
                f"Generation finished. sections verified={verified_sections}/{len(rows)}, "
                f"remaining chunks={pending_chunks}."
            )
            return (
                rows,
                gr.update(choices=section_ids, value=first_section),
                first_audio,
                message,
            )
        except Exception as exc:
            logger.exception("Fixed Project Studio generation failed")
            error_file = _write_generation_error(project_path, exc) if project_path else None
            detail = f"{type(exc).__name__}: {exc}"
            if error_file is not None:
                detail += f" | error log: {error_file}"
            raise gr.Error(f"Generate failed: {detail}")

    def play_section(project_path, section_id):
        if not project_path or not section_id:
            return None
        try:
            return str(controller.section_audio(project_path, section_id))
        except Exception as exc:
            raise gr.Error(f"Cannot play section: {exc}")

    def merge(project_path, allow_unverified):
        if not project_path:
            raise gr.Error("Select a project first")
        try:
            output = controller.merge_project(
                project_path,
                require_verified=not bool(allow_unverified),
            )
            return str(output), f"Merged: {output}"
        except Exception as exc:
            raise gr.Error(f"Merge failed: {type(exc).__name__}: {exc}")

    headers = [
        "Section", "Title", "Style", "Planned", "Beats", "Chunks",
        "Verified", "Unverified", "Status",
    ]

    with gr.Blocks(title="Generate / Resume") as demo:
        gr.Markdown(
            "# Generate / Resume\n"
            "This is the fixed generation path. It uses the **visible Project dropdown** "
            "directly, not a hidden Gradio state. Run **Preflight** first if generation "
            "ever appears to finish immediately. Runtime failures show as a popup and "
            "are also saved as `generation_error.json` inside the project folder."
        )
        with gr.Row():
            project = gr.Dropdown(
                label="Project (source of truth)",
                choices=projects,
                value=initial_project,
            )
            voice = gr.Dropdown(label="Voice", choices=voices, value=initial_voice)
            variant = gr.Dropdown(
                label="Voice variant",
                choices=initial_variants,
                value=("AUTO" if initial_variants else None),
            )
            language = gr.Textbox(label="Language", value="en")
        sections = gr.Textbox(
            label="Sections (optional)",
            placeholder="S03,S07,S10 - empty means all",
        )
        with gr.Row():
            refresh_button = gr.Button("Refresh Projects / Voices")
            preflight_button = gr.Button("Preflight")
            resume = gr.Checkbox(label="Resume / skip verified chunks", value=True)
            strict = gr.Checkbox(label="Exact mode", value=False)
            generate_button = gr.Button("Generate / Resume", variant="primary")
        status = gr.Markdown("Ready.")
        status_table = gr.Dataframe(headers=headers, interactive=False)
        with gr.Row():
            section_picker = gr.Dropdown(label="Generated section", choices=[])
            play_button = gr.Button("Play selected section")
        section_audio = gr.Audio(label="Section audio", type="filepath")
        with gr.Row():
            allow_unverified = gr.Checkbox(label="Allow merge with unverified", value=False)
            merge_button = gr.Button("Merge full.wav")
        merged_audio = gr.Audio(label="Merged project", type="filepath")

        refresh_button.click(
            refresh,
            outputs=[project, voice, variant, status],
        )
        voice.change(variants_for_voice, inputs=voice, outputs=variant)
        preflight_button.click(
            preflight,
            inputs=[project, voice, variant, sections],
            outputs=status,
        )
        generate_button.click(
            generate,
            inputs=[project, voice, variant, language, sections, resume, strict],
            outputs=[status_table, section_picker, section_audio, status],
        )
        section_picker.change(
            play_section,
            inputs=[project, section_picker],
            outputs=section_audio,
        )
        play_button.click(
            play_section,
            inputs=[project, section_picker],
            outputs=section_audio,
        )
        merge_button.click(
            merge,
            inputs=[project, allow_unverified],
            outputs=[merged_audio, status],
        )

    return demo


def build_preview_demo(model: Any, workspace: str | Path):
    import gradio as gr

    controller = ProjectStudioController(model, workspace)

    initial_projects = controller.list_projects()
    initial_voices = controller.voices.voice_names()
    initial_voice = initial_voices[0] if initial_voices else None
    initial_variants = (
        controller.voices.variant_choices(initial_voice) if initial_voice else []
    )

    def refresh():
        projects = controller.list_projects()
        voices = controller.voices.voice_names()
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
        return gr.update(choices=variants, value=("AUTO" if variants else None))

    def generate_previews(project_path, voice_name, variant, language, strict):
        if not project_path:
            raise gr.Error("Select a project first")
        if not voice_name:
            raise gr.Error("Select a saved voice first")
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
            details = []
            for label in ("opening", "middle", "ending"):
                item = by_label.get(label)
                if item:
                    fallback = " fallback" if item.voice_variant_fallback else ""
                    details.append(
                        f"{label}: {item.target.section_id}/{item.target.chunk_id} "
                        f"[{item.target.style}] -> {item.voice_variant}{fallback}"
                    )
            return (
                by_label.get("opening").audio_file if by_label.get("opening") else None,
                by_label.get("middle").audio_file if by_label.get("middle") else None,
                by_label.get("ending").audio_file if by_label.get("ending") else None,
                "Preview complete. " + " | ".join(details),
            )
        except Exception as exc:
            logger.exception("Preview generation failed")
            raise gr.Error(f"Preview failed: {type(exc).__name__}: {exc}")

    with gr.Blocks(title="Preview Before Full Render") as demo:
        gr.Markdown(
            "# Preview Before Full Render\n"
            "Generate opening / middle / ending samples without changing project status."
        )
        with gr.Row():
            project = gr.Dropdown(
                label="Project", choices=initial_projects,
                value=(initial_projects[0] if initial_projects else None),
            )
            voice = gr.Dropdown(label="Voice", choices=initial_voices, value=initial_voice)
            variant = gr.Dropdown(
                label="Voice variant", choices=initial_variants,
                value=("AUTO" if initial_variants else None),
            )
            language = gr.Textbox(label="Language", value="en")
        with gr.Row():
            strict = gr.Checkbox(label="Exact mode", value=False)
            refresh_button = gr.Button("Refresh")
            preview_button = gr.Button("Generate 3 Previews", variant="primary")
        with gr.Row():
            opening = gr.Audio(label="Opening", type="filepath")
            middle = gr.Audio(label="Middle", type="filepath")
            ending = gr.Audio(label="Ending", type="filepath")
        status = gr.Markdown()
        voice.change(variants_for_voice, inputs=voice, outputs=variant)
        refresh_button.click(refresh, outputs=[project, voice, variant, status])
        preview_button.click(
            generate_previews,
            inputs=[project, voice, variant, language, strict],
            outputs=[opening, middle, ending, status],
        )
    return demo


def build_demo(model: Any, workspace: str | Path):
    import gradio as gr

    fixed = build_fixed_generate_demo(model, workspace)
    setup = build_project_demo(model, workspace)
    preview = build_preview_demo(model, workspace)
    return gr.TabbedInterface(
        [fixed, setup, preview],
        ["Generate / Resume", "Project Setup / Legacy", "Preview Before Render"],
        title="OmniVoice Project Studio",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch OmniVoice Project Studio")
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
    logger.info("Loading OmniVoice model=%s device=%s", args.model, device)
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
        show_error=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
