#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Model Context Protocol adapter for OmniVoice Studio.

The MCP layer is deliberately thin. It delegates reads to ``StudioService``
and durable mutations to ``StudioJobManager`` so REST, Gradio, and MCP all
share the same project/job state rather than implementing parallel workflows.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from omnivoice.services.job_manager import StudioJobManager
from omnivoice.services.studio_service import StudioService


def _csv_env(name: str) -> list[str]:
    value = str(os.environ.get(name, "") or "")
    return [item.strip() for item in value.split(",") if item.strip()]


def mcp_transport_security_from_env():
    """Return official MCP transport security settings for this deployment.

    Defaults to ``None`` so the SDK's localhost-only DNS-rebinding protection
    remains active. Public deployments should set explicit allowlists. A
    trusted reverse proxy/tunnel may opt out explicitly with
    ``OMNIVOICE_MCP_TRUST_PROXY=1``; this should only be used when the proxy is
    the actual security boundary.
    """

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

    def studio_status(self) -> dict[str, Any]:
        """Return runtime, hardware, and API capability information."""

        return {
            "health": self.service.health(),
            "hardware": self.service.hardware(),
            "capabilities": self.service.capabilities(),
        }

    def list_projects(
        self,
        statuses: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """List Studio projects, optionally filtered by project status."""

        return {"items": self.service.list_projects(statuses)}

    def inspect_project(self, project_id: str) -> dict[str, Any]:
        """Return one project's current status and section progress summary."""

        return self.service.get_project(project_id)

    def queue_status(self) -> dict[str, Any]:
        """Return the current persistent Project Queue state."""

        return self.service.queue_summary()

    def get_job(self, job_id: str, include_events: bool = False) -> dict[str, Any]:
        """Return durable job state; event history is optional to keep replies small."""

        payload = self.jobs.get(job_id).to_dict()
        if not include_events:
            payload.pop("events", None)
        return payload

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Request cooperative cancellation at the next safe generation checkpoint."""

        job = self.jobs.request_cancel(job_id)
        payload = job.to_dict()
        payload.pop("events", None)
        return payload

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
        """Submit resumable project/section generation and return immediately."""

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
        for key, value in optional.items():
            if value is not None:
                payload[key] = value

        job = self.jobs.submit(
            "generate_project",
            payload,
            idempotency_key=(str(idempotency_key).strip() or None)
            if idempotency_key is not None
            else None,
        )
        return {
            "job_id": job.id,
            "status": job.status,
            "project_id": project_id,
            "idempotency_key": job.idempotency_key,
            "job_url": f"/api/v1/jobs/{job.id}",
            "events_url": f"/api/v1/jobs/{job.id}/stream",
            "message": (
                "Generation was submitted. Use get_job for durable state or the "
                "SSE events URL for live progress."
            ),
        }

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
            "Control OmniVoice Studio projects and durable GPU jobs. Prefer reading "
            "project/job state before mutations. generate_project is asynchronous and "
            "returns a job_id; do not repeatedly submit the same work. Supply a stable "
            "idempotency_key when retrying a command after a network failure. Cancellation "
            "is cooperative and only occurs at safe generation checkpoints."
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
        """Submit resumable TTS generation. Returns immediately with a durable job_id."""

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
        """Read one durable job. Set include_events only when event history is needed."""

        return tools.get_job(job_id, include_events=include_events)

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

    # Retain the protocol-neutral implementation for tests and advanced callers.
    mcp.omnivoice_tools = tools
    return mcp
