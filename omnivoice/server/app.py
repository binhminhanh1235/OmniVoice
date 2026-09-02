#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""FastAPI host for OmniVoice Studio."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from omnivoice.runtime_workspace import RuntimeWorkspace
from omnivoice.services.job_manager import StudioJobManager
from omnivoice.services.studio_service import StudioService


def _job_payload(job, *, include_events: bool = False) -> dict[str, Any]:
    payload = job.to_dict()
    if not include_events:
        payload.pop("events", None)
    return payload


def create_studio_app(
    model: Any,
    workspace: str | Path,
    *,
    runtime: Optional[RuntimeWorkspace] = None,
    mount_ui: bool = True,
):
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import RedirectResponse

    service = StudioService(model, workspace, runtime=runtime)
    jobs = StudioJobManager(workspace)

    @asynccontextmanager
    async def lifespan(_app):
        jobs.start()
        try:
            yield
        finally:
            jobs.shutdown()

    app = FastAPI(
        title="OmniVoice Studio API",
        version="0.2.0",
        description=(
            "Machine-facing API for OmniVoice Studio with persistent single-GPU "
            "job scheduling. Generation handlers are added in the next slice."
        ),
        lifespan=lifespan,
    )
    app.state.studio_service = service
    app.state.job_manager = jobs
    app.state.omnivoice_model = model

    @app.get("/health", tags=["system"])
    def health():
        payload = service.health()
        payload["job_manager"] = "ready"
        return payload

    @app.get("/api/v1/capabilities", tags=["system"])
    def capabilities():
        payload = service.capabilities()
        payload["features"]["job_manager"] = True
        payload["endpoints"]["jobs"] = "/api/v1/jobs"
        return payload

    @app.get("/api/v1/hardware", tags=["system"])
    def hardware():
        return service.hardware()

    @app.get("/api/v1/projects", tags=["projects"])
    def list_projects(
        status: Optional[list[str]] = Query(
            default=None,
            description="Optional project statuses, e.g. PENDING or GENERATING.",
        )
    ):
        try:
            return {"items": service.list_projects(status)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v1/projects/{project_id}", tags=["projects"])
    def get_project(project_id: str):
        try:
            return service.get_project(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Project not found") from exc

    @app.get("/api/v1/queue", tags=["queue"])
    def queue_summary():
        return service.queue_summary()

    @app.get("/api/v1/jobs", tags=["jobs"])
    def list_jobs():
        return {"items": [_job_payload(job) for job in jobs.list_jobs()]}

    @app.get("/api/v1/jobs/{job_id}", tags=["jobs"])
    def get_job(job_id: str):
        try:
            return _job_payload(jobs.get(job_id), include_events=True)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.get("/api/v1/jobs/{job_id}/events", tags=["jobs"])
    def get_job_events(job_id: str, after: int = 0):
        try:
            return {
                "items": [asdict(event) for event in jobs.events_after(job_id, after)]
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.post("/api/v1/jobs/{job_id}/cancel", tags=["jobs"])
    def cancel_job(job_id: str):
        try:
            return _job_payload(jobs.request_cancel(job_id), include_events=True)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    if mount_ui:
        import gradio as gr

        from omnivoice.cli.project_studio_voice_doctor import build_demo

        demo = build_demo(model, workspace)
        app = gr.mount_gradio_app(app, demo, path="/ui")
        app.state.studio_service = service
        app.state.job_manager = jobs
        app.state.omnivoice_model = model

        @app.get("/", include_in_schema=False)
        def root():
            return RedirectResponse(url="/ui")
    else:
        @app.get("/", include_in_schema=False)
        def root():
            return RedirectResponse(url="/docs")

    return app
