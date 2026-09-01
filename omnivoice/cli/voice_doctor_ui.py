#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Small Gradio panel for reference-audio diagnostics."""

from __future__ import annotations

from typing import Any

from omnivoice.voice_doctor import analyze_voice_reference


METRIC_HEADERS = ["Metric", "Value", "Guidance"]


def _report_rows(report) -> list[list[Any]]:
    return [
        ["Duration", f"{report.duration_seconds:.2f} s", "Recommended 3–10 s"],
        ["Sample rate", f"{report.sample_rate} Hz", "Prefer ≥ 16 kHz"],
        ["Channels", report.channels, "Mono preferred"],
        ["Peak", f"{report.peak_dbfs:.2f} dBFS", "Avoid 0 dBFS/clipping"],
        ["RMS", f"{report.rms_dbfs:.2f} dBFS", "Rough target -30 to -12 dBFS"],
        ["Clipping", f"{report.clipping_ratio * 100:.4f}%", "Closer to 0% is better"],
        ["Silence", f"{report.silence_ratio * 100:.1f}%", "Mostly continuous speech"],
        ["DC offset", f"{report.dc_offset:.6f}", "Near zero"],
        ["Noise floor", f"{report.noise_floor_dbfs:.2f} dBFS", "Lower is cleaner"],
        ["Dynamic separation", f"{report.dynamic_range_db:.2f} dB", "Higher is generally safer"],
    ]


def build_voice_doctor_demo():
    import gradio as gr

    def analyze(audio_path):
        if not audio_path:
            raise gr.Error("Upload a reference audio file first.")
        try:
            report = analyze_voice_reference(audio_path)
        except Exception as exc:
            raise gr.Error(f"Voice Doctor failed: {type(exc).__name__}: {exc}")

        badge = "✅ Recommended" if report.recommended else "⚠ Review before cloning"
        summary = (
            f"## Voice Quality: {report.score}/100 · {report.grade}\n\n"
            f"**{badge}**\n\n"
            "This analysis is non-destructive. Voice Doctor does not modify the uploaded audio."
        )
        issues = "\n".join(f"- `{item}`" for item in report.issues) or "- None detected"
        recs = (
            "\n".join(f"- {item}" for item in report.recommendations)
            or "- Reference looks suitable. Keep the transcript exact when creating the voice."
        )
        return summary, _report_rows(report), issues, recs

    with gr.Blocks(title="Voice Doctor") as demo:
        gr.Markdown(
            "# Voice Doctor\n"
            "Check a reference clip **before** saving it to Voice Library. "
            "Best starting point: one clean speaker, roughly 3–10 seconds, little noise, no clipping."
        )
        audio = gr.Audio(label="Reference audio", type="filepath")
        analyze_button = gr.Button("Analyze reference", variant="primary")
        summary = gr.Markdown("Upload a reference and run Voice Doctor.")
        metrics = gr.Dataframe(
            headers=METRIC_HEADERS,
            interactive=False,
            wrap=True,
        )
        with gr.Row():
            issues = gr.Markdown("### Issues\n- Not analyzed yet")
            recommendations = gr.Markdown("### Recommendations\n- Not analyzed yet")

        analyze_button.click(
            analyze,
            inputs=audio,
            outputs=[summary, metrics, issues, recommendations],
        )

    return demo
