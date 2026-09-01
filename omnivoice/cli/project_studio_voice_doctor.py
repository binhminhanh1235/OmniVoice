#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Text Doctor + Voice Doctor + Project Studio + persistent Project Queue."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import torch

from omnivoice import OmniVoice
from omnivoice.cli.project_queue_ui import build_project_queue_demo
from omnivoice.cli.project_studio import default_workspace
from omnivoice.cli.project_studio_resume import (
    SectionResumeProjectStudioController,
    build_demo as build_resume_project_studio,
)
from omnivoice.cli.text_doctor_ui import build_text_doctor_demo
from omnivoice.cli.voice_doctor_ui import build_voice_doctor_demo
from omnivoice.utils.common import get_best_device

logger = logging.getLogger(__name__)


def build_demo(model, workspace: str | Path):
    import gradio as gr

    text_doctor = build_text_doctor_demo()
    # Pass the already-loaded model and the same workspace so Voice Doctor can
    # save the analyzed reference directly into the shared Voice Library.
    voice_doctor = build_voice_doctor_demo(model, workspace)
    studio = build_resume_project_studio(model, workspace)
    project_queue = build_project_queue_demo(
        model,
        workspace,
        controller_cls=SectionResumeProjectStudioController,
    )
    return gr.TabbedInterface(
        [text_doctor, voice_doctor, studio, project_queue],
        [
            "1. Text Doctor",
            "2. Voice Doctor",
            "3. Project Studio",
            "4. Project Queue",
        ],
        title="OmniVoice Project Studio",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Launch OmniVoice Project Studio with Text Doctor, Voice Doctor, "
            "persistent section resume, and a crash-safe multi-project queue"
        )
    )
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
    args = build_parser().parse_args(argv)
    device = args.device or get_best_device()
    logger.info("Loading OmniVoice model=%s device=%s", args.model, device)
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
        show_error=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
