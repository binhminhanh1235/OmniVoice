#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""FastAPI host for OmniVoice Studio.

The same process serves the human Gradio UI and machine-facing REST API. MCP
will be mounted beside these endpoints in a later slice, using the same
application service layer rather than calling Gradio callbacks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from omnivoice.runtime_workspace import RuntimeWorkspace
from omnivoice.services.studio_service import StudioService


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
    app = FastAPI(
        title="OmniVoice Studio API",
        version="0.1.0",
        description=(
            "Machine-facing API for OmniVoice Studio. Long-running generation "
            "jobs and MCP tools are added in subsequent AI-native slices."
        ),
    )
    app.state.studio_service = service
    app.state.omnivoice_model = model

    @app.get("/health", tags=["system"])
    def health():
        return service.health()

    @app.get("/api/v1/capabilities", tags=["system"])
    def capabilities():
        return service.capabilities()

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

    if mount_ui:
        import gradio as gr

        # Import lazily so API-only tests and future headless deployments do not
        # instantiate the full UI unless requested.
        from omnivoice.cli.project_studio_voice_doctor import build_demo

        demo = build_demo(model, workspace)
        app = gr.mount_gradio_app(app, demo, path="/ui")
        app.state.studio_service = service
        app.state.omnivoice_model = model

        @app.get("/", include_in_schema=False)
        def root():
            return RedirectResponse(url="/ui")
    else:
        @app.get("/", include_in_schema=False)
        def root():
            return RedirectResponse(url="/docs")

    return app
