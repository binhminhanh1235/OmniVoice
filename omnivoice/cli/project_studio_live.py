#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Project Studio generation UI with live per-section progress.

This module keeps the visible project selector as the source of truth and
streams Gradio updates while each section is generated. The section table is
therefore populated before inference begins and remains visible throughout a
long render instead of disappearing behind one blocking callback.
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
from omnivoice.cli.project_studio_plus import build_preview_demo
from omnivoice.utils.common import get_best_device

logger = logging.getLogger(__name__)


STATUS_HEADERS = [
    "Section",
    "Title",
    "Style",
    "Planned",
    "Beats",
    "Chunks",
    "Verified",
    "Unverified",
    "Live status",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _split_sections(value: str | None) -> Optional[list[str]]:
    if not value or not value.strip():
        return None
    items = [part.strip().upper() for part in value.replace(";", ",").split(",")]
    return [item for item in items if item]


def _error_path(project_path: str | Path) -> Path:
    return Path(project_path).expanduser() / "generation_error.json"


def _write_generation_error(
    project_path: str | Path,
    exc: Exception,
    *,
    section_id: Optional[str] = None,
) -> Path:
    path = _error_path(project_path)
    payload = {
        "timestamp": _utc_now(),
        "section": section_id,
        "error_type": type(exc).__name__,
        "error": str(exc),
        "traceback": traceback.format_exc(),
    }
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("Could not persist generation error report")
    return path


def _decorate_status_rows(
    rows: list[list[Any]],
    target_ids: list[str],
    live_status: dict[str, str],
) -> list[list[Any]]:
    """Decorate persistent Project rows with transient UI-only live states."""

    targets = set(target_ids)
    output: list[list[Any]] = []
    for row in rows:
        item = list(row)
        section_id = str(item[0])
        persistent = str(item[-1])
        if section_id in live_status:
            item[-1] = live_status[section_id]
        elif section_id not in targets:
            item[-1] = f"{persistent} · not selected"
        elif persistent == "verified":
            item[-1] = "VERIFIED ✓"
        elif persistent == "unverified":
            item[-1] = "UNVERIFIED ⚠"
        else:
            item[-1] = "QUEUED"
        output.append(item)
    return output


def _section_chunk_counts(section: Any) -> tuple[int, int]:
    chunks = [chunk for beat in section.beats for chunk in beat.chunks]
    total = len(chunks)
    verified = sum(chunk.status == "verified" for chunk in chunks)
    return total, verified


def _preflight(
    controller: ProjectStudioController,
    project_path: str,
    voice_name: str,
    variant: str,
    sections: str | None,
) -> tuple[Any, list[str], str]:
    if not project_path:
        raise ValueError("Select a project first")
    if not voice_name:
        raise ValueError("Select a saved voice first")

    project = controller.load_project(project_path)
    controller.voices.get(voice_name)
    preferred = (variant or "AUTO").upper()
    selected = _split_sections(sections)

    available = [section.id for section in project.manifest.sections]
    available_set = set(available)
    if selected:
        unknown = sorted(set(selected) - available_set)
        if unknown:
            raise ValueError(f"Unknown sections: {', '.join(unknown)}")
        selected_set = set(selected)
        target_ids = [item for item in available if item in selected_set]
    else:
        target_ids = available

    total = 0
    verified = 0
    styles: set[str] = set()
    resolutions: dict[str, str] = {}

    for section in project.manifest.sections:
        if section.id not in target_ids:
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

    if total == 0:
        raise ValueError("The selected project/sections contain no chunks")

    pending = total - verified
    style_text = ", ".join(
        f"{style}->{resolutions[style]}" for style in sorted(styles)
    ) or "DEFAULT"
    summary = (
        f"Preflight OK · sections={len(target_ids)} · chunks={total} · "
        f"pending={pending} · verified={verified} · voice={voice_name} · "
        f"variant={preferred} · styles: {style_text}."
    )
    return project, target_ids, summary


def _project_snapshot(
    controller: ProjectStudioController,
    project_path: str | Path,
    target_ids: list[str],
    live_status: Optional[dict[str, str]] = None,
) -> tuple[list[list[Any]], list[str]]:
    project = controller.load_project(project_path)
    rows, _, generated_sections = controller.project_view(project.root)
    return (
        _decorate_status_rows(rows, target_ids, live_status or {}),
        generated_sections,
    )


def build_live_generate_demo(model: Any, workspace: str | Path):
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

    if initial_project:
        initial_loaded = controller.load_project(initial_project)
        initial_targets = [section.id for section in initial_loaded.manifest.sections]
        initial_rows, initial_generated = _project_snapshot(
            controller,
            initial_project,
            initial_targets,
        )
    else:
        initial_rows, initial_generated = [], []

    def refresh():
        project_items = list_projects()
        voice_items = list_voices()
        voice_name = voice_items[0] if voice_items else None
        variants = controller.voices.variant_choices(voice_name) if voice_name else []
        selected_project = project_items[0] if project_items else None
        if selected_project:
            loaded = controller.load_project(selected_project)
            target_ids = [section.id for section in loaded.manifest.sections]
            rows, generated_sections = _project_snapshot(
                controller,
                selected_project,
                target_ids,
            )
        else:
            rows, generated_sections = [], []
        return (
            gr.update(choices=project_items, value=selected_project),
            gr.update(choices=voice_items, value=voice_name),
            gr.update(choices=variants, value=("AUTO" if variants else None)),
            rows,
            gr.update(
                choices=generated_sections,
                value=(generated_sections[0] if generated_sections else None),
            ),
            "Ready.",
            "No generation running.",
        )

    def variants_for_voice(name):
        variants = controller.voices.variant_choices(name) if name else []
        return gr.update(choices=variants, value=("AUTO" if variants else None))

    def show_project(project_path):
        if not project_path:
            return [], gr.update(choices=[], value=None), None, "Select a project."
        try:
            loaded = controller.load_project(project_path)
            target_ids = [section.id for section in loaded.manifest.sections]
            rows, generated_sections = _project_snapshot(
                controller,
                project_path,
                target_ids,
            )
            first = generated_sections[0] if generated_sections else None
            audio = (
                str(controller.section_audio(project_path, first))
                if first
                else None
            )
            return (
                rows,
                gr.update(choices=generated_sections, value=first),
                audio,
                f"Loaded {loaded.manifest.title} · {len(target_ids)} sections.",
            )
        except Exception as exc:
            raise gr.Error(f"Cannot load project: {type(exc).__name__}: {exc}")

    def preflight(project_path, voice_name, variant, sections):
        try:
            project_obj, target_ids, summary = _preflight(
                controller,
                project_path,
                voice_name,
                variant or "AUTO",
                sections,
            )
            rows, generated_sections = _project_snapshot(
                controller,
                project_obj.root,
                target_ids,
            )
            return (
                rows,
                gr.update(
                    choices=generated_sections,
                    value=(generated_sections[0] if generated_sections else None),
                ),
                summary,
            )
        except Exception as exc:
            raise gr.Error(f"Preflight failed: {type(exc).__name__}: {exc}")

    def generate_stream(
        project_path,
        voice_name,
        variant,
        language,
        sections,
        resume,
        strict,
    ):
        """Generate one section at a time and yield UI state after every transition."""

        try:
            project_obj, target_ids, summary = _preflight(
                controller,
                project_path,
                voice_name,
                variant or "AUTO",
                sections,
            )
        except Exception as exc:
            raise gr.Error(f"Preflight failed: {type(exc).__name__}: {exc}")

        live_status: dict[str, str] = {}
        generated_ids: list[str] = []
        current_audio: Optional[str] = None

        # Important: first yield happens before any expensive inference. This keeps
        # the section table visible instead of leaving Gradio on a blank spinner.
        rows, generated_ids = _project_snapshot(
            controller,
            project_obj.root,
            target_ids,
            live_status,
        )
        selected_audio = generated_ids[0] if generated_ids else None
        if selected_audio:
            current_audio = str(
                controller.section_audio(project_obj.root, selected_audio)
            )
        yield (
            rows,
            gr.update(choices=generated_ids, value=selected_audio),
            current_audio,
            summary,
            f"Queued {len(target_ids)} sections. Starting now…",
        )

        total_sections = len(target_ids)
        for index, section_id in enumerate(target_ids, start=1):
            project_obj = controller.load_project(project_obj.root)
            section = project_obj.get_section(section_id)
            total_chunks, verified_before = _section_chunk_counts(section)

            if bool(resume) and total_chunks > 0 and verified_before == total_chunks:
                live_status[section_id] = (
                    f"SKIPPED ✓ · already verified · {verified_before}/{total_chunks} chunks"
                )
                rows, generated_ids = _project_snapshot(
                    controller,
                    project_obj.root,
                    target_ids,
                    live_status,
                )
                if section.audio_file:
                    current_audio = str(project_obj.root / section.audio_file)
                yield (
                    rows,
                    gr.update(choices=generated_ids, value=section_id),
                    current_audio,
                    f"{section_id} skipped because all chunks are already verified.",
                    f"Progress {index}/{total_sections} · {section_id} SKIPPED",
                )
                continue

            live_status[section_id] = (
                f"GENERATING… · section {index}/{total_sections} · "
                f"{verified_before}/{total_chunks} chunks already verified"
            )
            rows, generated_ids = _project_snapshot(
                controller,
                project_obj.root,
                target_ids,
                live_status,
            )
            yield (
                rows,
                gr.update(
                    choices=generated_ids,
                    value=(generated_ids[-1] if generated_ids else None),
                ),
                current_audio,
                f"Generating {section_id}…",
                f"Progress {index}/{total_sections} · {section_id} GENERATING",
            )

            try:
                project_obj = controller.generate(
                    project_obj.root,
                    voice_name=voice_name,
                    voice_variant=variant or "AUTO",
                    language=language or None,
                    section_ids=[section_id],
                    resume=bool(resume),
                    strict=bool(strict),
                )
            except Exception as exc:
                logger.exception("Generation failed at section %s", section_id)
                error_file = _write_generation_error(
                    project_obj.root,
                    exc,
                    section_id=section_id,
                )
                live_status[section_id] = f"FAILED ✗ · {type(exc).__name__}: {exc}"
                rows, generated_ids = _project_snapshot(
                    controller,
                    project_obj.root,
                    target_ids,
                    live_status,
                )
                yield (
                    rows,
                    gr.update(
                        choices=generated_ids,
                        value=(generated_ids[-1] if generated_ids else None),
                    ),
                    current_audio,
                    f"Generation stopped at {section_id}. Error log: {error_file}",
                    f"Progress {index}/{total_sections} · {section_id} FAILED",
                )
                gr.Warning(
                    f"Generation failed at {section_id}. See {error_file} for traceback."
                )
                return

            project_obj = controller.load_project(project_obj.root)
            section = project_obj.get_section(section_id)
            total_chunks, verified_after = _section_chunk_counts(section)
            if section.status == "verified":
                live_status[section_id] = (
                    f"VERIFIED ✓ · {verified_after}/{total_chunks} chunks"
                )
            elif section.status == "unverified":
                live_status[section_id] = (
                    f"UNVERIFIED ⚠ · {verified_after}/{total_chunks} chunks verified"
                )
            else:
                live_status[section_id] = (
                    f"{section.status.upper()} · {verified_after}/{total_chunks} chunks verified"
                )

            rows, generated_ids = _project_snapshot(
                controller,
                project_obj.root,
                target_ids,
                live_status,
            )
            if section.audio_file:
                current_audio = str(project_obj.root / section.audio_file)

            yield (
                rows,
                gr.update(choices=generated_ids, value=section_id),
                current_audio,
                f"Finished {section_id}: {section.status}.",
                f"Progress {index}/{total_sections} · {section_id} {section.status.upper()}",
            )

        project_obj = controller.load_project(project_obj.root)
        rows, generated_ids = _project_snapshot(
            controller,
            project_obj.root,
            target_ids,
            live_status,
        )
        verified_sections = sum(
            section.status == "verified"
            for section in project_obj.manifest.sections
            if section.id in set(target_ids)
        )
        yield (
            rows,
            gr.update(
                choices=generated_ids,
                value=(generated_ids[-1] if generated_ids else None),
            ),
            current_audio,
            f"Generation finished · {verified_sections}/{len(target_ids)} selected sections verified.",
            "Done.",
        )

    def play_section(project_path, section_id):
        if not project_path or not section_id:
            return None
        try:
            return str(controller.section_audio(project_path, section_id))
        except Exception as exc:
            raise gr.Error(f"Cannot play section: {type(exc).__name__}: {exc}")

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

    with gr.Blocks(title="Generate / Resume — Live") as demo:
        gr.Markdown(
            "# Generate / Resume — Live section status\n"
            "The section table stays visible during generation. Each section moves through "
            "**QUEUED → GENERATING → VERIFIED / UNVERIFIED**, while previously completed "
            "sections show **SKIPPED** when Resume is enabled."
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
            strict = gr.Checkbox(
                label="Exact mode: reject unverified chunks",
                value=False,
            )
            generate_button = gr.Button("Generate / Resume", variant="primary")

        activity = gr.Markdown("No generation running.")
        status = gr.Markdown("Ready.")
        status_table = gr.Dataframe(
            value=initial_rows,
            headers=STATUS_HEADERS,
            interactive=False,
            wrap=True,
        )

        with gr.Row():
            section_picker = gr.Dropdown(
                label="Generated section",
                choices=initial_generated,
                value=(initial_generated[0] if initial_generated else None),
            )
            play_button = gr.Button("Play selected section")
        section_audio = gr.Audio(label="Section audio", type="filepath")

        with gr.Row():
            allow_unverified = gr.Checkbox(
                label="Allow merge with unverified",
                value=False,
            )
            merge_button = gr.Button("Merge full.wav")
        merged_audio = gr.Audio(label="Merged project", type="filepath")

        refresh_button.click(
            refresh,
            outputs=[
                project,
                voice,
                variant,
                status_table,
                section_picker,
                status,
                activity,
            ],
        )
        project.change(
            show_project,
            inputs=project,
            outputs=[status_table, section_picker, section_audio, status],
        )
        voice.change(variants_for_voice, inputs=voice, outputs=variant)
        preflight_button.click(
            preflight,
            inputs=[project, voice, variant, sections],
            outputs=[status_table, section_picker, status],
        )
        generate_button.click(
            generate_stream,
            inputs=[project, voice, variant, language, sections, resume, strict],
            outputs=[status_table, section_picker, section_audio, status, activity],
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


def build_demo(model: Any, workspace: str | Path):
    import gradio as gr

    live = build_live_generate_demo(model, workspace)
    setup = build_project_demo(model, workspace)
    preview = build_preview_demo(model, workspace)
    return gr.TabbedInterface(
        [live, setup, preview],
        ["Generate / Resume", "Project Setup / Legacy", "Preview Before Render"],
        title="OmniVoice Project Studio",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch OmniVoice Project Studio with live section status"
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
