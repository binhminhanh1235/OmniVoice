#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Voice Doctor UI: analyze once, save once, optionally run clone stability tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from omnivoice.voice_doctor import VoiceDoctorReport, analyze_voice_reference
from omnivoice.voice_library import VoiceLibrary
from omnivoice.voice_stability import VoiceStabilityReport, evaluate_voice_stability


METRIC_HEADERS = ["Metric", "Value", "Guidance"]
STABILITY_HEADERS = [
    "Sample",
    "Pass",
    "WER",
    "Similarity",
    "Word ratio",
    "WPS",
    "Pacing",
    "Transcript",
]


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


def _stability_rows(report: VoiceStabilityReport) -> list[list[Any]]:
    return [
        [
            sample.index,
            "✓" if sample.accepted else "✗",
            sample.wer,
            sample.similarity,
            sample.word_ratio,
            sample.global_wps,
            "ANOMALY" if sample.pacing_anomaly else "OK",
            sample.transcript,
        ]
        for sample in report.samples
    ]


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
    """Build analysis-only UI or full analyze/save/stability UI."""

    import gradio as gr

    can_save = model is not None and workspace is not None
    library = VoiceLibrary(Path(workspace).expanduser() / "voices") if can_save else None
    initial_voices = library.voice_names() if library is not None else []
    initial_stability_voice = initial_voices[0] if initial_voices else None
    initial_stability_variants = (
        library.variant_choices(initial_stability_voice, include_auto=False)
        if library is not None and initial_stability_voice
        else []
    )

    def analyze(audio_path):
        if not audio_path:
            raise gr.Error("Upload a reference audio file first.")
        try:
            report = analyze_voice_reference(audio_path)
        except Exception as exc:
            raise gr.Error(f"Voice Doctor failed: {type(exc).__name__}: {exc}")
        return _format_report(report)

    def refresh_stability_voices(preferred=None):
        if library is None:
            return gr.update(choices=[], value=None), gr.update(choices=[], value=None)
        names = library.voice_names()
        value = preferred if preferred in names else (names[0] if names else None)
        variants = library.variant_choices(value, include_auto=False) if value else []
        return (
            gr.update(choices=names, value=value),
            gr.update(choices=variants, value=(variants[0] if variants else None)),
        )

    def variants_for_stability_voice(name):
        if library is None or not name:
            return gr.update(choices=[], value=None)
        variants = library.variant_choices(name, include_auto=False)
        return gr.update(choices=variants, value=(variants[0] if variants else None))

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
        names = library.voice_names()
        saved_name = voice_name.strip()
        variants = library.variant_choices(saved_name, include_auto=False)
        saved_variant = (variant or "DEFAULT").strip().upper()
        return (
            summary_text,
            rows,
            issues_text,
            recs_text,
            f"✅ {save_message} You can run Stability Score below or open Project Studio.",
            gr.update(choices=names, value=saved_name),
            gr.update(choices=variants, value=saved_variant),
        )

    def run_stability(voice_name, variant):
        if not can_save or library is None:
            raise gr.Error("Voice Stability Score is unavailable in analysis-only mode.")
        if not voice_name:
            raise gr.Error("Choose a saved voice first.")
        try:
            report = evaluate_voice_stability(
                model,
                library,
                voice_name=voice_name,
                variant=variant or "DEFAULT",
            )
        except Exception as exc:
            raise gr.Error(f"Stability test failed: {type(exc).__name__}: {exc}")

        badge = "✅ Stable" if report.stable else "⚠ Needs review"
        issue_text = "\n".join(f"- {item}" for item in report.issues) or "- None detected"
        summary_text = (
            f"## Voice Stability: {report.score}/100 · {report.grade}\n\n"
            f"**{badge}** · passed {report.passed}/{report.total} clone tests\n\n"
            f"Mean WER: `{report.mean_wer:.3f}` · Mean similarity: `{report.mean_similarity:.3f}` · "
            f"Mean pacing: `{report.mean_global_wps:.2f} words/s`\n\n"
            f"### Issues\n{issue_text}\n\n"
            "This score measures clone text/pacing stability, not speaker-identity similarity."
        )
        audio_paths = [sample.audio_file for sample in report.samples]
        audio_paths += [None] * (3 - len(audio_paths))
        return (
            summary_text,
            _stability_rows(report),
            audio_paths[0],
            audio_paths[1],
            audio_paths[2],
        )

    with gr.Blocks(title="Voice Doctor") as demo:
        gr.Markdown(
            "# Voice Doctor\n"
            "Upload the reference **once**. Analyze it, save the same file directly to "
            "Voice Library, then optionally run three real clone tests."
        )
        audio = gr.Audio(label="Reference audio", type="filepath")
        analyze_button = gr.Button("Analyze reference", variant="primary")
        summary = gr.Markdown("Upload a reference and run Voice Doctor.")
        metrics = gr.Dataframe(headers=METRIC_HEADERS, interactive=False, wrap=True)
        with gr.Row():
            issues = gr.Markdown("### Issues\n- Not analyzed yet")
            recommendations = gr.Markdown("### Recommendations\n- Not analyzed yet")

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

            gr.Markdown(
                "## Voice Stability Score\n"
                "Optional GPU check. Generates three short samples, ASR-checks them, and measures pacing consistency."
            )
            with gr.Row():
                stability_voice = gr.Dropdown(
                    label="Saved voice",
                    choices=initial_voices,
                    value=initial_stability_voice,
                )
                stability_variant = gr.Dropdown(
                    label="Variant",
                    choices=initial_stability_variants,
                    value=(initial_stability_variants[0] if initial_stability_variants else None),
                )
                refresh_stability = gr.Button("Refresh saved voices")
                stability_button = gr.Button("Run 3 Clone Tests", variant="primary")
            stability_summary = gr.Markdown("Stability test not run yet.")
            stability_table = gr.Dataframe(
                headers=STABILITY_HEADERS,
                interactive=False,
                wrap=True,
            )
            with gr.Row():
                stability_audio_1 = gr.Audio(label="Clone test 1", type="filepath")
                stability_audio_2 = gr.Audio(label="Clone test 2", type="filepath")
                stability_audio_3 = gr.Audio(label="Clone test 3", type="filepath")

        analyze_button.click(
            analyze,
            inputs=audio,
            outputs=[summary, metrics, issues, recommendations],
        )

        if can_save:
            save_button.click(
                analyze_and_save,
                inputs=[audio, voice_name, variant, ref_text, language, allow_low_score],
                outputs=[
                    summary,
                    metrics,
                    issues,
                    recommendations,
                    save_status,
                    stability_voice,
                    stability_variant,
                ],
            )
            refresh_stability.click(
                refresh_stability_voices,
                inputs=stability_voice,
                outputs=[stability_voice, stability_variant],
            )
            stability_voice.change(
                variants_for_stability_voice,
                inputs=stability_voice,
                outputs=stability_variant,
            )
            stability_button.click(
                run_stability,
                inputs=[stability_voice, stability_variant],
                outputs=[
                    stability_summary,
                    stability_table,
                    stability_audio_1,
                    stability_audio_2,
                    stability_audio_3,
                ],
            )

    return demo
