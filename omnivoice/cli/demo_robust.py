#!/usr/bin/env python3
# Copyright    2026  OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Robust Gradio entry point for OmniVoice.

The original UI is reused, but long inputs are routed through
``RobustLongFormGenerator`` so each semantic chunk can be verified and retried.
Short inputs keep the original direct generation path.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any, Callable, Optional

import numpy as np
import torch

from omnivoice import (
    OmniVoice,
    OmniVoiceGenerationConfig,
    RobustLongFormConfig,
    RobustLongFormGenerator,
)
from omnivoice.cli.demo import build_demo, build_parser as build_base_parser
from omnivoice.robust_longform import clean_tts_text, semantic_chunk_text
from omnivoice.utils.common import get_best_device

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Extend the original demo CLI with robust long-form controls."""

    parser = build_base_parser()
    parser.description = (
        "Launch the OmniVoice Gradio demo with semantic chunking, "
        "ASR verification, and failed-chunk retries."
    )
    parser.set_defaults(asr_model="openai/whisper-small")
    parser.add_argument(
        "--no-robust",
        action="store_true",
        default=False,
        help="Use the original direct model.generate path for every input.",
    )
    parser.add_argument(
        "--robust-min-words",
        type=int,
        default=12,
        help="Minimum words for robust verification when text has one sentence.",
    )
    parser.add_argument(
        "--robust-max-chunk-words",
        type=int,
        default=20,
        help="Maximum words in one semantic generation chunk.",
    )
    parser.add_argument(
        "--robust-max-chunk-chars",
        type=int,
        default=180,
        help="Maximum characters in one semantic generation chunk.",
    )
    parser.add_argument(
        "--robust-retries",
        type=int,
        default=3,
        help="Maximum generation attempts for a failed chunk.",
    )
    parser.add_argument(
        "--robust-max-wer",
        type=float,
        default=0.18,
        help="Maximum accepted chunk-level word error rate.",
    )
    parser.add_argument(
        "--robust-strict",
        action="store_true",
        default=False,
        help="Raise an error instead of accepting an unverified best candidate.",
    )
    parser.add_argument(
        "--asr-device",
        default="cpu",
        help="Device for Whisper verification, normally cpu on Colab T4.",
    )
    parser.add_argument(
        "--position-temperature",
        type=float,
        default=1.0,
        help="Position sampling temperature. Lower values improve repeatability.",
    )
    return parser


def _to_gradio_audio(audio: np.ndarray, sampling_rate: int):
    """Return clipped int16 audio in the tuple format expected by Gradio."""

    waveform = np.asarray(audio, dtype=np.float32).reshape(-1)
    waveform = np.clip(waveform, -1.0, 1.0)
    waveform = (waveform * 32767.0).astype(np.int16)
    return sampling_rate, waveform


def _should_use_robust(
    text: str,
    *,
    enabled: bool,
    min_words: int,
    max_chunk_words: int,
    max_chunk_chars: int,
    duration: Optional[float],
) -> bool:
    """Choose robust mode for long/multi-sentence input.

    A manually supplied total duration cannot safely be applied to each chunk,
    so duration requests intentionally stay on the direct path.
    """

    if not enabled:
        return False
    if duration is not None and float(duration) > 0:
        return False

    chunks = semantic_chunk_text(
        text,
        max_words=max_chunk_words,
        max_chars=max_chunk_chars,
    )
    return len(chunks) > 1 or len(text.split()) >= min_words


def create_generate_fn(
    model: OmniVoice,
    robust_config: RobustLongFormConfig,
    *,
    robust_enabled: bool = True,
    robust_min_words: int = 12,
    position_temperature: float = 1.0,
) -> Callable[..., tuple[Any, str]]:
    """Create the callback consumed by :func:`omnivoice.cli.demo.build_demo`."""

    robust_generator = RobustLongFormGenerator(model, robust_config)
    sampling_rate = int(model.sampling_rate)

    def generate(
        text,
        language,
        ref_audio,
        instruct,
        num_step,
        guidance_scale,
        denoise,
        speed,
        duration,
        preprocess_prompt,
        postprocess_output,
        mode,
        ref_text=None,
    ):
        if not text or not text.strip():
            return None, "Please enter the text to synthesize."

        original_text = text.strip()
        normalized_text = clean_tts_text(original_text)
        normalized_ref_text = (
            clean_tts_text(ref_text) if ref_text and ref_text.strip() else None
        )

        generation_config = OmniVoiceGenerationConfig(
            num_step=int(num_step or 32),
            guidance_scale=(
                float(guidance_scale) if guidance_scale is not None else 2.0
            ),
            position_temperature=float(position_temperature),
            class_temperature=0.0,
            denoise=bool(denoise) if denoise is not None else True,
            preprocess_prompt=bool(preprocess_prompt),
            postprocess_output=bool(postprocess_output),
            # Direct mode keeps OmniVoice internal chunking. The robust
            # wrapper overrides this to 1e9 after semantic splitting.
            audio_chunk_threshold=30.0,
            pad_duration=0.0,
            fade_duration=0.0,
            output_min_silence_ms=650,
            output_keep_silence_ms=180,
            output_lead_silence_ms=80,
            output_trail_silence_ms=130,
            output_target_lead_silence_ms=80,
            output_target_trail_silence_ms=130,
        )

        lang = language if language and language != "Auto" else None
        generate_kwargs: dict[str, Any] = {"language": lang}

        if speed is not None and float(speed) != 1.0:
            generate_kwargs["speed"] = float(speed)

        duration_value = (
            float(duration) if duration is not None and float(duration) > 0 else None
        )

        if mode == "clone":
            if not ref_audio:
                return None, "Please upload a reference audio."
            try:
                voice_prompt = model.create_voice_clone_prompt(
                    ref_audio=ref_audio,
                    ref_text=normalized_ref_text,
                    preprocess_prompt=bool(preprocess_prompt),
                )
            except Exception as exc:
                return None, (
                    f"Reference processing failed: {type(exc).__name__}: {exc}"
                )
            generate_kwargs["voice_clone_prompt"] = voice_prompt

        if instruct and instruct.strip():
            generate_kwargs["instruct"] = clean_tts_text(instruct)

        use_robust = _should_use_robust(
            normalized_text,
            enabled=robust_enabled,
            min_words=robust_min_words,
            max_chunk_words=robust_config.max_chunk_words,
            max_chunk_chars=robust_config.max_chunk_chars,
            duration=duration_value,
        )

        try:
            if use_robust:
                result = robust_generator.generate(
                    normalized_text,
                    generation_config=generation_config,
                    **generate_kwargs,
                )
                verified = sum(report.accepted for report in result.reports)
                total = len(result.reports)
                retries = sum(max(0, report.attempts - 1) for report in result.reports)
                failed = total - verified
                verification = (
                    f"{verified}/{total} chunks verified"
                    if robust_config.verify_with_asr
                    else f"{total} chunks generated; ASR verification disabled"
                )
                status = (
                    f"Done (robust). {verification}; "
                    f"retries={retries}; unverified={failed}."
                )
                audio = result.audio
            else:
                direct_kwargs = dict(generate_kwargs)
                if duration_value is not None:
                    direct_kwargs["duration"] = duration_value
                audios = model.generate(
                    text=normalized_text,
                    generation_config=generation_config,
                    **direct_kwargs,
                )
                audio = np.asarray(audios[0], dtype=np.float32)
                status = "Done (direct short-form mode)."
                if duration_value is not None and robust_enabled:
                    status += " Robust mode was skipped because Duration was set."

            if normalized_text != original_text:
                status += " HTML entities/typographic whitespace were normalized."

            return _to_gradio_audio(audio, sampling_rate), status
        except Exception as exc:
            logger.exception("Gradio generation failed")
            return None, f"Error: {type(exc).__name__}: {exc}"

    return generate


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.robust_min_words < 1:
        parser.error("--robust-min-words must be >= 1")
    if args.robust_max_chunk_words < 4:
        parser.error("--robust-max-chunk-words must be >= 4")
    if args.robust_max_chunk_chars < 40:
        parser.error("--robust-max-chunk-chars must be >= 40")
    if args.robust_retries < 1:
        parser.error("--robust-retries must be >= 1")
    if not 0.0 <= args.robust_max_wer <= 1.0:
        parser.error("--robust-max-wer must be between 0 and 1")

    device = args.device or get_best_device()
    checkpoint = args.model
    if not checkpoint:
        parser.print_help()
        return 0

    verify_with_asr = not args.no_asr
    logger.info(
        "Loading model from %s, device=%s, robust=%s, ASR=%s on %s",
        checkpoint,
        device,
        not args.no_robust,
        verify_with_asr,
        args.asr_device,
    )
    model = OmniVoice.from_pretrained(
        checkpoint,
        device_map=device,
        dtype=torch.float16,
        load_asr=verify_with_asr,
        asr_model_name=args.asr_model,
        asr_device=args.asr_device,
    )
    print("Model loaded.")

    robust_config = RobustLongFormConfig(
        max_chunk_words=args.robust_max_chunk_words,
        max_chunk_chars=args.robust_max_chunk_chars,
        max_retries=args.robust_retries,
        max_split_depth=2,
        verify_with_asr=verify_with_asr,
        asr_model_name=args.asr_model,
        asr_device=args.asr_device,
        max_wer=args.robust_max_wer,
        min_similarity=0.82,
        min_word_ratio=0.74,
        max_word_ratio=1.30,
        pause_ms=320,
        paragraph_pause_ms=460,
        strict=args.robust_strict,
        # Preserve a small amount of real silence before onset consonants such
        # as the /p/ in "Patterns" instead of forcing zero-length edges.
        exact_chunk_edges=False,
    )
    generate_fn = create_generate_fn(
        model,
        robust_config,
        robust_enabled=not args.no_robust,
        robust_min_words=args.robust_min_words,
        position_temperature=args.position_temperature,
    )
    demo = build_demo(model, checkpoint, generate_fn=generate_fn)
    demo.queue().launch(
        server_name=args.ip,
        server_port=args.port,
        share=args.share,
        root_path=args.root_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
