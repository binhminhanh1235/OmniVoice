#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Gradio UI for the persistent multi-project render queue."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from omnivoice.project_queue import ProjectQueueRunner, ProjectQueueStore, queue_rows

QUEUE_HEADERS = [
    "#",
    "Project",
    "Status",
    "Sections",
    "Current section",
    "Voice",
    "Variant",
    "Language",
    "Auto merge",
    "Message / error",
    "Queue ID",
]


def _item_choices(manifest) -> list[str]:
    return [
        f"{item.id} | {item.project_title} | {item.status.upper()}"
        for item in manifest.items
    ]


def _preferred_item_choice(manifest) -> str | None:
    if not manifest.items:
        return None
    preferred = next(
        (item for item in manifest.items if item.status == "running"),
        None,
    )
    if preferred is None:
        preferred = next(
            (
                item
                for item in manifest.items
                if item.status in {"pending", "paused", "failed", "needs_review"}
            ),
            manifest.items[0],
        )
    return f"{preferred.id} | {preferred.project_title} | {preferred.status.upper()}"


def _choice_id(value: str | None) -> str:
    if not value:
        raise ValueError("Select a queue item first")
    return value.split(" | ", 1)[0].strip()


def build_project_queue_demo(
    model: Any,
    workspace: str | Path,
    *,
    controller_cls: type,
):
    import gradio as gr

    controller = controller_cls(model, workspace)
    store = ProjectQueueStore(workspace)
    # Recovery is intentionally performed once when the app starts. A normal
    # Refresh must never rewrite a genuinely RUNNING item while generation is
    # still active in this process.
    store.recover_interrupted()
    runner = ProjectQueueRunner(controller, store)

    def project_defaults(project_path, voices=None):
        names = list(voices if voices is not None else controller.voices.voice_names())
        preferred_voice = names[0] if names else None
        preferred_variant = None
        language = "en"
        title = None

        if project_path:
            project = controller.load_project(project_path)
            title = project.manifest.title
            settings = controller.load_project_settings(project)
            saved_voice = settings.get("voice_name")
            if saved_voice in names:
                preferred_voice = saved_voice
            language = settings.get("language") or "en"

            variants = (
                controller.voices.variant_choices(preferred_voice)
                if preferred_voice
                else []
            )
            saved_variant = (settings.get("voice_variant") or "AUTO").upper()
            if saved_variant in variants:
                preferred_variant = saved_variant
            elif "AUTO" in variants:
                preferred_variant = "AUTO"
            elif variants:
                preferred_variant = variants[0]
            return preferred_voice, variants, preferred_variant, language, title

        variants = (
            controller.voices.variant_choices(preferred_voice)
            if preferred_voice
            else []
        )
        preferred_variant = "AUTO" if "AUTO" in variants else (variants[0] if variants else None)
        return preferred_voice, variants, preferred_variant, language, title

    def queue_updates(message: str = ""):
        manifest = store.load()
        choices = _item_choices(manifest)
        return (
            queue_rows(manifest),
            gr.update(choices=choices, value=_preferred_item_choice(manifest)),
            message or f"Queue has {len(manifest.items)} project(s).",
        )

    def refresh_all():
        projects = controller.list_projects()
        voices = controller.voices.voice_names()
        project_value = projects[0] if projects else None
        voice_value, variants, variant_value, language_value, title = project_defaults(
            project_value,
            voices,
        )
        manifest = store.load()
        choices = _item_choices(manifest)
        note = (
            f"Loaded saved settings for {title!r}. " if title else ""
        ) + f"Found {len(projects)} project(s), {len(voices)} voice(s), {len(manifest.items)} queued item(s)."
        return (
            gr.update(choices=projects, value=project_value),
            gr.update(choices=voices, value=voice_value),
            gr.update(choices=variants, value=variant_value),
            language_value,
            queue_rows(manifest),
            gr.update(choices=choices, value=_preferred_item_choice(manifest)),
            note,
        )

    def project_settings(project_path):
        if not project_path:
            return gr.update(), gr.update(), "en", "Choose a project."
        voices = controller.voices.voice_names()
        voice_value, variants, variant_value, language_value, title = project_defaults(
            project_path,
            voices,
        )
        return (
            gr.update(choices=voices, value=voice_value),
            gr.update(choices=variants, value=variant_value),
            language_value,
            f"Loaded saved settings for {title!r}.",
        )

    def voice_variants(voice_name):
        variants = controller.voices.variant_choices(voice_name) if voice_name else []
        return gr.update(choices=variants, value=("AUTO" if "AUTO" in variants else (variants[0] if variants else None)))

    def enqueue(project_path, voice_name, variant, language, strict, auto_merge):
        if not project_path:
            raise gr.Error("Choose a project first.")
        try:
            item = store.enqueue(
                controller,
                project_path,
                voice_name=voice_name,
                voice_variant=variant or "AUTO",
                language=language or None,
                strict=bool(strict),
                auto_merge=bool(auto_merge),
            )
            return queue_updates(f"✅ Added {item.project_title!r} to queue.")
        except Exception as exc:
            raise gr.Error(f"Could not add project: {type(exc).__name__}: {exc}")

    def remove_item(choice):
        try:
            store.remove(_choice_id(choice))
            return queue_updates("Removed queue item.")
        except Exception as exc:
            raise gr.Error(f"Remove failed: {type(exc).__name__}: {exc}")

    def move_item(choice, delta):
        try:
            store.move(_choice_id(choice), int(delta))
            return queue_updates("Queue order updated.")
        except Exception as exc:
            raise gr.Error(f"Move failed: {type(exc).__name__}: {exc}")

    def requeue_item(choice):
        try:
            store.requeue(_choice_id(choice))
            return queue_updates("Project marked pending again. Completed sections will still be skipped.")
        except Exception as exc:
            raise gr.Error(f"Requeue failed: {type(exc).__name__}: {exc}")

    def clear_completed():
        store.clear_completed()
        return queue_updates("Cleared completed queue items. Project files were not deleted.")

    def request_pause():
        store.request_pause()
        return "⏸ Pause requested. Runner will stop before the next section."

    def resume_flag():
        store.resume_queue()
        return "▶ Queue resumed. Click Run Queue to continue pending work."

    def run_queue(continue_on_error):
        store.resume_queue()
        manifest = store.load()
        choices = _item_choices(manifest)
        yield (
            queue_rows(manifest),
            gr.update(choices=choices, value=_preferred_item_choice(manifest)),
            "▶ Queue started. Projects run top-to-bottom; each project resumes incomplete sections only.",
        )
        try:
            for event in runner.run(continue_on_error=bool(continue_on_error)):
                manifest = store.load()
                choices = _item_choices(manifest)
                where = f" · {event.current_section}" if event.current_section else ""
                yield (
                    queue_rows(manifest),
                    gr.update(choices=choices, value=_preferred_item_choice(manifest)),
                    f"**{event.status.upper()}** · {event.project_title or 'Queue'}{where}\n\n{event.message}",
                )
        except Exception as exc:
            manifest = store.load()
            choices = _item_choices(manifest)
            yield (
                queue_rows(manifest),
                gr.update(choices=choices, value=_preferred_item_choice(manifest)),
                f"❌ Queue runner error: {type(exc).__name__}: {exc}",
            )
            return

        manifest = store.load()
        choices = _item_choices(manifest)
        pending = sum(item.status not in {"completed", "cancelled"} for item in manifest.items)
        yield (
            queue_rows(manifest),
            gr.update(choices=choices, value=_preferred_item_choice(manifest)),
            f"Queue pass finished. {pending} item(s) still need work/review.",
        )

    initial_projects = controller.list_projects()
    initial_voices = controller.voices.voice_names()
    initial_project = initial_projects[0] if initial_projects else None
    (
        initial_voice,
        initial_variants,
        initial_variant,
        initial_language,
        initial_title,
    ) = project_defaults(initial_project, initial_voices)
    initial_manifest = store.load()
    initial_items = _item_choices(initial_manifest)

    with gr.Blocks(title="Project Queue") as demo:
        gr.Markdown(
            "# Project Queue\n"
            "Queue multiple narration projects and let Studio render them continuously. "
            "Queue state is saved to `project-queue.json`; each project still uses its own "
            "`section-status.json`, so completed sections are never rendered again after a restart."
        )

        with gr.Row():
            project = gr.Dropdown(
                label="Project",
                choices=initial_projects,
                value=initial_project,
                scale=3,
            )
            refresh = gr.Button("Refresh projects / voices", scale=1)
        with gr.Row():
            voice = gr.Dropdown(label="Voice", choices=initial_voices, value=initial_voice)
            variant = gr.Dropdown(
                label="Variant",
                choices=initial_variants,
                value=initial_variant,
            )
            language = gr.Textbox(label="Language", value=initial_language)
        with gr.Row():
            strict = gr.Checkbox(label="Strict verification", value=False)
            auto_merge = gr.Checkbox(label="Auto-merge full.wav when project completes", value=True)
            add_button = gr.Button("Add Project to Queue", variant="primary")
        add_status = gr.Markdown(
            f"Loaded saved settings for {initial_title!r}." if initial_title else "Select a project and add it to the queue."
        )

        gr.Markdown("## Queue")
        queue_table = gr.Dataframe(
            headers=QUEUE_HEADERS,
            value=queue_rows(initial_manifest),
            interactive=False,
            wrap=True,
        )
        with gr.Row():
            queue_item = gr.Dropdown(
                label="Queue item",
                choices=initial_items,
                value=_preferred_item_choice(initial_manifest),
                scale=3,
            )
            up_button = gr.Button("↑ Up")
            down_button = gr.Button("↓ Down")
            remove_button = gr.Button("Remove")
            requeue_button = gr.Button("Requeue")
            clear_button = gr.Button("Clear completed")

        gr.Markdown("## Continuous Render")
        with gr.Row():
            continue_on_error = gr.Checkbox(
                label="Continue with next project if one project fails",
                value=True,
            )
            run_button = gr.Button("Run Queue", variant="primary")
            pause_button = gr.Button("Pause after current section")
            resume_button = gr.Button("Resume queue flag")
        run_status = gr.Markdown(
            "Idle. Queue order and progress persist across Colab/runtime restarts."
        )

        refresh.click(
            refresh_all,
            outputs=[project, voice, variant, language, queue_table, queue_item, add_status],
        )
        project.change(
            project_settings,
            inputs=project,
            outputs=[voice, variant, language, add_status],
        )
        voice.change(voice_variants, inputs=voice, outputs=variant)
        add_button.click(
            enqueue,
            inputs=[project, voice, variant, language, strict, auto_merge],
            outputs=[queue_table, queue_item, add_status],
        )
        remove_button.click(
            remove_item,
            inputs=queue_item,
            outputs=[queue_table, queue_item, add_status],
        )
        up_button.click(
            lambda choice: move_item(choice, -1),
            inputs=queue_item,
            outputs=[queue_table, queue_item, add_status],
        )
        down_button.click(
            lambda choice: move_item(choice, 1),
            inputs=queue_item,
            outputs=[queue_table, queue_item, add_status],
        )
        requeue_button.click(
            requeue_item,
            inputs=queue_item,
            outputs=[queue_table, queue_item, add_status],
        )
        clear_button.click(
            clear_completed,
            outputs=[queue_table, queue_item, add_status],
        )
        pause_button.click(request_pause, outputs=run_status)
        resume_button.click(resume_flag, outputs=run_status)
        run_button.click(
            run_queue,
            inputs=continue_on_error,
            outputs=[queue_table, queue_item, run_status],
        )

    return demo
