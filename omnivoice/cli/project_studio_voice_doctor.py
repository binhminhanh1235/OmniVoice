#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0

"""Full Project Studio launcher with quality-aware queue and hardware presets."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import torch

from omnivoice import OmniVoice
from omnivoice.cli import project_studio_quality as quality_module
from omnivoice.cli.advanced_settings_ui import build_advanced_settings_demo
from omnivoice.cli.audio_download_ui import enable_audio_download_buttons
from omnivoice.cli.data_management_ui import build_data_management_demo
from omnivoice.cli.generation_control_ui import build_generation_control_demo
from omnivoice.cli.project_queue_ui import build_project_queue_demo
from omnivoice.cli.project_studio_advanced import (
    AdvancedSettingsProjectStudioController,
)
from omnivoice.cli.project_studio_quality import (
    build_hardware_quality_demo,
    build_quality_project_demo,
    install_quality_controller,
)
from omnivoice.cli.section_export_ui import build_section_export_demo
from omnivoice.cli.text_doctor_ui import build_text_doctor_demo
from omnivoice.cli.voice_doctor_ui import build_voice_doctor_demo
from omnivoice.hardware_quality import detect_hardware
from omnivoice.runtime_workspace import detect_runtime_workspace
from omnivoice.utils.common import get_best_device

logger = logging.getLogger(__name__)


def build_demo(model, workspace: str | Path):
    import gradio as gr

    # Existing Studio builders resolve their controller class from
    # project_studio_quality at runtime. Replace that integration seam with the
    # pause-aware + advanced-settings subclass so Generate/Resume, Queue,
    # History and exports all share one project settings contract.
    quality_module.QualityPresetProjectStudioController = (
        AdvancedSettingsProjectStudioController
    )
    install_quality_controller()

    text_doctor = build_text_doctor_demo()
    voice_doctor = build_voice_doctor_demo(model, workspace)
    studio = build_quality_project_demo(model, workspace)
    generation_control = build_generation_control_demo(
        model,
        workspace,
        controller_cls=AdvancedSettingsProjectStudioController,
    )
    project_queue = build_project_queue_demo(
        model,
        workspace,
        controller_cls=AdvancedSettingsProjectStudioController,
    )
    hardware = build_hardware_quality_demo(model, workspace)
    advanced = build_advanced_settings_demo(
        model,
        workspace,
        controller_cls=AdvancedSettingsProjectStudioController,
    )
    downloads = build_section_export_demo(
        model,
        workspace,
        controller_cls=AdvancedSettingsProjectStudioController,
    )
    data_management = build_data_management_demo(
        model,
        workspace,
        controller_cls=AdvancedSettingsProjectStudioController,
    )
    demo = gr.TabbedInterface(
        [
            text_doctor,
            voice_doctor,
            studio,
            generation_control,
            project_queue,
            hardware,
            advanced,
            downloads,
            data_management,
        ],
        [
            "1. Text Doctor",
            "2. Voice Doctor",
            "3. Project Studio",
            "4. Pause / Resume",
            "5. Project Queue",
            "6. Hardware & Quality",
            "7. Advanced Settings",
            "8. Section MP3 Downloads",
            "9. Data Management",
        ],
        title="OmniVoice Project Studio",
    )
    audio_players = enable_audio_download_buttons(demo)
    logger.info("Enabled download controls for %s Studio audio player(s)", audio_players)
    return demo


def build_parser() -> argparse.ArgumentParser:
    runtime = detect_runtime_workspace()
    parser = argparse.ArgumentParser(
        description=(
            "Launch OmniVoice Project Studio with Text Doctor, Voice Doctor, "
            "persistent resume/queue, hardware detection, quality presets and "
            "optional per-project advanced generation settings"
        )
    )
    parser.add_argument("--model", default="k2-fsa/OmniVoice")
    parser.add_argument("--device", default=None)
    parser.add_argument(
        "--workspace",
        default=str(runtime.root),
        help=(
            "Execution workspace. Kaggle defaults to "
            "/kaggle/working/OmniVoiceStudio (local ephemeral SSD)."
        ),
    )
    parser.add_argument("--asr-model", default="openai/whisper-small.en")
    parser.add_argument(
        "--asr-device",
        default="cpu",
        help=(
            "ASR device. A single T4 usually keeps ASR on cpu; dual-T4 Kaggle can "
            "dedicate cuda:1 to ASR. CPU ASR is loaded lazily on first verification."
        ),
    )
    parser.add_argument("--ip", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true", default=False)
    return parser


def _should_eager_load_asr(device: str) -> bool:
    """Keep dedicated accelerator ASR eager while removing CPU ASR from startup."""

    return str(device).lower().startswith(("cuda", "xpu"))


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )
    args = build_parser().parse_args(argv)
    runtime = detect_runtime_workspace()
    workspace = Path(args.workspace).expanduser()
    workspace.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Runtime environment=%s execution_workspace=%s persistence=%s",
        runtime.environment,
        workspace,
        runtime.persistence_backend,
    )
    if runtime.environment == "kaggle":
        logger.warning(
            "Kaggle execution workspace is local/ephemeral. "
            "Remote persistence is optional and can be configured from the Data Management tab."
        )

    device = args.device or get_best_device()
    hardware = detect_hardware()
    logger.info("Hardware: %s", hardware.summary())
    for note in hardware.notes:
        logger.info("Hardware note: %s", note)

    eager_asr = _should_eager_load_asr(args.asr_device)
    logger.info(
        "Loading OmniVoice model=%s device=%s asr_device=%s asr_startup=%s",
        args.model,
        device,
        args.asr_device,
        "eager" if eager_asr else "lazy",
    )
    model = OmniVoice.from_pretrained(
        args.model,
        device_map=device,
        dtype=torch.float16,
        load_asr=eager_asr,
        asr_model_name=args.asr_model,
        asr_device=args.asr_device,
    )
    if not eager_asr:
        logger.info(
            "CPU ASR deferred until the first transcription/verification request; Studio UI can start without loading Whisper."
        )

    demo = build_demo(model, workspace)
    demo.queue().launch(
        server_name=args.ip,
        server_port=args.port,
        share=args.share,
        show_error=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
