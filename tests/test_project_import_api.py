import json

import pytest
from fastapi.testclient import TestClient

from omnivoice.auth import GENERATE_SCOPE, READ_SCOPE, StudioAuthConfig
from omnivoice.server.app import create_studio_app
from omnivoice.services import project_import as project_import_module


SCRIPT = """# Demo

## S01 — 0:00–0:20

### Opening title

[WARM] Hello world.

## S02 — 0:20–0:40

[SOFT] Second section.
"""


class FakeCommandService:
    def __init__(self):
        self.calls = []

    def generate_project_job(self, ctx):
        self.calls.append(dict(ctx.payload))
        return {
            "project_id": ctx.payload["project_id"],
            "project_status": "PENDING",
        }


def create_client(tmp_path, *, commands=None, auth_config=None, raise_server_exceptions=True):
    app = create_studio_app(
        None,
        tmp_path / "studio",
        mount_ui=False,
        mount_mcp=False,
        command_service=commands,
        auth_config=auth_config,
    )
    return app, TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_import_happy_path_and_existing_project_apis(tmp_path):
    app, client = create_client(tmp_path)
    with client:
        response = client.post(
            "/api/v1/projects/import",
            json={"project_id": "demo-video", "script": SCRIPT},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["project_id"] == "demo-video"
        assert payload["title"] == "Demo"
        assert payload["created"] is True
        assert payload["status"] == "PENDING"
        assert [section["id"] for section in payload["sections"]] == ["S01", "S02"]
        assert payload["links"]["self"] == "/api/v1/projects/demo-video"
        assert payload["links"]["generate"] == "/api/v1/projects/demo-video/generate"

        root = tmp_path / "studio" / "projects" / "demo-video"
        assert (root / "project.json").exists()
        assert (root / "script.md").read_text(encoding="utf-8") == SCRIPT
        assert (root / "sections" / "S01").exists()
        assert (root / "sections" / "S02").exists()

        listed = client.get("/api/v1/projects")
        assert listed.status_code == 200
        assert any(item["id"] == "demo-video" for item in listed.json()["items"])

        detail = client.get("/api/v1/projects/demo-video")
        assert detail.status_code == 200
        assert detail.json()["id"] == "demo-video"
        assert app.state.job_manager.list_jobs() == []


def test_import_is_idempotent_and_preserves_existing_artifacts(tmp_path):
    _app, client = create_client(tmp_path)
    with client:
        first = client.post(
            "/api/v1/projects/import",
            json={"project_id": "demo-video", "script": SCRIPT},
        )
        assert first.status_code == 201
        root = tmp_path / "studio" / "projects" / "demo-video"
        artifact = root / "output" / "existing.wav"
        artifact.write_bytes(b"existing-audio")
        original_manifest = (root / "project.json").read_bytes()

        second = client.post(
            "/api/v1/projects/import",
            json={"project_id": " demo-video ", "script": SCRIPT},
        )
        assert second.status_code == 200
        assert second.json()["created"] is False
        assert artifact.read_bytes() == b"existing-audio"
        assert (root / "project.json").read_bytes() == original_manifest


def test_import_same_id_different_source_or_chunk_options_conflicts(tmp_path):
    _app, client = create_client(tmp_path)
    with client:
        first = client.post(
            "/api/v1/projects/import",
            json={"project_id": "demo-video", "script": SCRIPT},
        )
        assert first.status_code == 201
        root = tmp_path / "studio" / "projects" / "demo-video"
        artifact = root / "output" / "existing.wav"
        artifact.write_bytes(b"keep-me")
        original_script = (root / "script.md").read_text(encoding="utf-8")

        changed = client.post(
            "/api/v1/projects/import",
            json={"project_id": "demo-video", "script": SCRIPT + "\nChanged."},
        )
        assert changed.status_code == 409
        assert changed.json()["detail"] == "Project already exists with different source"

        changed_chunking = client.post(
            "/api/v1/projects/import",
            json={
                "project_id": "demo-video",
                "script": SCRIPT,
                "max_chunk_words": 18,
            },
        )
        assert changed_chunking.status_code == 409
        assert (root / "script.md").read_text(encoding="utf-8") == original_script
        assert artifact.read_bytes() == b"keep-me"


@pytest.mark.parametrize("project_id", ["../foo", "foo/bar", "foo\\bar", ".", "..", "   "])
def test_import_rejects_unsafe_project_ids(tmp_path, project_id):
    _app, client = create_client(tmp_path)
    with client:
        response = client.post(
            "/api/v1/projects/import",
            json={"project_id": project_id, "script": SCRIPT},
        )
        assert response.status_code == 400


def test_import_rejects_invalid_and_duplicate_sections_without_publishing_project(tmp_path):
    _app, client = create_client(tmp_path)
    with client:
        invalid = client.post(
            "/api/v1/projects/import",
            json={"project_id": "invalid", "script": "# No sections\nHello"},
        )
        assert invalid.status_code == 400
        assert not (tmp_path / "studio" / "projects" / "invalid").exists()

        duplicate_script = """# Duplicate

## S01 — 0:00–0:10
First.

## S01 — 0:10–0:20
Second.
"""
        duplicate = client.post(
            "/api/v1/projects/import",
            json={"project_id": "duplicate", "script": duplicate_script},
        )
        assert duplicate.status_code == 400
        assert not (tmp_path / "studio" / "projects" / "duplicate").exists()


def test_import_uses_canonical_narration_behavior(tmp_path):
    _app, client = create_client(tmp_path)
    with client:
        without_titles = client.post(
            "/api/v1/projects/import",
            json={
                "project_id": "without-title",
                "script": SCRIPT,
                "speak_section_titles": False,
            },
        )
        assert without_titles.status_code == 201
        text = (
            tmp_path
            / "studio"
            / "projects"
            / "without-title"
            / "sections"
            / "S01"
            / "text.txt"
        ).read_text(encoding="utf-8")
        assert "[WARM]" not in text
        assert "Opening title" not in text
        assert "Hello world." in text

        with_titles = client.post(
            "/api/v1/projects/import",
            json={
                "project_id": "with-title",
                "script": SCRIPT,
                "speak_section_titles": True,
            },
        )
        assert with_titles.status_code == 201
        titled_text = (
            tmp_path
            / "studio"
            / "projects"
            / "with-title"
            / "sections"
            / "S01"
            / "text.txt"
        ).read_text(encoding="utf-8")
        assert "Opening title." in titled_text
        assert with_titles.json()["source_hash"] != without_titles.json()["source_hash"]


def test_capabilities_advertise_project_import(tmp_path):
    _app, client = create_client(tmp_path)
    with client:
        response = client.get("/api/v1/capabilities")
        assert response.status_code == 200
        payload = response.json()
        assert payload["features"]["project_import"] is True
        assert payload["endpoints"]["project_import"] == "/api/v1/projects/import"


def test_imported_project_resolves_through_existing_generate_flow(tmp_path):
    commands = FakeCommandService()
    app, client = create_client(tmp_path, commands=commands)
    with client:
        imported = client.post(
            "/api/v1/projects/import",
            json={"project_id": "demo-video", "script": SCRIPT},
        )
        assert imported.status_code == 201

        generated = client.post(
            "/api/v1/projects/demo-video/generate",
            json={"voice_name": "Narrator"},
        )
        assert generated.status_code == 202
        job = app.state.job_manager.get(generated.json()["job_id"])
        assert job.payload["project_id"] == "demo-video"
        assert job.payload["project_path"].endswith("projects/demo-video")


def test_import_uses_existing_bearer_generate_scope(tmp_path):
    auth = StudioAuthConfig(
        bearer_token="secret-token",
        scopes=frozenset({READ_SCOPE, GENERATE_SCOPE}),
        public_url=None,
        allow_insecure_public=False,
        ui_username=None,
        ui_password=None,
        trust_external_ui_auth=False,
    )
    _app, client = create_client(tmp_path, auth_config=auth)
    with client:
        unauthenticated = client.post(
            "/api/v1/projects/import",
            json={"project_id": "demo-video", "script": SCRIPT},
        )
        assert unauthenticated.status_code == 401

        authorized = client.post(
            "/api/v1/projects/import",
            headers={"Authorization": "Bearer secret-token"},
            json={"project_id": "demo-video", "script": SCRIPT},
        )
        assert authorized.status_code == 201


def test_storage_failure_does_not_publish_valid_project(tmp_path, monkeypatch):
    original = project_import_module.create_narration_project

    def broken_create(*args, **kwargs):
        project = original(*args, **kwargs)
        (project.root / "partial-marker").write_text("partial", encoding="utf-8")
        raise OSError("simulated storage failure")

    monkeypatch.setattr(project_import_module, "create_narration_project", broken_create)
    _app, client = create_client(tmp_path, raise_server_exceptions=False)
    with client:
        response = client.post(
            "/api/v1/projects/import",
            json={"project_id": "storage-failure", "script": SCRIPT},
        )
        assert response.status_code == 500
        assert not (tmp_path / "studio" / "projects" / "storage-failure").exists()
