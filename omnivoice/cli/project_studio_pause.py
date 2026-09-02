#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Pause-aware controller for cooperative Project Studio generation."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from omnivoice.cli.project_studio_quality import QualityPresetProjectStudioController
from omnivoice.generation_control import pause_requested

logger = logging.getLogger(__name__)


class PauseAwareQualityPresetProjectStudioController(QualityPresetProjectStudioController):
    """Wait between section calls while a project pause is requested.

    The live Studio already invokes ``generate()`` one section at a time. By
    waiting at the start of the next call, a Pause request never interrupts an
    active TTS inference or leaves a partially assembled section behind.
    """

    pause_poll_seconds = 0.25

    def _wait_for_resume(self, project_path: str | Path) -> None:
        announced = False
        while pause_requested(project_path):
            if not announced:
                logger.info(
                    "Generation paused for project=%s; waiting for Resume before next section",
                    project_path,
                )
                announced = True
            time.sleep(self.pause_poll_seconds)
        if announced:
            logger.info("Generation resumed for project=%s", project_path)

    def generate(self, project_path: str | Path, **kwargs):
        self._wait_for_resume(project_path)
        return super().generate(project_path, **kwargs)
