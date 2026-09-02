#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Compatibility helper for explicit download controls on Gradio Audio players."""

from __future__ import annotations

from typing import Any


def enable_audio_download_buttons(root: Any) -> int:
    """Enable the built-in download control on every gr.Audio under ``root``.

    Gradio has used two APIs across recent releases:
    ``show_download_button=True`` in older versions and ``buttons=[...]`` in
    newer versions.  Project Studio supports both without changing individual
    callbacks or audio filepath semantics.
    """

    import gradio as gr

    seen: set[int] = set()
    stack = [root]
    updated = 0

    while stack:
        node = stack.pop()
        marker = id(node)
        if marker in seen:
            continue
        seen.add(marker)

        if isinstance(node, gr.Audio):
            if hasattr(node, "buttons"):
                current = list(getattr(node, "buttons", None) or [])
                if "download" not in current:
                    current.insert(0, "download")
                node.buttons = current
                updated += 1
            elif hasattr(node, "show_download_button"):
                node.show_download_button = True
                updated += 1

        blocks = getattr(node, "blocks", None)
        if isinstance(blocks, dict):
            stack.extend(blocks.values())

        children = getattr(node, "children", None)
        if isinstance(children, (list, tuple)):
            stack.extend(children)

    return updated
