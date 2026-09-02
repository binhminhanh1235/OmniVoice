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

    projects = client.get("/api/v1/projects", params={"status": "PENDING"})
    assert projects.status_code == 200
    assert projects.json()["items"][0]["id"] == "video-a"

    project = client.get("/api/v1/projects/video-a")
    assert project.status_code == 200
    assert project.json()["progress"] == "1/2"

    queue = client.get("/api/v1/queue")
    assert queue.status_code == 200
    assert queue.json()["items"] == []


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
