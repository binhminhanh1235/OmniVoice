#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0

"""Full OmniVoice Studio launcher with a consolidated project-first UX."""

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
from omnivoice.cli.project_studio_quality import (
    build_hardware_quality_demo,
    install_quality_controller,
)
from omnivoice.cli.project_workspace import build_project_workspace_demo
from omnivoice.cli.section_export_ui import build_section_export_demo
from omnivoice.cli.section_history_ui import build_section_history_demo
from omnivoice.cli.text_doctor_ui import build_text_doctor_demo
from omnivoice.cli.unified_controller import UnifiedWorkspaceController
from omnivoice.cli.voice_doctor_ui import build_voice_doctor_demo
from omnivoice.hardware_quality import detect_hardware
from omnivoice.runtime_workspace import detect_runtime_workspace
from omnivoice.utils.common import get_best_device

logger = logging.getLogger(__name__)


def build_demo(model, workspace: str | Path):
    import gradio as gr

    # Keep one controller contract across the normal workspace, queue, recovery,
    # history, quality and advanced settings. Project-shaping metadata such as
    # speak_section_titles is preserved when later generation settings are saved.
    quality_module.QualityPresetProjectStudioController = UnifiedWorkspaceController
    install_quality_controller()

    project_workspace = build_project_workspace_demo(
        model,
        workspace,
        controller_cls=UnifiedWorkspaceController,
    )
    text_doctor = build_text_doctor_demo()
    history = build_section_history_demo(
        model,
        workspace,
        controller_cls=UnifiedWorkspaceController,
    )
    projects = gr.TabbedInterface(
        [project_workspace, text_doctor, history],
        ["Workspace", "Text Doctor", "Section History"],
        title="Projects",
    )

    project_queue = build_project_queue_demo(
        model,
        workspace,
        controller_cls=UnifiedWorkspaceController,
    )
    generation_control = build_generation_control_demo(
        model,
        workspace,
        controller_cls=UnifiedWorkspaceController,
    )
    jobs = gr.TabbedInterface(
        [project_queue, generation_control],
        ["Queue", "Pause / Resume"],
        title="Jobs",
    )

    voice_doctor = build_voice_doctor_demo(model, workspace)

    hardware = build_hardware_quality_demo(model, workspace)
    advanced = build_advanced_settings_demo(
        model,
        workspace,
        controller_cls=UnifiedWorkspaceController,
    )
    downloads = build_section_export_demo(
        model,
        workspace,
        controller_cls=UnifiedWorkspaceController,
    )
    data_management = build_data_management_demo(
        model,
        workspace,
        controller_cls=UnifiedWorkspaceController,
    )
    settings = gr.TabbedInterface(
        [hardware, advanced, downloads, data_management],
        ["Hardware & Quality", "Advanced", "Export", "Storage & Backup"],
        title="Settings",
    )

    demo = gr.TabbedInterface(
        [projects, jobs, voice_doctor, settings],
        ["1. Projects", "2. Jobs", "3. Voice Library", "4. Settings"],
        title="OmniVoice Studio",
    )
    audio_players = enable_audio_download_buttons(demo)
    logger.info("Enabled download controls for %s Studio audio player(s)", audio_players)
    return demo


def build_parser() -> argparse.ArgumentParser:
    runtime = detect_runtime_workspace()
    parser = argparse.ArgumentParser(
        description=(
            "Launch OmniVoice Studio with a unified project workflow, voice tools, "
            "persistent jobs, quality presets and advanced settings"
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
            "dedicate cuda:1 to ASR."
        ),
    )
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
            "Remote persistence is optional and can be configured from Settings > Storage & Backup."
        )

    device = args.device or get_best_device()
    hardware = detect_hardware()
    logger.info("Hardware: %s", hardware.summary())
    for note in hardware.notes:
        logger.info("Hardware note: %s", note)
    logger.info(
        "Loading OmniVoice model=%s device=%s asr_device=%s",
        args.model,
        device,
        args.asr_device,
    )
    model = OmniVoice.from_pretrained(
        args.model,
        device_map=device,
        dtype=torch.float16,
        load_asr=True,
        asr_model_name=args.asr_model,
        asr_device=args.asr_device,
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
