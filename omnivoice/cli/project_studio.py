#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Simple Project Studio UI for long-form narration.

The UI is deliberately thin. Persistent project parsing/generation lives in
``omnivoice.project``; reusable voice prompts live in
``omnivoice.voice_library``; style-aware prompt selection lives in
``omnivoice.style_bank``. This keeps the same workflow usable from Colab,
Python, CLI, or a future web application.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Optional

import torch

from omnivoice import OmniVoice, OmniVoiceGenerationConfig
from omnivoice.project import OmniVoiceProject, parse_project_script
from omnivoice.robust_longform import RobustLongFormConfig
from omnivoice.style_bank import StyleBankProjectRunner
from omnivoice.utils.common import get_best_device
from omnivoice.voice_library import VoiceLibrary

logger = logging.getLogger(__name__)

_STUDIO_SETTINGS = "studio.json"


def default_workspace() -> Path:
    """Choose a Colab/Drive-friendly workspace without mounting Drive itself."""

    configured = os.environ.get("OMNIVOICE_STUDIO_HOME")
    if configured:
        return Path(configured).expanduser()
    drive = Path("/content/drive/MyDrive")
    if drive.exists():
        return drive / "OmniVoiceStudio"
    if Path("/content").exists():
        return Path("/content/OmniVoiceStudio")
    return Path.cwd() / "OmniVoiceStudio"


def _split_section_ids(value: str | None) -> Optional[list[str]]:
    if not value or not value.strip():
        return None
    items = [item.strip().upper() for item in value.replace(";", ",").split(",")]
    return [item for item in items if item]


def _project_status_rows(project: OmniVoiceProject) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for section in project.manifest.sections:
        chunks = [chunk for beat in section.beats for chunk in beat.chunks]
        verified = sum(chunk.status == "verified" for chunk in chunks)
        unverified = sum(chunk.status == "unverified" for chunk in chunks)
        rows.append(
            [
                section.id,
                section.title or "",
                section.default_style,
                f"{section.start_time}–{section.end_time}",
                len(section.beats),
                len(chunks),
                verified,
                unverified,
                section.status,
            ]
        )
    return rows


def _chunk_choices(project: OmniVoiceProject) -> list[str]:
    return [
        f"{section.id}/{chunk.id} [{chunk.status}]"
        for section in project.manifest.sections
        for beat in section.beats
        for chunk in beat.chunks
    ]


def _section_audio_choices(project: OmniVoiceProject) -> list[str]:
    return [
        section.id
        for section in project.manifest.sections
        if section.audio_file and (project.root / section.audio_file).exists()
    ]


class ProjectStudioController:
    """UI-independent controller for Project Studio actions."""

    def __init__(self, model: Any, workspace: str | Path) -> None:
        self.model = model
        self.workspace = Path(workspace).expanduser()
        self.projects_root = self.workspace / "projects"
        self.voices_root = self.workspace / "voices"
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.voices = VoiceLibrary(self.voices_root)

    def set_workspace(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser()
        self.projects_root = self.workspace / "projects"
        self.voices_root = self.workspace / "voices"
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.voices = VoiceLibrary(self.voices_root)

    def parse_script(self, script: str) -> tuple[list[list[Any]], str]:
        manifest = parse_project_script(script)
        rows = []
        total_chunks = 0
        for section in manifest.sections:
            chunks = sum(len(beat.chunks) for beat in section.beats)
            total_chunks += chunks
            rows.append(
                [
                    section.id,
                    section.title or "",
                    section.default_style,
                    f"{section.start_time}–{section.end_time}",
                    len(section.beats),
                    chunks,
                ]
            )
        return rows, (
            f"Parsed {len(manifest.sections)} sections and {total_chunks} chunks. "
            "Directives/headings are metadata and will not be spoken."
        )

    def list_projects(self) -> list[str]:
        projects = []
        for manifest_path in sorted(self.projects_root.glob("*/project.json")):
            projects.append(str(manifest_path.parent))
        return projects

    def create_project(
        self,
        script: str,
        *,
        overwrite: bool = False,
    ) -> OmniVoiceProject:
        manifest = parse_project_script(script)
        root = self.projects_root / manifest.slug
        return OmniVoiceProject.create(
            script,
            root,
            max_chunk_words=manifest.max_chunk_words,
            max_chunk_chars=manifest.max_chunk_chars,
            overwrite=overwrite,
        )

    def load_project(self, project_path: str | Path) -> OmniVoiceProject:
        path = Path(project_path).expanduser()
        if not path.is_absolute():
            path = self.projects_root / path
        return OmniVoiceProject.load(path)

    def project_view(
        self,
        project_path: str | Path,
    ) -> tuple[list[list[Any]], list[str], list[str]]:
        project = self.load_project(project_path)
        return (
            _project_status_rows(project),
            _chunk_choices(project),
            _section_audio_choices(project),
        )

    def save_project_settings(
        self,
        project: OmniVoiceProject,
        *,
        voice_name: str,
        voice_variant: str,
        language: Optional[str],
    ) -> None:
        payload = {
            "voice_name": voice_name,
            "voice_variant": voice_variant,
            "language": language,
        }
        (project.root / _STUDIO_SETTINGS).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_project_settings(self, project: OmniVoiceProject) -> dict[str, Any]:
        path = project.root / _STUDIO_SETTINGS
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def create_voice(
        self,
        *,
        name: str,
        reference_audio: str | Path,
        ref_text: Optional[str] = None,
        variant: str = "DEFAULT",
        language: Optional[str] = None,
    ) -> str:
        entry = self.voices.create_from_reference(
            self.model,
            name=name,
            reference_audio=reference_audio,
            ref_text=ref_text,
            variant=variant,
            language=language,
        )
        variants = ", ".join(sorted(entry.variants))
        return f"Saved voice {entry.name!r}. Variants: {variants}."

    def generation_config(self) -> OmniVoiceGenerationConfig:
        return OmniVoiceGenerationConfig(
            num_step=32,
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

    def robust_config(self, *, strict: bool = False) -> RobustLongFormConfig:
        return RobustLongFormConfig(
            max_chunk_words=24,
            max_chunk_chars=220,
            max_retries=3,
            max_split_depth=2,
            verify_with_asr=True,
            asr_model_name="openai/whisper-small.en",
            asr_device="cpu",
            max_wer=0.18,
            min_similarity=0.82,
            min_word_ratio=0.74,
            max_word_ratio=1.30,
            pause_ms=320,
            paragraph_pause_ms=460,
            strict=strict,
            exact_chunk_edges=False,
        )

    def generate(
        self,
        project_path: str | Path,
        *,
        voice_name: str,
        voice_variant: str = "AUTO",
        language: Optional[str] = "en",
        section_ids: Optional[Iterable[str]] = None,
        resume: bool = True,
        strict: bool = False,
    ) -> OmniVoiceProject:
        if not voice_name:
            raise ValueError("Select a saved voice before generation")
        project = self.load_project(project_path)
        selected_variant = (voice_variant or "AUTO").upper()
        self.save_project_settings(
            project,
            voice_name=voice_name,
            voice_variant=selected_variant,
            language=language,
        )
        runner = StyleBankProjectRunner(
            self.model,
            self.voices,
            voice_name=voice_name,
            preferred_variant=selected_variant,
        )
        runner.generate(
            project,
            robust_config=self.robust_config(strict=strict),
            generation_config=self.generation_config(),
            section_ids=section_ids,
            resume=resume,
            language=language or None,
        )
        return project

    def regenerate_chunk(
        self,
        project_path: str | Path,
        chunk_choice: str,
        *,
        voice_name: str,
        voice_variant: str = "AUTO",
        language: Optional[str] = "en",
        strict: bool = False,
    ) -> OmniVoiceProject:
        if not chunk_choice or "/" not in chunk_choice:
            raise ValueError("Select a chunk to regenerate")
        target = chunk_choice.split(" ", 1)[0]
        section_id, chunk_id = target.split("/", 1)
        project = self.load_project(project_path)
        project.mark_chunk_for_regeneration(section_id, chunk_id)
        return self.generate(
            project.root,
            voice_name=voice_name,
            voice_variant=voice_variant,
            language=language,
            section_ids=[section_id],
            resume=True,
            strict=strict,
        )

    def merge_project(
        self,
        project_path: str | Path,
        *,
        require_verified: bool = True,
    ) -> Path:
        project = self.load_project(project_path)
        return project.merge(require_verified=require_verified)

    def section_audio(self, project_path: str | Path, section_id: str) -> Path:
        project = self.load_project(project_path)
        section = project.get_section(section_id)
        if not section.audio_file:
            raise FileNotFoundError(f"{section.id} has no generated audio")
        path = project.root / section.audio_file
        if not path.exists():
            raise FileNotFoundError(path)
        return path


def build_demo(model: Any, workspace: str | Path):
    import gradio as gr

    controller = ProjectStudioController(model, workspace)
    status_headers = [
        "Section",
        "Title",
        "Style",
        "Planned",
        "Beats",
        "Chunks",
        "Verified",
        "Unverified",
        "Status",
    ]
    parse_headers = ["Section", "Title", "Style", "Planned", "Beats", "Chunks"]

    def refresh_voices():
        names = controller.voices.voice_names()
        value = names[0] if names else None
        variants = controller.voices.variant_choices(value) if value else []
        return (
            gr.update(choices=names, value=value),
            gr.update(choices=variants, value=("AUTO" if variants else None)),
            f"Found {len(names)} saved voices.",
        )

    def voice_variants(name):
        variants = controller.voices.variant_choices(name) if name else []
        return gr.update(
            choices=variants,
            value=("AUTO" if variants else None),
        )

    def add_voice(name, variant, audio, ref_text, language):
        if not audio:
            raise gr.Error("Upload a reference audio first.")
        message = controller.create_voice(
            name=name,
            reference_audio=audio,
            ref_text=ref_text,
            variant=variant or "DEFAULT",
            language=language or None,
        )
        names = controller.voices.voice_names()
        variants = controller.voices.variant_choices(name)
        return (
            gr.update(choices=names, value=name),
            gr.update(choices=variants, value="AUTO"),
            message,
        )

    def parse_script(script):
        try:
            rows, message = controller.parse_script(script)
            return rows, message
        except Exception as exc:
            return [], f"Parse error: {type(exc).__name__}: {exc}"

    def refresh_projects():
        projects = controller.list_projects()
        value = projects[0] if projects else None
        return gr.update(
            choices=projects, value=value
        ), f"Found {len(projects)} projects."

    def create_project(script, overwrite):
        try:
            project = controller.create_project(script, overwrite=bool(overwrite))
            projects = controller.list_projects()
            rows, chunks, sections = controller.project_view(project.root)
            return (
                str(project.root),
                gr.update(choices=projects, value=str(project.root)),
                rows,
                gr.update(choices=chunks, value=(chunks[0] if chunks else None)),
                gr.update(choices=sections, value=(sections[0] if sections else None)),
                f"Created project: {project.manifest.title}",
            )
        except Exception as exc:
            return (
                "",
                gr.update(),
                [],
                gr.update(choices=[], value=None),
                gr.update(choices=[], value=None),
                f"Create error: {type(exc).__name__}: {exc}",
            )

    def load_project(path):
        if not path:
            return (
                "",
                [],
                gr.update(choices=[]),
                gr.update(choices=[]),
                "Select a project.",
            )
        try:
            project = controller.load_project(path)
            rows, chunks, sections = controller.project_view(project.root)
            settings = controller.load_project_settings(project)
            suffix = ""
            if settings:
                suffix = (
                    f" Saved voice={settings.get('voice_name')}, "
                    f"variant={settings.get('voice_variant')}."
                )
            return (
                str(project.root),
                rows,
                gr.update(choices=chunks, value=(chunks[0] if chunks else None)),
                gr.update(choices=sections, value=(sections[0] if sections else None)),
                f"Loaded {project.manifest.title}.{suffix}",
            )
        except Exception as exc:
            return (
                "",
                [],
                gr.update(choices=[]),
                gr.update(choices=[]),
                (f"Load error: {type(exc).__name__}: {exc}"),
            )

    def generate_project(path, voice, variant, language, sections, resume, strict):
        if not path:
            return [], gr.update(), gr.update(), "Create/load a project first."
        try:
            project = controller.generate(
                path,
                voice_name=voice,
                voice_variant=variant or "AUTO",
                language=language or None,
                section_ids=_split_section_ids(sections),
                resume=bool(resume),
                strict=bool(strict),
            )
            rows, chunks, section_audio = controller.project_view(project.root)
            verified = sum(row[-1] == "verified" for row in rows)
            return (
                rows,
                gr.update(choices=chunks, value=(chunks[0] if chunks else None)),
                gr.update(
                    choices=section_audio,
                    value=(section_audio[0] if section_audio else None),
                ),
                f"Generation finished. {verified}/{len(rows)} sections verified.",
            )
        except Exception as exc:
            logger.exception("Project generation failed")
            return (
                [],
                gr.update(),
                gr.update(),
                f"Generate error: {type(exc).__name__}: {exc}",
            )

    def regenerate(path, chunk, voice, variant, language, strict):
        try:
            project = controller.regenerate_chunk(
                path,
                chunk,
                voice_name=voice,
                voice_variant=variant or "AUTO",
                language=language or None,
                strict=bool(strict),
            )
            rows, chunks, section_audio = controller.project_view(project.root)
            return (
                rows,
                gr.update(choices=chunks, value=chunk),
                gr.update(
                    choices=section_audio,
                    value=(section_audio[0] if section_audio else None),
                ),
                f"Regenerated {chunk.split(' ', 1)[0]}.",
            )
        except Exception as exc:
            logger.exception("Chunk regeneration failed")
            return (
                [],
                gr.update(),
                gr.update(),
                f"Regenerate error: {type(exc).__name__}: {exc}",
            )

    def play_section(path, section_id):
        if not path or not section_id:
            return None
        try:
            return str(controller.section_audio(path, section_id))
        except Exception as exc:
            raise gr.Error(str(exc))

    def merge(path, allow_unverified):
        try:
            output = controller.merge_project(
                path,
                require_verified=not bool(allow_unverified),
            )
            return str(output), f"Merged: {output}"
        except Exception as exc:
            return None, f"Merge error: {type(exc).__name__}: {exc}"

    initial_voice_names = controller.voices.voice_names()
    initial_voice = initial_voice_names[0] if initial_voice_names else None
    initial_variants = (
        controller.voices.variant_choices(initial_voice) if initial_voice else []
    )

    with gr.Blocks(title="OmniVoice Project Studio") as demo:
        gr.Markdown(
            "# OmniVoice Project Studio\n"
            "Paste the full script, keep `[WARM]`, `[SOFT]`, `[EMPHASIZE]` as "
            "directives, and generate/checkpoint each Sxx section independently.\n\n"
            "**Voice Style Bank:** choose `AUTO` to let each beat select a matching "
            "saved voice variant. Example: `[WARM]` uses `WARM` when available, "
            "then falls back safely to `DEFAULT`."
        )
        project_state = gr.State("")

        with gr.Tab("1. Voice Library"):
            gr.Markdown(
                "Save the same narrator more than once with variants such as "
                "`DEFAULT`, `WARM`, `SOFT`, or `EMPHASIZE`."
            )
            with gr.Row():
                voice_name = gr.Textbox(
                    label="Voice name", placeholder="Warm American Male"
                )
                voice_variant_new = gr.Textbox(label="Variant", value="DEFAULT")
                voice_language_new = gr.Textbox(label="Language", value="en")
            reference_audio = gr.Audio(label="Reference audio (3–10s)", type="filepath")
            reference_text = gr.Textbox(
                label="Exact reference transcript (recommended)",
                lines=3,
            )
            add_voice_button = gr.Button("Save Voice / Variant", variant="primary")
            refresh_voice_button = gr.Button("Refresh Voice Library")
            voice_message = gr.Markdown()

        with gr.Tab("2. Project"):
            script = gr.Textbox(
                label="Full Markdown script",
                lines=22,
                placeholder="# Title\n\n## S01 — 0:00–0:45\n\n[WARM] Narration...",
            )
            with gr.Row():
                parse_button = gr.Button("Parse Script")
                create_button = gr.Button("Create Project", variant="primary")
                overwrite = gr.Checkbox(label="Overwrite same project", value=False)
            parse_table = gr.Dataframe(headers=parse_headers, interactive=False)
            parse_message = gr.Markdown()

            with gr.Row():
                project_picker = gr.Dropdown(
                    label="Saved project",
                    choices=controller.list_projects(),
                )
                refresh_project_button = gr.Button("Refresh Projects")
                load_project_button = gr.Button("Load Project")

        with gr.Tab("3. Generate / Resume"):
            with gr.Row():
                saved_voice = gr.Dropdown(
                    label="Voice",
                    choices=initial_voice_names,
                    value=initial_voice,
                )
                saved_variant = gr.Dropdown(
                    label="Voice variant",
                    info="AUTO follows [WARM]/[SOFT]/... tags; a concrete variant locks the project.",
                    choices=initial_variants,
                    value=("AUTO" if initial_variants else None),
                )
                language = gr.Textbox(label="Language", value="en")
            sections = gr.Textbox(
                label="Sections (optional)",
                placeholder="S03,S07,S10 - empty means all",
            )
            with gr.Row():
                resume = gr.Checkbox(label="Resume / skip verified chunks", value=True)
                strict = gr.Checkbox(
                    label="Exact mode: reject unverified chunks", value=False
                )
                generate_button = gr.Button("Generate / Resume", variant="primary")
            status_table = gr.Dataframe(headers=status_headers, interactive=False)

            with gr.Row():
                chunk_picker = gr.Dropdown(label="Chunk to regenerate", choices=[])
                regenerate_button = gr.Button("Regenerate selected chunk")

            with gr.Row():
                section_audio_picker = gr.Dropdown(
                    label="Generated section", choices=[]
                )
                play_section_button = gr.Button("Play section")
            section_audio = gr.Audio(label="Section audio", type="filepath")

            with gr.Row():
                allow_unverified = gr.Checkbox(
                    label="Allow merge with unverified sections",
                    value=False,
                )
                merge_button = gr.Button("Merge full.wav")
            merged_audio = gr.Audio(label="Merged project audio", type="filepath")
            action_message = gr.Markdown()

        refresh_voice_button.click(
            refresh_voices,
            outputs=[saved_voice, saved_variant, voice_message],
        )
        saved_voice.change(voice_variants, inputs=saved_voice, outputs=saved_variant)
        add_voice_button.click(
            add_voice,
            inputs=[
                voice_name,
                voice_variant_new,
                reference_audio,
                reference_text,
                voice_language_new,
            ],
            outputs=[saved_voice, saved_variant, voice_message],
        )
        parse_button.click(
            parse_script, inputs=script, outputs=[parse_table, parse_message]
        )
        refresh_project_button.click(
            refresh_projects,
            outputs=[project_picker, parse_message],
        )
        create_button.click(
            create_project,
            inputs=[script, overwrite],
            outputs=[
                project_state,
                project_picker,
                status_table,
                chunk_picker,
                section_audio_picker,
                action_message,
            ],
        )
        load_project_button.click(
            load_project,
            inputs=project_picker,
            outputs=[
                project_state,
                status_table,
                chunk_picker,
                section_audio_picker,
                action_message,
            ],
        )
        generate_button.click(
            generate_project,
            inputs=[
                project_state,
                saved_voice,
                saved_variant,
                language,
                sections,
                resume,
                strict,
            ],
            outputs=[status_table, chunk_picker, section_audio_picker, action_message],
        )
        regenerate_button.click(
            regenerate,
            inputs=[
                project_state,
                chunk_picker,
                saved_voice,
                saved_variant,
                language,
                strict,
            ],
            outputs=[status_table, chunk_picker, section_audio_picker, action_message],
        )
        play_section_button.click(
            play_section,
            inputs=[project_state, section_audio_picker],
            outputs=section_audio,
        )
        merge_button.click(
            merge,
            inputs=[project_state, allow_unverified],
            outputs=[merged_audio, action_message],
        )

    return demo


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
    parser = build_parser()
    args = parser.parse_args(argv)
    device = args.device or get_best_device()
    logger.info(
        "Loading OmniVoice model=%s device=%s ASR=%s on %s",
        args.model,
        device,
        args.asr_model,
        args.asr_device,
    )
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
