import asyncio
import json

from mcp import Client

from omnivoice.mcp_server import (
    OmniVoiceMCPTools,
    create_omnivoice_mcp_server,
    mcp_transport_security_from_env,
)
from omnivoice.services.job_manager import StudioJobManager
from omnivoice.services.studio_service import StudioService


def write_pending_project(workspace):
    root = workspace / "projects" / "video-a"
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.json").write_text(
        json.dumps(
            {
                "title": "Video A",
                "sections": [
                    {"id": "S01", "status": "pending", "audio_file": None},
                    {
                        "id": "S02",
                        "status": "verified",
                        "audio_file": "sections/S02/S02.wav",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "section-status.json").write_text(
        json.dumps(
            {
                "sections": {
                    "S01": {"status": "pending", "complete": False},
                    "S02": {"status": "verified", "complete": True},
                }
            }
        ),
        encoding="utf-8",
    )
    return root


def build_mcp(tmp_path):
    workspace = tmp_path / "studio"
    write_pending_project(workspace)
    service = StudioService(None, workspace)
    jobs = StudioJobManager(workspace)
    jobs.register("generate_project", lambda ctx: {"ok": True})
    return create_omnivoice_mcp_server(service, jobs), jobs


def test_protocol_neutral_mcp_tools_submit_durable_job(tmp_path):
    workspace = tmp_path / "studio"
    write_pending_project(workspace)
    service = StudioService(None, workspace)
    jobs = StudioJobManager(workspace)
    jobs.register("generate_project", lambda ctx: {})
    tools = OmniVoiceMCPTools(service, jobs)

    listed = tools.list_projects(["PENDING"])
    assert [item["id"] for item in listed["items"]] == ["video-a"]

    submitted = tools.generate_project(
        "video-a",
        voice_name="Narrator",
        sections=["S01"],
        quality_preset="BALANCED",
        idempotency_key="agent-video-a",
    )
    duplicate = tools.generate_project(
        "video-a",
        voice_name="Different voice should not duplicate",
        idempotency_key="agent-video-a",
    )

    assert duplicate["job_id"] == submitted["job_id"]
    assert len(jobs.list_jobs()) == 1
    stored = jobs.get(submitted["job_id"])
    assert stored.payload["project_id"] == "video-a"
    assert stored.payload["sections"] == ["S01"]
    assert stored.payload["quality_preset"] == "BALANCED"
    assert submitted["events_url"].endswith("/stream")


def test_mcp_in_memory_client_lists_and_calls_task_oriented_tools(tmp_path):
    mcp, jobs = build_mcp(tmp_path)

    async def exercise():
        async with Client(mcp, raise_exceptions=True) as client:
            listed_tools = await client.list_tools()
            names = {tool.name for tool in listed_tools.tools}
            assert {
                "studio_status",
                "list_projects",
                "inspect_project",
                "queue_status",
                "generate_project",
                "get_job",
                "cancel_job",
            }.issubset(names)

            projects = await client.call_tool(
                "list_projects",
                {"statuses": ["PENDING"]},
            )
            assert projects.is_error is False
            assert projects.structured_content["items"][0]["id"] == "video-a"

            submitted = await client.call_tool(
                "generate_project",
                {
                    "project_id": "video-a",
                    "voice_name": "Narrator",
                    "sections": ["S01"],
                    "quality_preset": "BALANCED",
                    "idempotency_key": "mcp-video-a",
                },
            )
            assert submitted.is_error is False
            job_id = submitted.structured_content["job_id"]
            assert jobs.get(job_id).status == "queued"

            job = await client.call_tool("get_job", {"job_id": job_id})
            assert job.is_error is False
            assert job.structured_content["id"] == job_id
            assert "events" not in job.structured_content

            cancelled = await client.call_tool("cancel_job", {"job_id": job_id})
            assert cancelled.is_error is False
            assert cancelled.structured_content["status"] == "cancelled"

    asyncio.run(exercise())


def test_mcp_transport_security_defaults_closed_and_supports_explicit_proxy(monkeypatch):
    for name in (
        "OMNIVOICE_MCP_TRUST_PROXY",
        "OMNIVOICE_MCP_ALLOWED_HOSTS",
        "OMNIVOICE_MCP_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)

    assert mcp_transport_security_from_env() is None

    monkeypatch.setenv("OMNIVOICE_MCP_TRUST_PROXY", "1")
    trusted = mcp_transport_security_from_env()
    assert trusted.enable_dns_rebinding_protection is False

    monkeypatch.delenv("OMNIVOICE_MCP_TRUST_PROXY")
    monkeypatch.setenv(
        "OMNIVOICE_MCP_ALLOWED_HOSTS",
        "omnivoice.example.com,omnivoice.example.com:*",
    )
    monkeypatch.setenv(
        "OMNIVOICE_MCP_ALLOWED_ORIGINS",
        "https://omnivoice.example.com",
    )
    secured = mcp_transport_security_from_env()
    assert secured.enable_dns_rebinding_protection is True
    assert "omnivoice.example.com" in secured.allowed_hosts
    assert secured.allowed_origins == ["https://omnivoice.example.com"]
