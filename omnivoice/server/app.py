#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""FastAPI host for OmniVoice Studio."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from omnivoice.artifacts import ArtifactCatalog
from omnivoice.auth import StudioAuthConfig, StudioBearerAuthMiddleware
from omnivoice.mcp_server import (
    create_omnivoice_mcp_server,
    mcp_transport_security_from_env,
)
from omnivoice.runtime_workspace import RuntimeWorkspace
from omnivoice.server.schemas import (
    GenerateAudioRequest,
    GenerateProjectRequest,
    ImportProjectRequest,
    PreviewAudioRequest,
    RegenerateRequest,
)
from omnivoice.services.job_manager import JobEvent, StudioJobManager
from omnivoice.services.job_wait import wait_for_job
from omnivoice.services.project_import import (
    ProjectImportConflict,
    StudioProjectImportService,
)
from omnivoice.services.studio_commands import StudioCommandService
from omnivoice.services.studio_service import StudioService

_TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}


def _job_payload(job, *, include_events: bool = False) -> dict[str, Any]:
    payload = job.to_dict()
    if not include_events:
        payload.pop("events", None)
    return payload


def _sse_event(event: JobEvent) -> str:
    payload = {
        "seq": event.seq,
        "timestamp": event.timestamp,
        "message": event.message,
        "progress": event.progress,
        "data": event.data,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event.seq}\nevent: {event.event}\ndata: {encoded}\n\n"


def create_studio_app(
    model: Any,
    workspace: str | Path,
    *,
    runtime: Optional[RuntimeWorkspace] = None,
    mount_ui: bool = True,
    mount_mcp: bool = True,
    command_service: Optional[StudioCommandService] = None,
    auth_config: Optional[StudioAuthConfig] = None,
):
    from fastapi import FastAPI, Header, HTTPException, Query
    from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse

    auth = auth_config or StudioAuthConfig.from_env()
    auth.validate(mount_ui=mount_ui, mount_mcp=mount_mcp)

    service = StudioService(model, workspace, runtime=runtime)
    jobs = StudioJobManager(workspace)
    commands = command_service or StudioCommandService(model, workspace)
    project_imports = StudioProjectImportService(workspace)
    artifacts = ArtifactCatalog(workspace)

    # Custom command services used by tests/integrators may implement only a
    # subset. The production StudioCommandService implements all five writers.
    for kind, method_name in (
        ("generate_audio", "generate_audio_job"),
        ("generate_project", "generate_project_job"),
        ("preview_audio", "preview_audio_job"),
        ("regenerate_section", "regenerate_section_job"),
        ("regenerate_chunk", "regenerate_chunk_job"),
    ):
        handler = getattr(commands, method_name, None)
        if handler is not None:
            jobs.register(kind, handler)

    mcp_server = None
    mcp_http_app = None
    if mount_mcp:
        mcp_server = create_omnivoice_mcp_server(service, jobs)
        mcp_http_app = mcp_server.streamable_http_app(
            streamable_http_path="/",
            json_response=True,
            stateless_http=True,
            transport_security=mcp_transport_security_from_env(),
        )

    @asynccontextmanager
    async def lifespan(_app):
        jobs.start()
        try:
            if mcp_server is None:
                yield
            else:
                async with mcp_server.session_manager.run():
                    yield
        finally:
            jobs.shutdown()

    app = FastAPI(
        title="OmniVoice Studio API",
        version="0.7.0",
        description=(
            "Unified OmniVoice Studio host with authenticated Gradio UI, REST/OpenAPI, "
            "durable single-GPU jobs, live SSE progress, generated audio artifacts, "
            "and Model Context Protocol tools."
        ),
        lifespan=lifespan,
    )
    if auth.bearer_enabled:
        app.add_middleware(StudioBearerAuthMiddleware, config=auth)

    app.state.studio_service = service
    app.state.command_service = commands
    app.state.project_import_service = project_imports
    app.state.job_manager = jobs
    app.state.artifact_catalog = artifacts
    app.state.omnivoice_model = model
    app.state.mcp_server = mcp_server
    app.state.auth_config = auth

    def submit_job(
        kind: str,
        payload: dict[str, Any],
        idempotency_key: Optional[str],
    ):
        try:
            job = jobs.submit(
                kind,
                payload,
                idempotency_key=(str(idempotency_key).strip() or None)
                if idempotency_key is not None
                else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        location = f"/api/v1/jobs/{job.id}"
        return JSONResponse(
            status_code=202,
            headers={"Location": location},
            content={
                "job_id": job.id,
                "kind": job.kind,
                "status": job.status,
                "location": location,
                "wait": f"{location}/wait",
                "events": f"{location}/stream",
                "idempotency_key": job.idempotency_key,
            },
        )

    def project_payload(project_id: str) -> dict[str, Any]:
        try:
            return service.get_project(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Project not found") from exc

    @app.get("/health", tags=["system"])
    def health():
        payload = service.health()
        payload["job_manager"] = "ready"
        payload["mcp"] = "enabled" if mcp_server is not None else "disabled"
        payload["auth"] = {
            "public": bool(auth.public_url),
            "machine": "bearer" if auth.bearer_enabled else "disabled",
            "ui": (
                "basic"
                if auth.ui_basic_auth
                else "external"
                if auth.trust_external_ui_auth
                else "disabled"
            ),
        }
        return payload

    @app.get("/api/v1/capabilities", tags=["system"])
    def capabilities():
        payload = service.capabilities()
        payload["features"]["job_manager"] = True
        payload["features"]["async_generation"] = True
        payload["features"]["sse_job_stream"] = True
        payload["features"]["audio_artifacts"] = True
        payload["features"]["artifact_content_download"] = True
        payload["features"]["standalone_audio_generation"] = True
        payload["features"]["preview_audio"] = True
        payload["features"]["targeted_regeneration"] = True
        payload["features"]["project_import"] = True
        payload["features"]["mcp"] = mcp_server is not None
        payload["features"]["bearer_auth"] = auth.bearer_enabled
        payload["endpoints"]["jobs"] = "/api/v1/jobs"
        payload["endpoints"]["job_stream"] = "/api/v1/jobs/{job_id}/stream"
        payload["endpoints"]["job_wait"] = "/api/v1/jobs/{job_id}/wait"
        payload["endpoints"]["generate_audio"] = "/api/v1/audio/generate"
        payload["endpoints"]["preview_audio"] = "/api/v1/audio/preview"
        payload["endpoints"]["artifacts"] = "/api/v1/artifacts"
        payload["endpoints"]["artifact_content"] = "/api/v1/artifacts/{artifact_id}/content"
        payload["endpoints"]["project_import"] = "/api/v1/projects/import"
        payload["endpoints"]["generate_project"] = "/api/v1/projects/{project_id}/generate"
        payload["endpoints"]["regenerate_section"] = (
            "/api/v1/projects/{project_id}/sections/{section_id}/regenerate"
        )
        payload["endpoints"]["regenerate_chunk"] = (
            "/api/v1/projects/{project_id}/sections/{section_id}/chunks/{chunk_id}/regenerate"
        )
        payload["endpoints"]["mcp"] = "/mcp" if mcp_server is not None else None
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

    @app.post("/api/v1/projects/import", tags=["projects"])
    def import_project(request: ImportProjectRequest):
        try:
            payload = project_imports.import_project(**request.model_dump())
        except ProjectImportConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        project_id = payload["project_id"]
        payload["links"] = {
            "self": f"/api/v1/projects/{project_id}",
            "generate": f"/api/v1/projects/{project_id}/generate",
        }
        return JSONResponse(
            status_code=201 if payload["created"] else 200,
            content=payload,
        )

    @app.get("/api/v1/projects/{project_id}", tags=["projects"])
    def get_project(project_id: str):
        return project_payload(project_id)

    @app.post("/api/v1/audio/generate", status_code=202, tags=["audio", "jobs"])
    def generate_audio(
        request: GenerateAudioRequest,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ):
        return submit_job(
            "generate_audio",
            request.model_dump(exclude_none=True),
            idempotency_key,
        )

    @app.post("/api/v1/audio/preview", status_code=202, tags=["audio", "jobs"])
    def preview_audio(
        request: PreviewAudioRequest,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ):
        payload = request.model_dump(exclude_none=True)
        if request.project_id:
            project = project_payload(request.project_id)
            payload["project_path"] = project["path"]
        return submit_job("preview_audio", payload, idempotency_key)

    @app.post(
        "/api/v1/projects/{project_id}/generate",
        status_code=202,
        tags=["projects", "jobs"],
    )
    def generate_project(
        project_id: str,
        request: GenerateProjectRequest,
        idempotency_key: Optional[str] = Header(
            default=None,
            alias="Idempotency-Key",
            description="Stable client key used to deduplicate retried submissions.",
        ),
    ):
        project = project_payload(project_id)
        payload = request.model_dump(exclude_none=True)
        payload["project_id"] = project_id
        payload["project_path"] = project["path"]
        return submit_job("generate_project", payload, idempotency_key)

    @app.post(
        "/api/v1/projects/{project_id}/sections/{section_id}/regenerate",
        status_code=202,
        tags=["projects", "jobs"],
    )
    def regenerate_section(
        project_id: str,
        section_id: str,
        request: RegenerateRequest,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ):
        project = project_payload(project_id)
        payload = request.model_dump(exclude_none=True)
        payload.update(
            {
                "project_id": project_id,
                "project_path": project["path"],
                "section_id": section_id,
            }
        )
        return submit_job("regenerate_section", payload, idempotency_key)

    @app.post(
        "/api/v1/projects/{project_id}/sections/{section_id}/chunks/{chunk_id}/regenerate",
        status_code=202,
        tags=["projects", "jobs"],
    )
    def regenerate_chunk(
        project_id: str,
        section_id: str,
        chunk_id: str,
        request: RegenerateRequest,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    ):
        project = project_payload(project_id)
        payload = request.model_dump(exclude_none=True)
        payload.update(
            {
                "project_id": project_id,
                "project_path": project["path"],
                "section_id": section_id,
                "chunk_id": chunk_id,
            }
        )
        return submit_job("regenerate_chunk", payload, idempotency_key)

    @app.get("/api/v1/artifacts", tags=["audio"])
    def list_artifacts(
        project_id: Optional[str] = Query(default=None),
        kind: Optional[list[str]] = Query(default=None),
    ):
        try:
            return {"items": artifacts.list(project_id=project_id, kinds=kind)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Project not found") from exc

    @app.get("/api/v1/artifacts/{artifact_id}/content", tags=["audio"])
    def artifact_content(artifact_id: str):
        try:
            item = artifacts.get(artifact_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Artifact not found") from exc
        return FileResponse(
            path=item["path"],
            media_type="audio/wav",
            filename=item["filename"],
        )

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

    @app.get("/api/v1/jobs/{job_id}/wait", tags=["jobs"])
    def wait_job(
        job_id: str,
        timeout_seconds: float = Query(default=60.0, ge=0.0, le=600.0),
        include_events: bool = Query(default=False),
    ):
        try:
            job, timed_out = wait_for_job(
                jobs,
                job_id,
                timeout_seconds=timeout_seconds,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        payload = _job_payload(job, include_events=include_events)
        payload["timed_out"] = timed_out
        payload["terminal"] = job.status in _TERMINAL_JOB_STATUSES
        return payload

    @app.get("/api/v1/jobs/{job_id}/events", tags=["jobs"])
    def get_job_events(job_id: str, after: int = 0):
        try:
            return {"items": [asdict(event) for event in jobs.events_after(job_id, after)]}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.get("/api/v1/jobs/{job_id}/stream", tags=["jobs"])
    def stream_job_events(
        job_id: str,
        after: int = Query(default=0, ge=0),
        last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    ):
        try:
            jobs.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

        cursor = int(after)
        if last_event_id is not None and str(last_event_id).strip():
            try:
                cursor = max(cursor, int(str(last_event_id).strip()))
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="Last-Event-ID must be an integer event sequence.",
                ) from exc
        if cursor < 0:
            raise HTTPException(status_code=400, detail="Event cursor cannot be negative")

        def event_stream():
            current = cursor
            while True:
                events, job = jobs.wait_for_events(job_id, current, timeout=15.0)
                if events:
                    for event in events:
                        current = event.seq
                        yield _sse_event(event)
                    if job.status in _TERMINAL_JOB_STATUSES:
                        return
                    continue
                if job.status in _TERMINAL_JOB_STATUSES:
                    return
                yield ": keep-alive\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/v1/jobs/{job_id}/cancel", tags=["jobs"])
    def cancel_job(job_id: str):
        try:
            return _job_payload(jobs.request_cancel(job_id), include_events=True)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    if mcp_http_app is not None:
        app.mount("/mcp", mcp_http_app, name="omnivoice-mcp")

    if mount_ui:
        import gradio as gr

        from omnivoice.cli.project_studio_voice_doctor import build_demo

        demo = build_demo(model, workspace)
        app = gr.mount_gradio_app(
            app,
            demo,
            path="/ui",
            auth=auth.ui_basic_auth,
            auth_message="OmniVoice Studio private UI" if auth.ui_basic_auth else None,
        )
        app.state.studio_service = service
        app.state.command_service = commands
        app.state.project_import_service = project_imports
        app.state.job_manager = jobs
        app.state.artifact_catalog = artifacts
        app.state.omnivoice_model = model
        app.state.mcp_server = mcp_server
        app.state.auth_config = auth

        @app.get("/", include_in_schema=False)
        def root():
            return RedirectResponse(url="/ui")
    else:
        @app.get("/", include_in_schema=False)
        def root():
            return RedirectResponse(url="/docs")

    return app
