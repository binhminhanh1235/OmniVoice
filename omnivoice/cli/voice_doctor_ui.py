#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Gradio panel for reference-audio diagnostics and one-upload voice saving."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from omnivoice.voice_doctor import VoiceDoctorReport, analyze_voice_reference
from omnivoice.voice_library import VoiceLibrary


METRIC_HEADERS = ["Metric", "Value", "Guidance"]


def _report_rows(report: VoiceDoctorReport) -> list[list[Any]]:
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


def _format_report(report: VoiceDoctorReport) -> tuple[str, list[list[Any]], str, str]:
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


def save_voice_reference(
    model: Any,
    library: VoiceLibrary,
    *,
    audio_path: str | Path,
    voice_name: str,
    variant: str = "DEFAULT",
    ref_text: Optional[str] = None,
    language: Optional[str] = None,
    allow_low_score: bool = False,
) -> tuple[VoiceDoctorReport, str]:
    """Analyze the exact file being saved, then persist one Voice Library variant."""

    if not audio_path:
        raise ValueError("Upload a reference audio file first")
    if not voice_name or not voice_name.strip():
        raise ValueError("Voice name must be non-empty")

    report = analyze_voice_reference(audio_path)
    if not report.recommended and not allow_low_score:
        issue_text = ", ".join(report.issues) or "quality score below recommendation"
        raise ValueError(
            f"Reference scored {report.score}/100 ({report.grade}) and is not recommended: "
            f"{issue_text}. Fix the reference or enable the explicit override."
        )

    entry = library.create_from_reference(
        model,
        name=voice_name.strip(),
        reference_audio=audio_path,
        ref_text=ref_text.strip() if ref_text and ref_text.strip() else None,
        variant=(variant or "DEFAULT").strip().upper(),
        language=language.strip() if language and language.strip() else None,
    )
    variants = ", ".join(sorted(entry.variants))
    return report, f"Saved voice {entry.name!r}. Variants: {variants}."


def build_voice_doctor_demo(
    model: Any = None,
    workspace: str | Path | None = None,
):
    """Build analysis-only UI or analysis+save UI when model/workspace are supplied."""

    import gradio as gr

    can_save = model is not None and workspace is not None
    library = VoiceLibrary(Path(workspace).expanduser() / "voices") if can_save else None

    def analyze(audio_path):
        if not audio_path:
            raise gr.Error("Upload a reference audio file first.")
        try:
            report = analyze_voice_reference(audio_path)
        except Exception as exc:
            raise gr.Error(f"Voice Doctor failed: {type(exc).__name__}: {exc}")
        return _format_report(report)

    def analyze_and_save(
        audio_path,
        voice_name,
        variant,
        ref_text,
        language,
        allow_low_score,
    ):
        if not can_save or library is None:
            raise gr.Error("Voice Library saving is unavailable in analysis-only mode.")
        try:
            report, save_message = save_voice_reference(
                model,
                library,
                audio_path=audio_path,
                voice_name=voice_name,
                variant=variant or "DEFAULT",
                ref_text=ref_text,
                language=language,
                allow_low_score=bool(allow_low_score),
            )
        except Exception as exc:
            raise gr.Error(f"Voice not saved: {type(exc).__name__}: {exc}")

        summary_text, rows, issues_text, recs_text = _format_report(report)
        return (
            summary_text,
            rows,
            issues_text,
            recs_text,
            f"✅ {save_message} Open Project Studio and click Refresh Projects / Voices.",
        )

    with gr.Blocks(title="Voice Doctor") as demo:
        gr.Markdown(
            "# Voice Doctor\n"
            "Upload the reference **once**. Analyze it, then save the same file directly to "
            "Voice Library. Best starting point: one clean speaker, roughly 3–10 seconds, "
            "little noise, no clipping."
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

        with gr.Group(visible=can_save):
            gr.Markdown(
                "## Save this exact reference\n"
                "A recommended reference can be encoded and stored without uploading it again."
            )
            with gr.Row():
                voice_name = gr.Textbox(label="Voice name", placeholder="Warm American Male")
                variant = gr.Dropdown(
                    label="Variant",
                    choices=["DEFAULT", "WARM", "SOFT", "EMPHASIZE", "PRAYER"],
                    value="DEFAULT",
                    allow_custom_value=True,
                )
                language = gr.Textbox(label="Language", value="en")
            ref_text = gr.Textbox(
                label="Exact reference transcript (recommended)",
                lines=3,
                placeholder="Paste exactly what the speaker says...",
            )
            allow_low_score = gr.Checkbox(
                label="Allow save after review even if Voice Doctor does not recommend it",
                value=False,
            )
            save_button = gr.Button("Analyze & Save Voice")
            save_status = gr.Markdown("Not saved yet.")

            save_button.click(
                analyze_and_save,
                inputs=[
                    audio,
                    voice_name,
                    variant,
                    ref_text,
                    language,
                    allow_low_score,
                ],
                outputs=[summary, metrics, issues, recommendations, save_status],
            )

    return demo
