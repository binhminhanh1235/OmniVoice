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
import shutil
from pathlib import Path
from typing import Any, Iterable, Optional

import torch

from omnivoice import OmniVoice, OmniVoiceGenerationConfig
from omnivoice.project import OmniVoiceProject
from omnivoice.project_narration import (
    create_narration_project,
    parse_narration_project_script,
)
from omnivoice.robust_longform import RobustLongFormConfig
from omnivoice.style_bank import StyleBankProjectRunner
from omnivoice.utils.common import get_best_device
from omnivoice.utils.lang_map import LANG_NAME_TO_ID, lang_display_name
from omnivoice.voice_library import VoiceLibrary

logger = logging.getLogger(__name__)

_STUDIO_SETTINGS = "studio.json"
_LANGUAGE_CHOICES = [("English", "en")] + sorted(
    (
        (lang_display_name(name), language_id)
        for name, language_id in LANG_NAME_TO_ID.items()
        if name != "english"
    ),
    key=lambda item: item[0],
)


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

    def parse_script(
        self,
        script: str,
        *,
        speak_section_titles: bool = False,
    ) -> tuple[list[list[Any]], str]:
        manifest = parse_narration_project_script(
            script,
            speak_section_titles=speak_section_titles,
        )
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
        title_note = (
            "Section titles are included as narration."
            if speak_section_titles
            else "Section titles are metadata and will not be spoken."
        )
        return rows, (
            f"Parsed {len(manifest.sections)} sections and {total_chunks} chunks. "
            f"{title_note} Directives are always metadata."
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
        speak_section_titles: bool = False,
        overwrite: bool = False,
    ) -> OmniVoiceProject:
        manifest = parse_narration_project_script(
            script,
            speak_section_titles=speak_section_titles,
        )
        root = self.projects_root / manifest.slug
        return create_narration_project(
            script,
            root,
            max_chunk_words=manifest.max_chunk_words,
            max_chunk_chars=manifest.max_chunk_chars,
            speak_section_titles=speak_section_titles,
            overwrite=overwrite,
        )

    def delete_project(self, project_path: str | Path) -> str:
        """Delete one validated Studio project directory and return its title."""

        project = self.load_project(project_path)
        project_root = project.root.resolve()
        projects_root = self.projects_root.resolve()
        try:
            project_root.relative_to(projects_root)
        except ValueError as exc:
            raise ValueError("Refusing to delete a project outside the Studio projects directory") from exc
        if project_root == projects_root or not (project_root / "project.json").is_file():
            raise ValueError("Refusing to delete an invalid project directory")

        title = project.manifest.title
        shutil.rmtree(project_root)
        return title

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

    projects = controller.list_projects()
    voices = controller.voices.voice_names()
    initial_project = projects[0] if projects else None
    initial_voice = voices[0] if voices else None
    initial_variants = controller.voices.variant_choices(initial_voice) if initial_voice else []
    initial_rows = controller.project_view(initial_project)[0] if initial_project else []
    initial_sections = controller.project_view(initial_project)[2] if initial_project else []

    def refresh():
        items = controller.list_projects()
        voices_now = controller.voices.voice_names()
        selected = items[0] if items else None
        selected_voice = voices_now[0] if voices_now else None
        variants = controller.voices.variant_choices(selected_voice) if selected_voice else []
        rows = controller.project_view(selected)[0] if selected else []
        sections = controller.project_view(selected)[2] if selected else []
        return (
            gr.update(choices=items, value=selected),
            gr.update(choices=voices_now, value=selected_voice),
            gr.update(choices=variants, value=("AUTO" if variants else None)),
            rows,
            gr.update(choices=sections, value=(sections[0] if sections else None)),
            "Ready.",
        )

    def variants_for_voice(name):
        variants = controller.voices.variant_choices(name) if name else []
        return gr.update(choices=variants, value=("AUTO" if variants else None))

    def load_project_view(project_path):
        if not project_path:
            return [], gr.update(choices=[], value=None), None
        rows, _, sections = controller.project_view(project_path)
        first = sections[0] if sections else None
        audio = str(controller.section_audio(project_path, first)) if first else None
        return rows, gr.update(choices=sections, value=first), audio

    def create_project(script, speak_titles, replace_existing):
        try:
            project = controller.create_project(
                script,
                speak_section_titles=bool(speak_titles),
                overwrite=bool(replace_existing),
            )
        except FileExistsError as exc:
            raise gr.Error(
                "A project with this title already exists. Enable Replace existing project "
                "only when you intend to rebuild it. " + str(exc)
            )
        items = controller.list_projects()
        rows, _, sections = controller.project_view(project.root)
        return (
            gr.update(choices=items, value=str(project.root)),
            rows,
            gr.update(choices=sections, value=(sections[0] if sections else None)),
            f"Created {project.manifest.title}",
        )

    def generate(project_path, voice_name, variant, language, sections, resume, strict):
        try:
            project = controller.generate(
                project_path,
                voice_name=voice_name,
                voice_variant=variant,
                language=language or None,
                section_ids=_split_section_ids(sections),
                resume=bool(resume),
                strict=bool(strict),
            )
        except Exception as exc:
            raise gr.Error(f"Generation failed: {type(exc).__name__}: {exc}")
        rows, _, generated = controller.project_view(project.root)
        first = generated[0] if generated else None
        audio = str(controller.section_audio(project.root, first)) if first else None
        return rows, gr.update(choices=generated, value=first), audio, "Generation complete."

    def regenerate(project_path, chunk, voice_name, variant, language, strict):
        try:
            project = controller.regenerate_chunk(
                project_path,
                chunk,
                voice_name=voice_name,
                voice_variant=variant,
                language=language or None,
                strict=bool(strict),
            )
        except Exception as exc:
            raise gr.Error(f"Regeneration failed: {type(exc).__name__}: {exc}")
        rows, chunks, generated = controller.project_view(project.root)
        first = generated[0] if generated else None
        audio = str(controller.section_audio(project.root, first)) if first else None
        return (
            rows,
            gr.update(choices=chunks, value=(chunks[0] if chunks else None)),
            gr.update(choices=generated, value=first),
            audio,
            "Chunk regenerated.",
        )

    def merge(project_path, require_verified):
        try:
            output = controller.merge_project(project_path, require_verified=bool(require_verified))
        except Exception as exc:
            raise gr.Error(f"Merge failed: {type(exc).__name__}: {exc}")
        return str(output), f"Merged: {output}"

    with gr.Blocks(title="OmniVoice Project Studio") as demo:
        gr.Markdown(
            "# OmniVoice Project Studio\n"
            "Create a project from markdown, pick a saved voice/style bank, generate sections, "
            "inspect status, regenerate failed chunks, and merge final audio."
        )

        with gr.Row():
            refresh_button = gr.Button("Refresh Projects / Voices")
            project = gr.Dropdown(
                label="Project",
                choices=projects,
                value=initial_project,
            )

        with gr.Accordion("Create project", open=not bool(projects)):
            script = gr.Textbox(
                label="Project markdown",
                lines=16,
                placeholder="# Title\n\n## S01 — 0:00–0:45\n### Opening\n[WARM] Narration...",
            )
            with gr.Row():
                speak_titles = gr.Checkbox(
                    label="Read section titles (###)",
                    value=False,
                    info="When disabled, headings are metadata only and are not spoken.",
                )
                replace_existing = gr.Checkbox(
                    label="Replace existing project",
                    value=False,
                    info="Destructive: removes the existing project directory for the same title before rebuilding it.",
                )
                analyze_button = gr.Button("Analyze script")
                create_button = gr.Button("Create project", variant="primary")
            parse_table = gr.Dataframe(
                headers=["Section", "Title", "Style", "Planned", "Beats", "Chunks"],
                interactive=False,
                wrap=True,
            )
            parse_status = gr.Markdown()

        with gr.Row():
            voice = gr.Dropdown(label="Voice", choices=voices, value=initial_voice)
            variant = gr.Dropdown(
                label="Voice variant",
                choices=initial_variants,
                value=("AUTO" if initial_variants else None),
            )
            language = gr.Dropdown(
                label="Language",
                choices=_LANGUAGE_CHOICES,
                value="en",
                allow_custom_value=False,
                interactive=True,
                info="English is first; select another supported language when needed.",
            )

        sections = gr.Textbox(
            label="Sections (optional)",
            placeholder="S03,S07,S10 - empty means all",
        )

        with gr.Row():
            resume = gr.Checkbox(label="Resume / skip verified chunks", value=True)
            strict = gr.Checkbox(label="Exact mode: reject unverified chunks", value=False)
            generate_button = gr.Button("Generate / Resume", variant="primary")

        status = gr.Markdown("Ready.")
        status_table = gr.Dataframe(
            value=initial_rows,
            headers=status_headers,
            interactive=False,
            wrap=True,
        )

        with gr.Row():
            section_picker = gr.Dropdown(
                label="Generated section",
                choices=initial_sections,
                value=(initial_sections[0] if initial_sections else None),
            )
            play_button = gr.Button("Play section")
        section_audio = gr.Audio(label="Section audio", type="filepath")

        chunk_picker = gr.Dropdown(label="Chunk to regenerate", choices=[])
        regenerate_button = gr.Button("Regenerate selected chunk")

        require_verified = gr.Checkbox(label="Require verified sections before merge", value=True)
        merge_button = gr.Button("Merge full.wav", variant="primary")
        merged_audio = gr.Audio(label="Merged project", type="filepath")

        refresh_button.click(
            refresh,
            outputs=[project, voice, variant, status_table, section_picker, status],
        )
        project.change(
            load_project_view,
            inputs=project,
            outputs=[status_table, section_picker, section_audio],
        )
        voice.change(variants_for_voice, inputs=voice, outputs=variant)
        analyze_button.click(
            controller.parse_script,
            inputs=[script, speak_titles],
            outputs=[parse_table, parse_status],
        )
        create_button.click(
            create_project,
            inputs=[script, speak_titles, replace_existing],
            outputs=[project, status_table, section_picker, status],
        )
        generate_button.click(
            generate,
            inputs=[project, voice, variant, language, sections, resume, strict],
            outputs=[status_table, section_picker, section_audio, status],
        )
        play_button.click(
            controller.section_audio,
            inputs=[project, section_picker],
            outputs=section_audio,
        )
        section_picker.change(
            lambda project_path, section_id: (
                gr.update(choices=controller.project_view(project_path)[1], value=None)
                if project_path and section_id
                else gr.update(choices=[], value=None)
            ),
            inputs=[project, section_picker],
            outputs=chunk_picker,
        )
        regenerate_button.click(
            regenerate,
            inputs=[project, chunk_picker, voice, variant, language, strict],
            outputs=[status_table, chunk_picker, section_picker, section_audio, status],
        )
        merge_button.click(
            merge,
            inputs=[project, require_verified],
            outputs=[merged_audio, status],
        )

    return demo


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="OmniVoice Project Studio")
    parser.add_argument("--model", default="k2-fsa/OmniVoice")
    parser.add_argument("--device", default=None)
    parser.add_argument("--workspace", default=str(default_workspace()))
    parser.add_argument("--ip", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    device = args.device or get_best_device()
    model = OmniVoice.from_pretrained(
        args.model,
        device_map=device,
        dtype=torch.float16,
    )
    build_demo(model, args.workspace).queue().launch(
        server_name=args.ip,
        server_port=args.port,
        share=args.share,
        show_error=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
