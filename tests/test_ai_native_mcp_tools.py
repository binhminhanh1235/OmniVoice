import asyncio
import json

from mcp import Client

from omnivoice.mcp_server import OmniVoiceMCPTools, create_omnivoice_mcp_server
from omnivoice.services.job_manager import StudioJobManager
from omnivoice.services.studio_service import StudioService


NINE_TOOLS = {
    "generate_audio",
    "generate_project",
    "get_job",
    "wait_job",
    "list_artifacts",
    "preview_audio",
    "regenerate_section",
    "regenerate_chunk",
    "cancel_job",
}


def _project(workspace):
    root = workspace / "projects" / "video-a"
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.json").write_text(
        json.dumps(
            {
                "title": "Video A",
                "sections": [{"id": "S01", "status": "pending", "audio_file": None}],
            }
        ),
        encoding="utf-8",
    )
    (root / "section-status.json").write_text(
        json.dumps({"sections": {"S01": {"status": "pending", "complete": False}}}),
        encoding="utf-8",
    )


def _stack(tmp_path):
    workspace = tmp_path / "studio"
    _project(workspace)
    service = StudioService(None, workspace)
    jobs = StudioJobManager(workspace)
    for kind in (
        "generate_audio",
        "generate_project",
        "preview_audio",
        "regenerate_section",
        "regenerate_chunk",
    ):
        jobs.register(kind, lambda ctx, kind=kind: {"kind": kind})
    return service, jobs


def test_nine_priority_tools_are_exposed_over_mcp(tmp_path):
    service, jobs = _stack(tmp_path)
    mcp = create_omnivoice_mcp_server(service, jobs)

    async def exercise():
        async with Client(mcp, raise_exceptions=True) as client:
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert NINE_TOOLS.issubset(names)

    asyncio.run(exercise())


def test_priority_tool_submissions_share_durable_job_lifecycle(tmp_path):
    service, jobs = _stack(tmp_path)
    tools = OmniVoiceMCPTools(service, jobs)

    generated = tools.generate_audio(
        "Hello from OmniVoice",
        voice_name="Narrator",
        idempotency_key="audio-1",
    )
    duplicate = tools.generate_audio(
        "This different text must not duplicate work",
        idempotency_key="audio-1",
    )
    assert generated["job_id"] == duplicate["job_id"]
    assert tools.get_job(generated["job_id"])["kind"] == "generate_audio"

    waited = tools.wait_job(generated["job_id"], timeout_seconds=0)
    assert waited["timed_out"] is True
    assert waited["terminal"] is False

    cancelled = tools.cancel_job(generated["job_id"])
    assert cancelled["status"] == "cancelled"
    waited = tools.wait_job(generated["job_id"], timeout_seconds=1)
    assert waited["terminal"] is True
    assert waited["timed_out"] is False

    preview = tools.preview_audio(text="Preview me")
    assert tools.get_job(preview["job_id"])["kind"] == "preview_audio"

    section = tools.regenerate_section("video-a", "S01")
    chunk = tools.regenerate_chunk("video-a", "S01", "B01-C01")
    assert tools.get_job(section["job_id"])["payload"]["section_id"] == "S01"
    assert tools.get_job(chunk["job_id"])["payload"]["chunk_id"] == "B01-C01"

    artifacts = tools.list_artifacts(project_id="video-a")
    assert artifacts == {"items": []}
