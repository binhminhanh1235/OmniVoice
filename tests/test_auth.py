from fastapi.testclient import TestClient
import pytest

from omnivoice.auth import (
    GENERATE_SCOPE,
    MCP_SCOPE,
    READ_SCOPE,
    StudioAuthConfig,
    required_scope_for_request,
)
from omnivoice.server.app import create_studio_app


def config(
    *,
    token=None,
    scopes=frozenset({READ_SCOPE, GENERATE_SCOPE, MCP_SCOPE}),
    public_url=None,
    allow_insecure_public=False,
    ui_username=None,
    ui_password=None,
    trust_external_ui_auth=False,
):
    return StudioAuthConfig(
        bearer_token=token,
        scopes=frozenset(scopes),
        public_url=public_url,
        allow_insecure_public=allow_insecure_public,
        ui_username=ui_username,
        ui_password=ui_password,
        trust_external_ui_auth=trust_external_ui_auth,
    )


def test_scope_mapping_uses_least_privilege():
    assert required_scope_for_request("GET", "/api/v1/projects") == READ_SCOPE
    assert (
        required_scope_for_request("POST", "/api/v1/projects/demo/generate")
        == GENERATE_SCOPE
    )
    assert required_scope_for_request("POST", "/api/v1/jobs/job-1/cancel") == GENERATE_SCOPE
    assert required_scope_for_request("POST", "/mcp") == MCP_SCOPE
    assert required_scope_for_request("GET", "/health") is None


def test_public_mode_fails_closed_without_machine_token():
    auth = config(public_url="https://omnivoice.example.com")
    with pytest.raises(RuntimeError, match="OMNIVOICE_API_TOKEN"):
        auth.validate(mount_ui=False, mount_mcp=False)


def test_public_mcp_requires_mcp_scope():
    auth = config(
        token="secret",
        scopes={READ_SCOPE},
        public_url="https://omnivoice.example.com",
    )
    with pytest.raises(RuntimeError, match=MCP_SCOPE):
        auth.validate(mount_ui=False, mount_mcp=True)


def test_public_ui_requires_basic_or_trusted_external_auth():
    auth = config(
        token="secret",
        public_url="https://omnivoice.example.com",
    )
    with pytest.raises(RuntimeError, match="Public Gradio UI"):
        auth.validate(mount_ui=True, mount_mcp=False)

    config(
        token="secret",
        public_url="https://omnivoice.example.com",
        ui_username="owner",
        ui_password="password",
    ).validate(mount_ui=True, mount_mcp=False)

    config(
        token="secret",
        public_url="https://omnivoice.example.com",
        trust_external_ui_auth=True,
    ).validate(mount_ui=True, mount_mcp=False)


def test_bearer_gate_keeps_health_public_and_protects_api(tmp_path):
    auth = config(token="top-secret", scopes={READ_SCOPE})
    app = create_studio_app(
        None,
        tmp_path / "studio",
        mount_ui=False,
        mount_mcp=False,
        auth_config=auth,
    )

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["auth"]["machine"] == "bearer"

        missing = client.get("/api/v1/projects")
        assert missing.status_code == 401
        assert missing.headers["www-authenticate"].startswith("Bearer")

        wrong = client.get(
            "/api/v1/projects",
            headers={"Authorization": "Bearer wrong"},
        )
        assert wrong.status_code == 401

        allowed = client.get(
            "/api/v1/projects",
            headers={"Authorization": "Bearer top-secret"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["items"] == []

        forbidden = client.post(
            "/api/v1/projects/missing/generate",
            json={"voice_name": "Narrator"},
            headers={"Authorization": "Bearer top-secret"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["error"] == "insufficient_scope"


def test_local_mode_without_token_preserves_existing_open_behavior(tmp_path):
    app = create_studio_app(
        None,
        tmp_path / "studio",
        mount_ui=False,
        mount_mcp=False,
        auth_config=config(),
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/projects")
        assert response.status_code == 200
