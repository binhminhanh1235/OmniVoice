import json

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from omnivoice.server.app import create_studio_app
from omnivoice.services.job_manager import wait_for_terminal


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
    return root


class FakeCommands:
    def __init__(self):
        self.calls = []

    def _run(self, kind, ctx):
        self.calls.append((kind, dict(ctx.payload)))
        return {"kind": kind, "payload": dict(ctx.payload)}

    def generate_audio_job(self, ctx):
        return self._run("generate_audio", ctx)

    def generate_project_job(self, ctx):
        return self._run("generate_project", ctx)

    def preview_audio_job(self, ctx):
        return self._run("preview_audio", ctx)

    def regenerate_section_job(self, ctx):
        return self._run("regenerate_section", ctx)

    def regenerate_chunk_job(self, ctx):
        return self._run("regenerate_chunk", ctx)


def test_priority_rest_routes_submit_the_same_durable_job_kinds(tmp_path):
    workspace = tmp_path / "studio"
    _project(workspace)
    commands = FakeCommands()
    app = create_studio_app(
        None,
        workspace,
        mount_ui=False,
        command_service=commands,
    )

    with TestClient(app) as client:
        cases = [
            ("/api/v1/audio/generate", {"text": "hello"}, "generate_audio"),
            (
                "/api/v1/projects/video-a/generate",
                {"voice_name": "Narrator", "sections": ["S01"]},
                "generate_project",
            ),
            ("/api/v1/audio/preview", {"text": "preview"}, "preview_audio"),
            (
                "/api/v1/projects/video-a/sections/S01/regenerate",
                {"voice_name": "Narrator"},
                "regenerate_section",
            ),
            (
                "/api/v1/projects/video-a/sections/S01/chunks/B01-C01/regenerate",
                {"voice_name": "Narrator"},
                "regenerate_chunk",
            ),
        ]

        for index, (path, body, expected_kind) in enumerate(cases):
            response = client.post(
                path,
                json=body,
                headers={"Idempotency-Key": f"case-{index}"},
            )
            assert response.status_code == 202
            assert response.json()["kind"] == expected_kind
            job_id = response.json()["job_id"]
            finished = wait_for_terminal(app.state.job_manager, job_id)
            assert finished.status == "completed"
            assert finished.kind == expected_kind

            waited = client.get(
                f"/api/v1/jobs/{job_id}/wait",
                params={"timeout_seconds": 1},
            )
            assert waited.status_code == 200
            assert waited.json()["terminal"] is True
            assert waited.json()["timed_out"] is False


def test_artifact_route_reports_audio_metadata(tmp_path):
    workspace = tmp_path / "studio"
    _project(workspace)
    path = workspace / "artifacts" / "audio" / "job_demo.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.zeros(2400, dtype=np.float32), 24000)

    app = create_studio_app(None, workspace, mount_ui=False)
    with TestClient(app) as client:
        response = client.get("/api/v1/artifacts", params={"kind": "generated_audio"})
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["kind"] == "generated_audio"
        assert item["duration_seconds"] == 0.1
        assert item["sample_rate"] == 24000


def test_capabilities_publish_priority_tool_endpoints(tmp_path):
    app = create_studio_app(None, tmp_path / "studio", mount_ui=False)
    with TestClient(app) as client:
        payload = client.get("/api/v1/capabilities").json()

    assert payload["features"]["audio_artifacts"] is True
    assert payload["features"]["standalone_audio_generation"] is True
    assert payload["features"]["targeted_regeneration"] is True
    assert payload["endpoints"]["generate_audio"] == "/api/v1/audio/generate"
    assert payload["endpoints"]["job_wait"].endswith("/wait")
    assert payload["endpoints"]["artifacts"] == "/api/v1/artifacts"
