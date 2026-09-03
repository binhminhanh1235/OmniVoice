#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0

"""Unified project-first workspace for long-form narration.

This UI keeps the existing generation/controllers intact while presenting the
workflow the way a narrator works: Script -> Preview -> Render -> Review ->
Export.  Project selection is visible and shared across the page, sections are
selected from a checklist instead of typed as comma-separated IDs, and common
recovery actions live beside the audio they affect.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

from omnivoice.preview import ProjectPreviewGenerator


def _section_labels(project: Any) -> list[str]:
    labels: list[str] = []
    for section in project.manifest.sections:
        chunks = [chunk for beat in section.beats for chunk in beat.chunks]
        verified = sum(chunk.status == "verified" for chunk in chunks)
        state = section.status.upper()
        title = section.title or "Untitled section"
        labels.append(
            f"{section.id} · {title} · {verified}/{len(chunks)} verified · {state}"
        )
    return labels


def _section_ids(values: Optional[Iterable[str]]) -> Optional[list[str]]:
    if not values:
        return None
    ids: list[str] = []
    for value in values:
        section_id = str(value).split(" · ", 1)[0].strip().upper()
        if section_id and section_id not in ids:
            ids.append(section_id)
    return ids or None


def _chunk_labels(project: Any, section_id: Optional[str] = None) -> list[str]:
    labels: list[str] = []
    for section in project.manifest.sections:
        if section_id and section.id != section_id:
            continue
        for beat in section.beats:
            for chunk in beat.chunks:
                excerpt = " ".join(chunk.text.split())
                if len(excerpt) > 92:
                    excerpt = excerpt[:89].rstrip() + "..."
                labels.append(
                    f"{section.id}/{chunk.id} · {chunk.status.upper()} · {excerpt}"
                )
    return labels


def _chunk_target(value: str) -> tuple[str, str]:
    target = str(value).split(" · ", 1)[0]
    section_id, chunk_id = target.split("/", 1)
    return section_id.upper(), chunk_id


def _project_summary(project: Any, settings: dict[str, Any]) -> str:
    total = 0
    verified = 0
    for section in project.manifest.sections:
        for beat in section.beats:
            for chunk in beat.chunks:
                total += 1
                verified += chunk.status == "verified"
    voice = settings.get("voice_name") or "not selected"
    variant = settings.get("voice_variant") or "AUTO"
    quality = settings.get("quality_preset") or "workspace default"
    titles = "on" if settings.get("speak_section_titles", False) else "off"
    return (
        f"### {project.manifest.title}\n"
        f"**{len(project.manifest.sections)} sections** · "
        f"**{verified}/{total} chunks verified** · "
        f"Voice **{voice}/{variant}** · Quality **{quality}** · "
        f"Read titles **{titles}**"
    )


def build_project_workspace_demo(
    model: Any,
    workspace: str | Path,
    *,
    controller_cls: type,
):
    import gradio as gr

    controller = controller_cls(model, workspace)
    projects = controller.list_projects()
    voices = controller.voices.voice_names()
    initial_project = projects[0] if projects else None
    initial_voice = voices[0] if voices else None
    initial_variants = (
        controller.voices.variant_choices(initial_voice) if initial_voice else []
    )

    def load_state(project_path: Optional[str]):
        if not project_path:
            return (
                "### No project selected",
                gr.update(choices=[], value=[]),
                [],
                gr.update(choices=[], value=None),
                None,
                False,
                "Select or create a project.",
            )
        project = controller.load_project(project_path)
        settings = controller.load_project_settings(project)
        labels = _section_labels(project)
        generated = [
            section.id
            for section in project.manifest.sections
            if section.audio_file and (project.root / section.audio_file).exists()
        ]
        first_generated = generated[0] if generated else None
        audio = (
            str(controller.section_audio(project.root, first_generated))
            if first_generated
            else None
        )
        rows, _, _ = controller.project_view(project.root)
        return (
            _project_summary(project, settings),
            gr.update(choices=labels, value=labels),
            rows,
            gr.update(choices=generated, value=first_generated),
            audio,
            bool(settings.get("speak_section_titles", False)),
            f"Loaded {project.manifest.title}.",
        )

    def refresh_projects(current):
        items = controller.list_projects()
        value = current if current in items else (items[0] if items else None)
        return gr.update(choices=items, value=value)

    def variants_for_voice(name):
        variants = controller.voices.variant_choices(name) if name else []
        return gr.update(choices=variants, value=("AUTO" if variants else None))

    def analyze_script(script, speak_titles):
        try:
            rows, message = controller.parse_script(
                script,
                speak_section_titles=bool(speak_titles),
            )
            return rows, message
        except Exception as exc:
            raise gr.Error(f"Script analysis failed: {type(exc).__name__}: {exc}")

    def create_project(script, speak_titles, replace_existing):
        if not script or not script.strip():
            raise gr.Error("Paste a script first.")
        try:
            project = controller.create_project(
                script,
                speak_section_titles=bool(speak_titles),
                overwrite=bool(replace_existing),
            )
            items = controller.list_projects()
            labels = _section_labels(project)
            settings = controller.load_project_settings(project)
            rows, _, _ = controller.project_view(project.root)
            return (
                gr.update(choices=items, value=str(project.root)),
                _project_summary(project, settings),
                gr.update(choices=labels, value=labels),
                rows,
                f"Created {project.manifest.title}.",
            )
        except FileExistsError as exc:
            raise gr.Error(
                f"Project already exists. Open it, create a differently titled script, "
                f"or explicitly enable Replace existing project. Details: {exc}"
            )
        except Exception as exc:
            raise gr.Error(f"Create failed: {type(exc).__name__}: {exc}")

    def select_filter(project_path, mode):
        if not project_path:
            return gr.update(value=[])
        project = controller.load_project(project_path)
        labels = _section_labels(project)
        chosen: list[str] = []
        for label, section in zip(labels, project.manifest.sections):
            chunks = [chunk for beat in section.beats for chunk in beat.chunks]
            if mode == "All":
                chosen.append(label)
            elif mode == "Pending" and section.status not in {"verified"}:
                chosen.append(label)
            elif mode == "Needs review" and (
                section.status == "unverified"
                or any(chunk.status == "unverified" for chunk in chunks)
            ):
                chosen.append(label)
            elif mode == "Failed" and section.status == "failed":
                chosen.append(label)
        return gr.update(value=chosen)

    def preflight(project_path, voice_name, variant, selected_labels):
        if not project_path:
            raise gr.Error("Select a project first.")
        if not voice_name:
            raise gr.Error("Select a voice first.")
        project = controller.load_project(project_path)
        target_ids = _section_ids(selected_labels) or [
            section.id for section in project.manifest.sections
        ]
        pending = 0
        verified = 0
        resolutions: dict[str, str] = {}
        for section in project.manifest.sections:
            if section.id not in target_ids:
                continue
            for beat in section.beats:
                resolved, fallback = controller.voices.resolve_variant(
                    voice_name,
                    style=beat.style,
                    preferred_variant=(variant or "AUTO"),
                )
                resolutions[beat.style] = resolved + (" (fallback)" if fallback else "")
                for chunk in beat.chunks:
                    if chunk.status == "verified":
                        verified += 1
                    else:
                        pending += 1
        resolution_text = ", ".join(
            f"{style}→{value}" for style, value in sorted(resolutions.items())
        ) or "DEFAULT"
        return (
            f"Preflight OK · {len(target_ids)} sections · "
            f"{pending} pending chunks · {verified} already verified · "
            f"styles {resolution_text}."
        )

    def generate_previews(project_path, voice_name, variant, language, strict):
        if not project_path:
            raise gr.Error("Select a project first.")
        if not voice_name:
            raise gr.Error("Select a voice first.")
        try:
            project = controller.load_project(project_path)
            quality = None
            if hasattr(controller, "project_quality_preset"):
                quality = controller.project_quality_preset(project)[0]
            preview = ProjectPreviewGenerator(
                model,
                controller.voices,
                voice_name=voice_name,
                preferred_variant=(variant or "AUTO"),
            )
            results = preview.generate(
                project,
                robust_config=controller.robust_config(
                    strict=bool(strict),
                    **({"quality_preset": quality} if quality else {}),
                ),
                generation_config=controller.generation_config(
                    **({"quality_preset": quality} if quality else {})
                ),
                language=language or None,
                strict=bool(strict),
            )
            by_label = {item.target.label: item for item in results}
            return (
                by_label.get("opening").audio_file if by_label.get("opening") else None,
                by_label.get("middle").audio_file if by_label.get("middle") else None,
                by_label.get("ending").audio_file if by_label.get("ending") else None,
                "Preview complete. Listen before starting the full render.",
            )
        except Exception as exc:
            raise gr.Error(f"Preview failed: {type(exc).__name__}: {exc}")

    def render_stream(
        project_path,
        voice_name,
        variant,
        language,
        selected_labels,
        resume,
        strict,
    ):
        if not project_path:
            raise gr.Error("Select a project first.")
        if not voice_name:
            raise gr.Error("Select a voice first.")
        project = controller.load_project(project_path)
        target_ids = _section_ids(selected_labels) or [
            section.id for section in project.manifest.sections
        ]
        total = len(target_ids)
        for index, section_id in enumerate(target_ids, start=1):
            yield (
                gr.update(),
                gr.update(),
                None,
                f"Rendering {section_id} · {index}/{total}...",
                _project_summary(project, controller.load_project_settings(project)),
            )
            try:
                kwargs = {}
                if hasattr(controller, "project_quality_preset"):
                    kwargs["quality_preset"] = controller.project_quality_preset(project)[0]
                project = controller.generate(
                    project.root,
                    voice_name=voice_name,
                    voice_variant=variant or "AUTO",
                    language=language or None,
                    section_ids=[section_id],
                    resume=bool(resume),
                    strict=bool(strict),
                    **kwargs,
                )
            except Exception as exc:
                raise gr.Error(
                    f"Generation failed at {section_id}: {type(exc).__name__}: {exc}"
                )
            rows, _, generated = controller.project_view(project.root)
            section = project.get_section(section_id)
            audio = (
                str(project.root / section.audio_file) if section.audio_file else None
            )
            labels = _section_labels(project)
            yield (
                rows,
                gr.update(choices=labels, value=selected_labels),
                audio,
                f"Finished {section_id}: {section.status} · {index}/{total}.",
                _project_summary(project, controller.load_project_settings(project)),
            )

    def generated_sections(project_path):
        if not project_path:
            return gr.update(choices=[], value=None), None
        project = controller.load_project(project_path)
        ids = [
            section.id
            for section in project.manifest.sections
            if section.audio_file and (project.root / section.audio_file).exists()
        ]
        first = ids[0] if ids else None
        return (
            gr.update(choices=ids, value=first),
            str(controller.section_audio(project.root, first)) if first else None,
        )

    def play_section(project_path, section_id):
        if not project_path or not section_id:
            return None, gr.update(choices=[], value=None)
        project = controller.load_project(project_path)
        audio = str(controller.section_audio(project.root, section_id))
        chunks = _chunk_labels(project, section_id)
        return audio, gr.update(choices=chunks, value=(chunks[0] if chunks else None))

    def show_chunk(project_path, chunk_label):
        if not project_path or not chunk_label:
            return "Select a chunk to inspect."
        section_id, chunk_id = _chunk_target(chunk_label)
        project = controller.load_project(project_path)
        chunk = project.get_chunk(section_id, chunk_id)
        report = ""
        if chunk.report_file:
            report_path = project.root / chunk.report_file
            if report_path.exists():
                import json

                payload = json.loads(report_path.read_text(encoding="utf-8"))
                reports = payload.get("reports") or []
                if reports:
                    last = reports[-1]
                    transcript = last.get("transcript", "")
                    similarity = last.get("similarity")
                    wer = last.get("wer")
                    report = (
                        f"\n\n**ASR:** {transcript}\n\n"
                        f"Similarity: `{similarity}` · WER: `{wer}`"
                    )
        return f"**Expected:**\n\n{chunk.text}{report}"

    def regenerate_chunk(
        project_path,
        chunk_label,
        voice_name,
        variant,
        language,
        strict,
    ):
        if not project_path or not chunk_label:
            raise gr.Error("Select a chunk first.")
        kwargs = {}
        project = controller.load_project(project_path)
        if hasattr(controller, "project_quality_preset"):
            kwargs["quality_preset"] = controller.project_quality_preset(project)[0]
        project = controller.regenerate_chunk(
            project.root,
            chunk_label,
            voice_name=voice_name,
            voice_variant=variant or "AUTO",
            language=language or None,
            strict=bool(strict),
            **kwargs,
        )
        section_id, _ = _chunk_target(chunk_label)
        audio = str(controller.section_audio(project.root, section_id))
        chunks = _chunk_labels(project, section_id)
        rows, _, _ = controller.project_view(project.root)
        return (
            audio,
            gr.update(choices=chunks, value=(chunks[0] if chunks else None)),
            rows,
            _project_summary(project, controller.load_project_settings(project)),
            f"Regenerated {chunk_label.split(' · ', 1)[0]}.",
        )

    def merge(project_path, allow_unverified):
        if not project_path:
            raise gr.Error("Select a project first.")
        try:
            output = controller.merge_project(
                project_path,
                require_verified=not bool(allow_unverified),
            )
            return str(output), f"Merged project: {output}"
        except Exception as exc:
            raise gr.Error(f"Merge failed: {type(exc).__name__}: {exc}")

    if initial_project:
        initial_loaded = controller.load_project(initial_project)
        initial_settings = controller.load_project_settings(initial_loaded)
        initial_summary = _project_summary(initial_loaded, initial_settings)
        initial_section_labels = _section_labels(initial_loaded)
        initial_rows, _, _ = controller.project_view(initial_loaded.root)
        initial_titles = bool(initial_settings.get("speak_section_titles", False))
    else:
        initial_summary = "### No project selected"
        initial_section_labels = []
        initial_rows = []
        initial_titles = False

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

    with gr.Blocks(title="Projects") as demo:
        with gr.Row():
            project = gr.Dropdown(
                label="Project",
                choices=projects,
                value=initial_project,
                scale=6,
            )
            refresh_project = gr.Button("Refresh", scale=1)
        project_header = gr.Markdown(initial_summary)

        with gr.Accordion("1 · Script & Project", open=not bool(initial_project)):
            script = gr.Textbox(
                label="Markdown script",
                lines=16,
                placeholder="# Title\n\n## S01 — 0:00–0:45\n### Opening\n[WARM] Narration...",
            )
            with gr.Row():
                speak_titles = gr.Checkbox(
                    label="Read section titles (###)",
                    value=initial_titles,
                )
                replace_existing = gr.Checkbox(
                    label="Replace existing project",
                    value=False,
                    info="Destructive: existing generated files for the same project are replaced.",
                )
                analyze = gr.Button("Analyze script")
                create = gr.Button("Create project", variant="primary")
            parse_table = gr.Dataframe(headers=parse_headers, interactive=False, wrap=True)
            script_status = gr.Markdown("Analyze the script before rendering.")

        with gr.Accordion("2 · Voice & Preview", open=True):
            with gr.Row():
                voice = gr.Dropdown(label="Voice", choices=voices, value=initial_voice)
                variant = gr.Dropdown(
                    label="Variant",
                    choices=initial_variants,
                    value=("AUTO" if initial_variants else None),
                )
                language = gr.Textbox(label="Language", value="en")
                strict = gr.Checkbox(label="Exact mode", value=False)
            with gr.Row():
                preview_button = gr.Button("Generate opening / middle / ending previews")
            with gr.Row():
                opening = gr.Audio(label="Opening", type="filepath")
                middle = gr.Audio(label="Middle", type="filepath")
                ending = gr.Audio(label="Ending", type="filepath")
            preview_status = gr.Markdown()

        with gr.Accordion("3 · Render", open=True):
            with gr.Row():
                section_filter = gr.Radio(
                    ["All", "Pending", "Needs review", "Failed"],
                    value="All",
                    label="Quick select",
                )
                preflight_button = gr.Button("Preflight")
                resume = gr.Checkbox(label="Skip verified chunks", value=True)
                render_button = gr.Button("Render selected", variant="primary")
            section_selection = gr.CheckboxGroup(
                label="Sections",
                choices=initial_section_labels,
                value=initial_section_labels,
            )
            preflight_status = gr.Markdown()
            status_table = gr.Dataframe(
                headers=status_headers,
                value=initial_rows,
                interactive=False,
                wrap=True,
            )
            render_audio = gr.Audio(label="Latest rendered section", type="filepath")
            render_status = gr.Markdown("Ready.")

        with gr.Accordion("4 · Review", open=True):
            with gr.Row():
                generated_picker = gr.Dropdown(label="Generated section", choices=[])
                refresh_generated = gr.Button("Refresh generated sections")
            section_audio = gr.Audio(label="Section audio", type="filepath")
            chunk_picker = gr.Dropdown(label="Chunk to inspect", choices=[])
            chunk_detail = gr.Markdown("Select a generated section, then inspect a chunk.")
            regenerate = gr.Button("Regenerate selected chunk")

        with gr.Accordion("5 · Export", open=False):
            allow_unverified = gr.Checkbox(
                label="Allow export with unverified sections",
                value=False,
            )
            merge_button = gr.Button("Merge full.wav", variant="primary")
            merged_audio = gr.Audio(label="Merged project", type="filepath")
            export_status = gr.Markdown()

        refresh_project.click(refresh_projects, inputs=project, outputs=project)
        project.change(
            load_state,
            inputs=project,
            outputs=[
                project_header,
                section_selection,
                status_table,
                generated_picker,
                section_audio,
                speak_titles,
                render_status,
            ],
        )
        voice.change(variants_for_voice, inputs=voice, outputs=variant)
        analyze.click(
            analyze_script,
            inputs=[script, speak_titles],
            outputs=[parse_table, script_status],
        )
        create.click(
            create_project,
            inputs=[script, speak_titles, replace_existing],
            outputs=[project, project_header, section_selection, status_table, script_status],
        )
        section_filter.change(
            select_filter,
            inputs=[project, section_filter],
            outputs=section_selection,
        )
        preflight_button.click(
            preflight,
            inputs=[project, voice, variant, section_selection],
            outputs=preflight_status,
        )
        preview_button.click(
            generate_previews,
            inputs=[project, voice, variant, language, strict],
            outputs=[opening, middle, ending, preview_status],
        )
        render_button.click(
            render_stream,
            inputs=[project, voice, variant, language, section_selection, resume, strict],
            outputs=[status_table, section_selection, render_audio, render_status, project_header],
        )
        refresh_generated.click(
            generated_sections,
            inputs=project,
            outputs=[generated_picker, section_audio],
        )
        generated_picker.change(
            play_section,
            inputs=[project, generated_picker],
            outputs=[section_audio, chunk_picker],
        )
        chunk_picker.change(
            show_chunk,
            inputs=[project, chunk_picker],
            outputs=chunk_detail,
        )
        regenerate.click(
            regenerate_chunk,
            inputs=[project, chunk_picker, voice, variant, language, strict],
            outputs=[section_audio, chunk_picker, status_table, project_header, render_status],
        )
        merge_button.click(
            merge,
            inputs=[project, allow_unverified],
            outputs=[merged_audio, export_status],
        )

    return demo
