#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Model Context Protocol adapter for OmniVoice Studio.

The MCP layer is deliberately thin. It delegates reads to ``StudioService``
and durable mutations to ``StudioJobManager`` so REST, CLI, Gradio, and MCP
share the same project/job state rather than implementing parallel workflows.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from omnivoice.artifacts import ArtifactCatalog
from omnivoice.services.job_manager import StudioJobManager
from omnivoice.services.job_wait import wait_for_job
from omnivoice.services.studio_service import StudioService


def _csv_env(name: str) -> list[str]:
    value = str(os.environ.get(name, "") or "")
    return [item.strip() for item in value.split(",") if item.strip()]


def mcp_transport_security_from_env():
    """Return official MCP transport security settings for this deployment."""

    from mcp.server.transport_security import TransportSecuritySettings

    trust_proxy = str(os.environ.get("OMNIVOICE_MCP_TRUST_PROXY", "")).lower()
    if trust_proxy in {"1", "true", "yes", "on"}:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)

    allowed_hosts = _csv_env("OMNIVOICE_MCP_ALLOWED_HOSTS")
    allowed_origins = _csv_env("OMNIVOICE_MCP_ALLOWED_ORIGINS")
    if not allowed_hosts and not allowed_origins:
        return None
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


class OmniVoiceMCPTools:
    """Protocol-neutral implementations exposed as MCP tools/resources."""

    def __init__(self, service: StudioService, jobs: StudioJobManager) -> None:
        self.service = service
        self.jobs = jobs
        self.artifacts = ArtifactCatalog(service.workspace)

    def studio_status(self) -> dict[str, Any]:
        capabilities = self.service.capabilities()
        capabilities["features"]["mcp"] = True
        capabilities["features"]["job_manager"] = True
        capabilities["features"]["async_generation"] = True
        capabilities["features"]["sse_job_stream"] = True
        capabilities["features"]["audio_artifacts"] = True
        capabilities["endpoints"]["mcp"] = "/mcp"
        capabilities["endpoints"]["jobs"] = "/api/v1/jobs"
        capabilities["endpoints"]["job_stream"] = "/api/v1/jobs/{job_id}/stream"
        capabilities["endpoints"]["artifacts"] = "/api/v1/artifacts"
        return {
            "health": self.service.health(),
            "hardware": self.service.hardware(),
            "capabilities": capabilities,
        }

    def list_projects(
        self,
        statuses: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        return {"items": self.service.list_projects(statuses)}

    def inspect_project(self, project_id: str) -> dict[str, Any]:
        return self.service.get_project(project_id)

    def queue_status(self) -> dict[str, Any]:
        return self.service.queue_summary()

    def _submit(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        key = str(idempotency_key).strip() if idempotency_key is not None else None
        key = key or None
        job = self.jobs.submit(kind, payload, idempotency_key=key)
        return {
            "job_id": job.id,
            "kind": job.kind,
            "status": job.status,
            "idempotency_key": job.idempotency_key,
            "job_url": f"/api/v1/jobs/{job.id}",
            "wait_url": f"/api/v1/jobs/{job.id}/wait",
            "events_url": f"/api/v1/jobs/{job.id}/stream",
        }

    def generate_audio(
        self,
        text: str,
        voice_name: Optional[str] = None,
        voice_variant: Optional[str] = None,
        language: Optional[str] = "en",
        instruct: Optional[str] = None,
        speed: Optional[float] = None,
        quality_preset: Optional[str] = None,
        style: Optional[str] = "DEFAULT",
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Submit one standalone audio generation and return immediately."""

        payload: dict[str, Any] = {"text": text}
        optional = {
            "voice_name": voice_name,
            "voice_variant": voice_variant,
            "language": language,
            "instruct": instruct,
            "speed": speed,
            "quality_preset": quality_preset,
            "style": style,
        }
        payload.update({key: value for key, value in optional.items() if value is not None})
        return self._submit(
            "generate_audio",
            payload,
            idempotency_key=idempotency_key,
        )

    def generate_project(
        self,
        project_id: str,
        voice_name: Optional[str] = None,
        voice_variant: Optional[str] = None,
        language: Optional[str] = None,
        sections: Optional[list[str]] = None,
        resume: bool = True,
        strict: bool = False,
        quality_preset: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        payload: dict[str, Any] = {
            "project_id": project_id,
            "project_path": project["path"],
            "resume": bool(resume),
            "strict": bool(strict),
        }
        optional = {
            "voice_name": voice_name,
            "voice_variant": voice_variant,
            "language": language,
            "sections": sections,
            "quality_preset": quality_preset,
        }
        payload.update({key: value for key, value in optional.items() if value is not None})
        return self._submit(
            "generate_project",
            payload,
            idempotency_key=idempotency_key,
        )

    def get_job(self, job_id: str, include_events: bool = False) -> dict[str, Any]:
        payload = self.jobs.get(job_id).to_dict()
        if not include_events:
            payload.pop("events", None)
        return payload

    def wait_job(
        self,
        job_id: str,
        timeout_seconds: float = 60.0,
        include_events: bool = False,
    ) -> dict[str, Any]:
        job, timed_out = wait_for_job(
            self.jobs,
            job_id,
            timeout_seconds=timeout_seconds,
        )
        payload = job.to_dict()
        if not include_events:
            payload.pop("events", None)
        payload["timed_out"] = timed_out
        payload["terminal"] = job.status in {"completed", "failed", "cancelled"}
        return payload

    def list_artifacts(
        self,
        project_id: Optional[str] = None,
        kinds: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        return {"items": self.artifacts.list(project_id=project_id, kinds=kinds)}

    def preview_audio(
        self,
        text: Optional[str] = None,
        project_id: Optional[str] = None,
        voice_name: Optional[str] = None,
        voice_variant: Optional[str] = None,
        language: Optional[str] = None,
        labels: Optional[list[str]] = None,
        instruct: Optional[str] = None,
        speed: Optional[float] = None,
        quality_preset: Optional[str] = None,
        strict: bool = False,
        style: Optional[str] = "DEFAULT",
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        if not str(text or "").strip() and not str(project_id or "").strip():
            raise ValueError("preview_audio requires text or project_id")
        payload: dict[str, Any] = {"strict": bool(strict)}
        if str(text or "").strip():
            payload["text"] = str(text)
        if str(project_id or "").strip():
            project = self.service.get_project(str(project_id))
            payload["project_id"] = str(project_id)
            payload["project_path"] = project["path"]
        optional = {
            "voice_name": voice_name,
            "voice_variant": voice_variant,
            "language": language,
            "labels": labels,
            "instruct": instruct,
            "speed": speed,
            "quality_preset": quality_preset,
            "style": style,
        }
        payload.update({key: value for key, value in optional.items() if value is not None})
        return self._submit(
            "preview_audio",
            payload,
            idempotency_key=idempotency_key,
        )

    def regenerate_section(
        self,
        project_id: str,
        section_id: str,
        voice_name: Optional[str] = None,
        voice_variant: Optional[str] = None,
        language: Optional[str] = None,
        strict: bool = False,
        quality_preset: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        payload: dict[str, Any] = {
            "project_id": project_id,
            "project_path": project["path"],
            "section_id": section_id,
            "strict": bool(strict),
        }
        optional = {
            "voice_name": voice_name,
            "voice_variant": voice_variant,
            "language": language,
            "quality_preset": quality_preset,
        }
        payload.update({key: value for key, value in optional.items() if value is not None})
        return self._submit(
            "regenerate_section",
            payload,
            idempotency_key=idempotency_key,
        )

    def regenerate_chunk(
        self,
        project_id: str,
        section_id: str,
        chunk_id: str,
        voice_name: Optional[str] = None,
        voice_variant: Optional[str] = None,
        language: Optional[str] = None,
        strict: bool = False,
        quality_preset: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        payload: dict[str, Any] = {
            "project_id": project_id,
            "project_path": project["path"],
            "section_id": section_id,
            "chunk_id": chunk_id,
            "strict": bool(strict),
        }
        optional = {
            "voice_name": voice_name,
            "voice_variant": voice_variant,
            "language": language,
            "quality_preset": quality_preset,
        }
        payload.update({key: value for key, value in optional.items() if value is not None})
        return self._submit(
            "regenerate_chunk",
            payload,
            idempotency_key=idempotency_key,
        )

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        payload = self.jobs.request_cancel(job_id).to_dict()
        payload.pop("events", None)
        return payload

    def project_resource(self, project_id: str) -> str:
        return json.dumps(
            self.inspect_project(project_id),
            ensure_ascii=False,
            indent=2,
        )

    def queue_resource(self) -> str:
        return json.dumps(self.queue_status(), ensure_ascii=False, indent=2)


def create_omnivoice_mcp_server(
    service: StudioService,
    jobs: StudioJobManager,
):
    """Build the MCP server without starting a second network listener."""

    from mcp.server import MCPServer

    tools = OmniVoiceMCPTools(service, jobs)
    mcp = MCPServer(
        "OmniVoice Studio",
        instructions=(
            "Control OmniVoice Studio through durable GPU jobs. Generation tools return "
            "a job_id immediately. Prefer wait_job over repeated get_job polling, then "
            "use list_artifacts to discover generated WAV files. Supply a stable "
            "idempotency_key when retrying after a network failure. Cancellation is "
            "cooperative and occurs only at safe generation checkpoints."
        ),
    )

    @mcp.tool()
    def studio_status() -> dict[str, Any]:
        """Get OmniVoice runtime, GPU, workspace, and capability information."""
        return tools.studio_status()

    @mcp.tool()
    def list_projects(statuses: Optional[list[str]] = None) -> dict[str, Any]:
        """List projects. Status examples: PENDING, GENERATING, NEEDS_REVIEW, FAILED, DONE."""
        return tools.list_projects(statuses)

    @mcp.tool()
    def inspect_project(project_id: str) -> dict[str, Any]:
        """Inspect one project's current render status and section progress."""
        return tools.inspect_project(project_id)

    @mcp.tool()
    def queue_status() -> dict[str, Any]:
        """Read the persistent project queue without changing it."""
        return tools.queue_status()

    @mcp.tool()
    def generate_audio(
        text: str,
        voice_name: Optional[str] = None,
        voice_variant: Optional[str] = None,
        language: Optional[str] = "en",
        instruct: Optional[str] = None,
        speed: Optional[float] = None,
        quality_preset: Optional[str] = None,
        style: Optional[str] = "DEFAULT",
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate one standalone WAV asynchronously without creating a project."""
        return tools.generate_audio(
            text,
            voice_name=voice_name,
            voice_variant=voice_variant,
            language=language,
            instruct=instruct,
            speed=speed,
            quality_preset=quality_preset,
            style=style,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def generate_project(
        project_id: str,
        voice_name: Optional[str] = None,
        voice_variant: Optional[str] = None,
        language: Optional[str] = None,
        sections: Optional[list[str]] = None,
        resume: bool = True,
        strict: bool = False,
        quality_preset: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Submit resumable project generation and return a durable job_id."""
        return tools.generate_project(
            project_id,
            voice_name=voice_name,
            voice_variant=voice_variant,
            language=language,
            sections=sections,
            resume=resume,
            strict=strict,
            quality_preset=quality_preset,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def get_job(job_id: str, include_events: bool = False) -> dict[str, Any]:
        """Read one durable generation job without blocking."""
        return tools.get_job(job_id, include_events=include_events)

    @mcp.tool()
    def wait_job(
        job_id: str,
        timeout_seconds: float = 60.0,
        include_events: bool = False,
    ) -> dict[str, Any]:
        """Wait efficiently for a job to terminate or until the timeout expires."""
        return tools.wait_job(
            job_id,
            timeout_seconds=timeout_seconds,
            include_events=include_events,
        )

    @mcp.tool()
    def list_artifacts(
        project_id: Optional[str] = None,
        kinds: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """List generated WAV artifacts with duration, size, and durable workspace path."""
        return tools.list_artifacts(project_id=project_id, kinds=kinds)

    @mcp.tool()
    def preview_audio(
        text: Optional[str] = None,
        project_id: Optional[str] = None,
        voice_name: Optional[str] = None,
        voice_variant: Optional[str] = None,
        language: Optional[str] = None,
        labels: Optional[list[str]] = None,
        instruct: Optional[str] = None,
        speed: Optional[float] = None,
        quality_preset: Optional[str] = None,
        strict: bool = False,
        style: Optional[str] = "DEFAULT",
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate non-destructive preview audio from text or representative project chunks."""
        return tools.preview_audio(
            text=text,
            project_id=project_id,
            voice_name=voice_name,
            voice_variant=voice_variant,
            language=language,
            labels=labels,
            instruct=instruct,
            speed=speed,
            quality_preset=quality_preset,
            strict=strict,
            style=style,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def regenerate_section(
        project_id: str,
        section_id: str,
        voice_name: Optional[str] = None,
        voice_variant: Optional[str] = None,
        language: Optional[str] = None,
        strict: bool = False,
        quality_preset: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Force-regenerate exactly one section with history snapshot protection."""
        return tools.regenerate_section(
            project_id,
            section_id,
            voice_name=voice_name,
            voice_variant=voice_variant,
            language=language,
            strict=strict,
            quality_preset=quality_preset,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def regenerate_chunk(
        project_id: str,
        section_id: str,
        chunk_id: str,
        voice_name: Optional[str] = None,
        voice_variant: Optional[str] = None,
        language: Optional[str] = None,
        strict: bool = False,
        quality_preset: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Regenerate one chunk and rebuild only its containing beat/section."""
        return tools.regenerate_chunk(
            project_id,
            section_id,
            chunk_id,
            voice_name=voice_name,
            voice_variant=voice_variant,
            language=language,
            strict=strict,
            quality_preset=quality_preset,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def cancel_job(job_id: str) -> dict[str, Any]:
        """Request safe cooperative cancellation of a queued/running job."""
        return tools.cancel_job(job_id)

    @mcp.resource("omnivoice://projects/{project_id}")
    def project_resource(project_id: str) -> str:
        """Project status as JSON."""
        return tools.project_resource(project_id)

    @mcp.resource("omnivoice://queue")
    def queue_resource() -> str:
        """Current project queue as JSON."""
        return tools.queue_resource()

    return mcp
