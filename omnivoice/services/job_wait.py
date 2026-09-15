#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Condition-backed waiting helpers for durable Studio jobs."""

from __future__ import annotations

import time

from omnivoice.services.job_manager import JobRecord, StudioJobManager

_TERMINAL = {"completed", "failed", "cancelled"}


def wait_for_job(
    manager: StudioJobManager,
    job_id: str,
    *,
    timeout_seconds: float = 60.0,
) -> tuple[JobRecord, bool]:
    """Wait without busy-polling and return ``(job, timed_out)``.

    ``timeout_seconds=0`` behaves as a non-blocking state read. The helper uses
    the Job Manager condition/event stream so MCP and REST callers do not spend
    repeated requests polling ``jobs.json``.
    """

    timeout = max(0.0, min(float(timeout_seconds), 600.0))
    job = manager.get(job_id)
    if job.status in _TERMINAL or timeout == 0.0:
        return job, False if job.status in _TERMINAL else True

    cursor = job.events[-1].seq if job.events else 0
    deadline = time.monotonic() + timeout
    while job.status not in _TERMINAL:
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            return job, True
        events, job = manager.wait_for_events(
            job_id,
            cursor,
            timeout=min(remaining, 15.0),
        )
        if events:
            cursor = events[-1].seq

    return job, False
