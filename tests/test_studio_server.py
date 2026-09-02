import json

from fastapi.testclient import TestClient

from omnivoice.server.app import create_studio_app
from omnivoice.services.job_manager import wait_for_terminal


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


class FakeCommandService:
    def __init__(self):
        self.calls = []

    def generate_project_job(self, ctx):
        self.calls.append(dict(ctx.payload))
        ctx.emit("generated", progress=1.0, event="project.finished")
        return {
            "project_id": ctx.payload["project_id"],
            "project_status": "DONE",
        }


def test_api_health_capabilities_projects_and_queue(tmp_path):
    workspace = tmp_path / "studio"
    write_pending_project(workspace)
    app = create_studio_app(None, workspace, mount_ui=False)
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["service"] == "omnivoice-studio"

    capabilities = client.get("/api/v1/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["endpoints"]["api"] == "/api/v1"
    assert capabilities.json()["features"]["job_manager"] is True
    assert capabilities.json()["features"]["async_generation"] is True
    assert capabilities.json()["features"]["sse_job_stream"] is True
    assert capabilities.json()["endpoints"]["job_stream"] == (
        "/api/v1/jobs/{job_id}/stream"
    )

    projects = client.get("/api/v1/projects", params={"status": "PENDING"})
    assert projects.status_code == 200
    assert projects.json()["items"][0]["id"] == "video-a"

    project = client.get("/api/v1/projects/video-a")
    assert project.status_code == 200
    assert project.json()["progress"] == "1/2"

    queue = client.get("/api/v1/queue")
    assert queue.status_code == 200
    assert queue.json()["items"] == []


def test_generate_api_returns_202_and_deduplicates_agent_retry(tmp_path):
    workspace = tmp_path / "studio"
    write_pending_project(workspace)
    commands = FakeCommandService()
    app = create_studio_app(
        None,
        workspace,
        mount_ui=False,
        command_service=commands,
    )

    with TestClient(app) as client:
        headers = {"Idempotency-Key": "turn-42-video-a"}
        body = {
            "voice_name": "Narrator",
            "voice_variant": "WARM",
            "quality_preset": "BALANCED",
            "sections": ["S01"],
        }
        first = client.post(
            "/api/v1/projects/video-a/generate",
            json=body,
            headers=headers,
        )
        assert first.status_code == 202
        first_job = first.json()["job_id"]
        assert first.headers["location"] == f"/api/v1/jobs/{first_job}"

        finished = wait_for_terminal(app.state.job_manager, first_job)
        assert finished.status == "completed"
        assert finished.result["project_status"] == "DONE"

        second = client.post(
            "/api/v1/projects/video-a/generate",
            json={**body, "sections": ["S02"]},
            headers=headers,
        )
        assert second.status_code == 202
        assert second.json()["job_id"] == first_job
        assert len(commands.calls) == 1
        assert commands.calls[0]["project_id"] == "video-a"
        assert commands.calls[0]["sections"] == ["S01"]
        assert commands.calls[0]["project_path"].endswith("projects/video-a")


def test_generate_api_rejects_missing_project_before_job_submission(tmp_path):
    commands = FakeCommandService()
    app = create_studio_app(
        None,
        tmp_path / "studio",
        mount_ui=False,
        command_service=commands,
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/projects/missing/generate",
            json={"voice_name": "Narrator"},
        )
        assert response.status_code == 404
        assert app.state.job_manager.list_jobs() == []
        assert commands.calls == []


def test_job_api_exposes_persisted_job_and_events(tmp_path):
    app = create_studio_app(None, tmp_path / "studio", mount_ui=False)
    manager = app.state.job_manager

    def echo(ctx):
        ctx.emit("half", progress=0.5, data={"phase": "test"})
        return {"echo": ctx.payload["value"]}

    manager.register("echo", echo)
    with TestClient(app) as client:
        job = manager.submit("echo", {"value": "hello"})
        finished = wait_for_terminal(manager, job.id)
        assert finished.status == "completed"

        listed = client.get("/api/v1/jobs")
        assert listed.status_code == 200
        assert listed.json()["items"][0]["id"] == job.id
        assert "events" not in listed.json()["items"][0]

        detail = client.get(f"/api/v1/jobs/{job.id}")
        assert detail.status_code == 200
        assert detail.json()["result"] == {"echo": "hello"}
        assert detail.json()["events"][-1]["event"] == "completed"

        events = client.get(f"/api/v1/jobs/{job.id}/events", params={"after": 1})
        assert events.status_code == 200
        assert all(item["seq"] > 1 for item in events.json()["items"])


def test_job_sse_stream_replays_history_and_closes_at_terminal_event(tmp_path):
    app = create_studio_app(None, tmp_path / "studio", mount_ui=False)
    manager = app.state.job_manager

    def echo(ctx):
        ctx.emit("half", progress=0.5, event="work.half", data={"phase": "test"})
        return {"ok": True}

    manager.register("echo", echo)
    with TestClient(app) as client:
        job = manager.submit("echo", {})
        finished = wait_for_terminal(manager, job.id)

        response = client.get(f"/api/v1/jobs/{job.id}/stream")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache, no-transform"
        assert "event: queued\n" in response.text
        assert "event: work.half\n" in response.text
        assert "event: completed\n" in response.text
        assert f"id: {finished.events[-1].seq}\n" in response.text
        assert '"progress":0.5' in response.text


def test_job_sse_stream_resumes_from_last_event_id(tmp_path):
    app = create_studio_app(None, tmp_path / "studio", mount_ui=False)
    manager = app.state.job_manager

    def echo(ctx):
        ctx.emit("one", progress=0.25, event="work.one")
        ctx.emit("two", progress=0.75, event="work.two")
        return {"ok": True}

    manager.register("echo", echo)
    with TestClient(app) as client:
        job = manager.submit("echo", {})
        finished = wait_for_terminal(manager, job.id)
        cutoff = finished.events[-2].seq

        response = client.get(
            f"/api/v1/jobs/{job.id}/stream",
            headers={"Last-Event-ID": str(cutoff)},
        )
        assert response.status_code == 200
        assert f"id: {cutoff}\n" not in response.text
        assert f"id: {finished.events[-1].seq}\n" in response.text
        assert "event: completed\n" in response.text
        assert "event: work.two\n" not in response.text


def test_job_sse_stream_validates_job_and_cursor_before_streaming(tmp_path):
    app = create_studio_app(None, tmp_path / "studio", mount_ui=False)
    manager = app.state.job_manager
    manager.register("noop", lambda ctx: {})

    with TestClient(app) as client:
        missing = client.get("/api/v1/jobs/job_missing/stream")
        assert missing.status_code == 404

        job = manager.submit("noop", {})
        finished = wait_for_terminal(manager, job.id)
        assert finished.status == "completed"

        invalid = client.get(
            f"/api/v1/jobs/{job.id}/stream",
            headers={"Last-Event-ID": "not-a-number"},
        )
        assert invalid.status_code == 400

        negative = client.get(
            f"/api/v1/jobs/{job.id}/stream",
            params={"after": -1},
        )
        assert negative.status_code == 422


def test_api_returns_useful_errors(tmp_path):
    app = create_studio_app(None, tmp_path / "studio", mount_ui=False)
    client = TestClient(app)

    invalid_status = client.get("/api/v1/projects", params={"status": "NOPE"})
    assert invalid_status.status_code == 400

    missing = client.get("/api/v1/projects/missing")
    assert missing.status_code == 404

    traversal = client.get("/api/v1/projects/%2E%2E%2Fsecret")
    assert traversal.status_code in {400, 404}

    missing_job = client.get("/api/v1/jobs/job_missing")
    assert missing_job.status_code == 404
    cancel_missing = client.post("/api/v1/jobs/job_missing/cancel")
    assert cancel_missing.status_code == 404


def test_api_only_root_redirects_to_openapi(tmp_path):
    app = create_studio_app(None, tmp_path / "studio", mount_ui=False)
    client = TestClient(app, follow_redirects=False)
    response = client.get("/")
    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/docs"
