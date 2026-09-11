#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Thread-safe lazy ASR runtime for hosted/Studio entry points.

The core :class:`OmniVoice` model deliberately keeps ASR optional. Studio
launchers use this module to defer CPU Whisper construction until the first
real transcription or verification request while preserving eager startup for
explicit accelerator ASR devices.

The wrapper is model-scoped: one lock protects one model instance, successful
initialization is reused, and a failed initialization is never published as a
usable pipe. A later request can therefore retry normally.
"""

from __future__ import annotations

import logging
import threading
from types import MethodType
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CONFIGURED_ATTR = "_omnivoice_lazy_asr_configured"
_LOCK_ATTR = "_omnivoice_lazy_asr_lock"
_ORIGINAL_LOAD_ATTR = "_omnivoice_original_load_asr_model"
_ORIGINAL_TRANSCRIBE_ATTR = "_omnivoice_original_transcribe"
_LOADED_MODEL_ATTR = "_omnivoice_loaded_asr_model_name"
_LOADED_DEVICE_ATTR = "_omnivoice_loaded_asr_device"


def is_cpu_asr_device(device: object) -> bool:
    """Return ``True`` only for an explicit CPU ASR placement."""

    return str(device or "").strip().lower().startswith("cpu")


def should_defer_asr_startup(device: object) -> bool:
    """CPU ASR is deferred; explicit accelerator placement stays eager."""

    return is_cpu_asr_device(device)


def _target_model(model: Any, model_name: Optional[str]) -> object:
    return model_name if model_name is not None else getattr(model, "_asr_model_name", None)


def _target_device(model: Any, device: Optional[str]) -> object:
    if device is not None:
        return device
    configured = getattr(model, "_asr_device", None)
    if configured is not None:
        return configured
    return getattr(model, "device", None)


def _matches_loaded(model: Any, model_name: object, device: object) -> bool:
    return (
        getattr(model, "_asr_pipe", None) is not None
        and getattr(model, _LOADED_MODEL_ATTR, None) == model_name
        and getattr(model, _LOADED_DEVICE_ATTR, None) == device
    )


def configure_lazy_asr(
    model: Any,
    *,
    model_name: Optional[str] = None,
    device: Optional[str] = None,
) -> Any:
    """Install a thread-safe lazy ASR gate on one model instance.

    ``model.load_asr_model(...)`` remains callable. Repeating the same load is
    idempotent and returns the already published pipe. Requesting a different
    model/device still delegates to the original loader, preserving explicit
    reload semantics.

    ``model.transcribe(...)`` becomes a true first-use boundary: if no ASR pipe
    exists it initializes one under the same lock before invoking the original
    transcription implementation.
    """

    if model_name is not None:
        model._asr_model_name = model_name
    if device is not None:
        model._asr_device = device

    if getattr(model, _CONFIGURED_ATTR, False):
        return model

    original_load = model.load_asr_model
    original_transcribe = model.transcribe
    lock = threading.Lock()

    setattr(model, _LOCK_ATTR, lock)
    setattr(model, _ORIGINAL_LOAD_ATTR, original_load)
    setattr(model, _ORIGINAL_TRANSCRIBE_ATTR, original_transcribe)

    initial_model = _target_model(model, None)
    initial_device = _target_device(model, None)
    if getattr(model, "_asr_pipe", None) is not None:
        setattr(model, _LOADED_MODEL_ATTR, initial_model)
        setattr(model, _LOADED_DEVICE_ATTR, initial_device)

    def _lazy_load(self, model_name=None, device=None):
        target_model = _target_model(self, model_name)
        target_device = _target_device(self, device)
        if _matches_loaded(self, target_model, target_device):
            return self._asr_pipe

        with getattr(self, _LOCK_ATTR):
            if _matches_loaded(self, target_model, target_device):
                return self._asr_pipe

            logger.info(
                "Initializing ASR on first use: model=%s device=%s",
                target_model,
                target_device,
            )
            loader = getattr(self, _ORIGINAL_LOAD_ATTR)
            loader(model_name=target_model, device=target_device)
            pipe = getattr(self, "_asr_pipe", None)
            if pipe is None:
                raise RuntimeError("ASR loader completed without publishing an ASR pipeline.")
            setattr(self, _LOADED_MODEL_ATTR, target_model)
            setattr(self, _LOADED_DEVICE_ATTR, target_device)
            return pipe

    def _lazy_transcribe(self, audio):
        if getattr(self, "_asr_pipe", None) is None:
            self.load_asr_model()
        transcribe = getattr(self, _ORIGINAL_TRANSCRIBE_ATTR)
        return transcribe(audio)

    model.load_asr_model = MethodType(_lazy_load, model)
    model.transcribe = MethodType(_lazy_transcribe, model)
    setattr(model, _CONFIGURED_ATTR, True)
    return model


def ensure_asr_model(
    model: Any,
    *,
    model_name: Optional[str] = None,
    device: Optional[str] = None,
):
    """Ensure ASR exists exactly once for the requested model/device."""

    configure_lazy_asr(model, model_name=model_name, device=device)
    return model.load_asr_model(model_name=model_name, device=device)
