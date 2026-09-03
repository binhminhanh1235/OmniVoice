#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""CLI for reproducible OmniVoice raw-generation benchmarks."""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import replace
from pathlib import Path

import torch

from omnivoice.benchmark import (
    DEFAULT_BENCHMARK_TEXTS,
    benchmark_generate,
    summarize_results,
)
from omnivoice.hardware_quality import QUALITY_PRESETS, quality_policy
from omnivoice.models.omnivoice import OmniVoice, VoiceClonePrompt
from omnivoice.utils.common import get_best_device

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark OmniVoice raw TTS generation with RTF and CUDA peak memory metrics."
    )
    parser.add_argument("--model", default="k2-fsa/OmniVoice")
    parser.add_argument("--device", default=None)
    parser.add_argument("--language", default="en")
    parser.add_argument("--preset", choices=QUALITY_PRESETS, default="BALANCED")
    parser.add_argument("--num-step", type=int, default=None)
    parser.add_argument(
        "--text",
        action="append",
        default=None,
        help="Benchmark text. Repeat --text to add samples. Defaults to the built-in corpus.",
    )
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument(
        "--voice-prompt",
        default=None,
        help="Optional saved VoiceClonePrompt .pt file for clone-mode benchmarking.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional JSON output file. Parent directories are created automatically.",
    )
    return parser


def _dtype_for(device: str):
    return torch.float16 if device.startswith(("cuda", "xpu")) else torch.float32


def _format_optional(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )
    args = build_parser().parse_args(argv)
    device = str(args.device or get_best_device())

    logger.info("Loading model=%s on %s", args.model, device)
    load_started = time.perf_counter()
    model = OmniVoice.from_pretrained(
        args.model,
        device_map=device,
        dtype=_dtype_for(device),
        load_asr=False,
    )
    if device.startswith("cuda") and torch.cuda.is_available():
        torch.cuda.synchronize()
    model_load_seconds = time.perf_counter() - load_started

    generation_config = quality_policy(args.preset).generation_config()
    if args.num_step is not None:
        if args.num_step < 1:
            raise ValueError("--num-step must be >= 1")
        generation_config = replace(generation_config, num_step=int(args.num_step))

    generate_kwargs = {}
    if args.voice_prompt:
        generate_kwargs["voice_clone_prompt"] = VoiceClonePrompt.load(args.voice_prompt)

    texts = args.text or list(DEFAULT_BENCHMARK_TEXTS)
    results = benchmark_generate(
        model,
        texts,
        language=args.language or None,
        generation_config=generation_config,
        warmup=args.warmup,
        repeat=args.repeat,
        generate_kwargs=generate_kwargs,
    )
    summary = summarize_results(results)

    print(
        "sample rep chars words elapsed_s audio_s rtf peak_cuda_mb"
    )
    for item in results:
        print(
            f"{item.sample:>6} {item.repetition:>3} {item.text_chars:>5} "
            f"{item.text_words:>5} {item.elapsed_seconds:>9.3f} "
            f"{item.audio_duration_seconds:>7.3f} {item.rtf:>6.3f} "
            f"{_format_optional(item.peak_cuda_memory_mb):>12}"
        )
    print()
    print(f"model_load_seconds={model_load_seconds:.3f}")
    print(f"weighted_rtf={summary.weighted_rtf:.4f}")
    print(f"median_rtf={summary.median_rtf:.4f}")
    print(f"total_elapsed_seconds={summary.total_elapsed_seconds:.3f}")
    print(f"total_audio_seconds={summary.total_audio_seconds:.3f}")
    print(
        "max_peak_cuda_memory_mb="
        + _format_optional(summary.max_peak_cuda_memory_mb)
    )

    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": args.model,
            "device": device,
            "language": args.language,
            "preset": args.preset,
            "num_step": generation_config.num_step,
            "model_load_seconds": model_load_seconds,
            "warmup": args.warmup,
            "repeat": args.repeat,
            "summary": summary.to_dict(),
            "results": [item.to_dict() for item in results],
        }
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"json={output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
