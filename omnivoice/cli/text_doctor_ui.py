#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Gradio panel for non-destructive Project Studio Text Doctor."""

from __future__ import annotations

from omnivoice.text_doctor import changes_as_rows, inspect_script


HEADERS = ["Line", "Severity", "Kind", "Before", "After", "Note"]


def build_text_doctor_demo():
    import gradio as gr

    def analyze(script: str):
        try:
            result = inspect_script(script or "")
            summary = (
                f"Safe fixes: **{result.safe_change_count}** · "
                f"Review hints: **{result.review_count}**. "
                "Only safe formatting/encoding artifacts were changed automatically."
            )
            return (
                result.cleaned,
                changes_as_rows(result.changes),
                result.diff or "No safe text changes.",
                summary,
            )
        except Exception as exc:
            raise gr.Error(f"Text Doctor failed: {type(exc).__name__}: {exc}")

    with gr.Blocks(title="Text Doctor") as demo:
        gr.Markdown(
            "# Text Doctor\n"
            "Inspect the full Markdown script before creating a project. "
            "HTML entities, invisible characters, Markdown hard-break backslashes, "
            "tabs, and unsafe whitespace are cleaned. Numbers, abbreviations, and "
            "unknown directives are **review hints only** and are not silently rewritten."
        )
        script = gr.Textbox(
            label="Original project script",
            lines=18,
            placeholder="Paste the full # title / ## S01 ... script here",
        )
        analyze_button = gr.Button("Analyze & clean safe issues", variant="primary")
        summary = gr.Markdown("Paste a script and run Text Doctor.")
        cleaned = gr.Textbox(
            label="Cleaned script — review, then copy to Project Setup",
            lines=18,
        )
        changes = gr.Dataframe(
            headers=HEADERS,
            interactive=False,
            wrap=True,
        )
        diff = gr.Code(
            label="Visible diff",
            language=None,
            lines=14,
        )

        analyze_button.click(
            analyze,
            inputs=script,
            outputs=[cleaned, changes, diff, summary],
        )

    return demo
