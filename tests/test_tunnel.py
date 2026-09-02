import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from omnivoice.cli.studio_server import _public_endpoint, build_parser
from omnivoice.tunnel import (
    CloudflareTunnel,
    configure_mcp_security_for_public_url,
    parse_public_url,
)


def test_parse_public_url_builds_stable_surface_urls():
    endpoint = parse_public_url("https://omnivoice.example.com/")
    assert endpoint.url == "https://omnivoice.example.com"
    assert endpoint.host == "omnivoice.example.com"
    assert endpoint.ui_url == "https://omnivoice.example.com/ui"
    assert endpoint.api_url == "https://omnivoice.example.com/api/v1"
    assert endpoint.mcp_url == "https://omnivoice.example.com/mcp"

    with pytest.raises(ValueError):
        parse_public_url("omnivoice.example.com")
    with pytest.raises(ValueError):
        parse_public_url("https://omnivoice.example.com/ui")


def test_public_url_configures_mcp_allowlists_without_overwriting_explicit_values(monkeypatch):
    monkeypatch.delenv("OMNIVOICE_MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("OMNIVOICE_MCP_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("OMNIVOICE_PUBLIC_URL", raising=False)

    endpoint = configure_mcp_security_for_public_url("https://omnivoice.example.com")
    assert endpoint.host == "omnivoice.example.com"
    assert os.environ["OMNIVOICE_MCP_ALLOWED_HOSTS"] == (
        "omnivoice.example.com,omnivoice.example.com:*"
    )
    assert os.environ["OMNIVOICE_MCP_ALLOWED_ORIGINS"] == (
        "https://omnivoice.example.com"
    )
    assert os.environ["OMNIVOICE_PUBLIC_URL"] == "https://omnivoice.example.com"

    monkeypatch.setenv("OMNIVOICE_MCP_ALLOWED_HOSTS", "explicit.example.com")
    monkeypatch.setenv("OMNIVOICE_MCP_ALLOWED_ORIGINS", "https://explicit.example.com")
    configure_mcp_security_for_public_url("https://other.example.com")
    assert os.environ["OMNIVOICE_MCP_ALLOWED_HOSTS"] == "explicit.example.com"
    assert os.environ["OMNIVOICE_MCP_ALLOWED_ORIGINS"] == "https://explicit.example.com"


def test_tunnel_requires_public_url_for_safe_remote_mcp(monkeypatch):
    monkeypatch.delenv("OMNIVOICE_PUBLIC_URL", raising=False)
    args = build_parser().parse_args(["serve", "--tunnel"])
    with pytest.raises(ValueError, match="requires --public-url"):
        _public_endpoint(args)

    args = build_parser().parse_args(
        ["serve", "--tunnel", "--public-url", "https://omnivoice.example.com"]
    )
    assert _public_endpoint(args).mcp_url == "https://omnivoice.example.com/mcp"


class FakeProcess:
    def __init__(self, command):
        self.command = list(command)
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode or 0

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_cloudflare_tunnel_uses_private_token_file_not_command_line(monkeypatch):
    secret = "super-secret-tunnel-token"
    monkeypatch.setenv("CLOUDFLARE_TUNNEL_TOKEN", secret)
    monkeypatch.setattr("omnivoice.tunnel.shutil.which", lambda name: "/usr/bin/cloudflared")

    created = []

    def fake_popen(command):
        process = FakeProcess(command)
        created.append(process)
        return process

    monkeypatch.setattr("omnivoice.tunnel.subprocess.Popen", fake_popen)
    tunnel = CloudflareTunnel(startup_grace_seconds=0)
    tunnel.start()

    assert len(created) == 1
    command = created[0].command
    assert secret not in command
    assert command[:2] == ["/usr/bin/cloudflared", "tunnel"]
    assert "--token-file" in command
    token_path = Path(command[command.index("--token-file") + 1])
    assert token_path.read_text(encoding="utf-8") == secret
    assert token_path.stat().st_mode & 0o777 == 0o600

    tunnel.stop()
    assert created[0].terminated is True
    assert token_path.exists() is False


def test_cloudflare_tunnel_reports_missing_binary_or_token(monkeypatch):
    monkeypatch.setattr("omnivoice.tunnel.shutil.which", lambda name: None)
    with pytest.raises(RuntimeError, match="cloudflared was not found"):
        CloudflareTunnel(startup_grace_seconds=0).start()

    monkeypatch.setattr("omnivoice.tunnel.shutil.which", lambda name: "/usr/bin/cloudflared")
    monkeypatch.delenv("CLOUDFLARE_TUNNEL_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="Tunnel token is missing"):
        CloudflareTunnel(startup_grace_seconds=0).start()


# Auth tests live in this already-selected CI module so the public-deployment
# guardrails are exercised by the current regression workflow.
from fastapi.testclient import TestClient

from omnivoice.auth import GENERATE_SCOPE, MCP_SCOPE, READ_SCOPE, StudioAuthConfig
from omnivoice.server.app import create_studio_app


def _auth_config(
    *,
    token=None,
    scopes=frozenset({READ_SCOPE, GENERATE_SCOPE, MCP_SCOPE}),
    public_url=None,
    ui_username=None,
    ui_password=None,
    trust_external_ui_auth=False,
):
    return StudioAuthConfig(
        bearer_token=token,
        scopes=frozenset(scopes),
        public_url=public_url,
        allow_insecure_public=False,
        ui_username=ui_username,
        ui_password=ui_password,
        trust_external_ui_auth=trust_external_ui_auth,
    )


def test_public_auth_fails_closed_without_machine_token():
    auth = _auth_config(public_url="https://omnivoice.example.com")
    with pytest.raises(RuntimeError, match="OMNIVOICE_API_TOKEN"):
        auth.validate(mount_ui=False, mount_mcp=False)


def test_public_auth_requires_mcp_scope_and_ui_protection():
    with pytest.raises(RuntimeError, match=MCP_SCOPE):
        _auth_config(
            token="secret",
            scopes={READ_SCOPE},
            public_url="https://omnivoice.example.com",
        ).validate(mount_ui=False, mount_mcp=True)

    with pytest.raises(RuntimeError, match="Public Gradio UI"):
        _auth_config(
            token="secret",
            public_url="https://omnivoice.example.com",
        ).validate(mount_ui=True, mount_mcp=False)

    _auth_config(
        token="secret",
        public_url="https://omnivoice.example.com",
        ui_username="owner",
        ui_password="password",
    ).validate(mount_ui=True, mount_mcp=False)


def test_bearer_gate_keeps_health_public_and_enforces_scope(tmp_path):
    auth = _auth_config(token="top-secret", scopes={READ_SCOPE})
    app = create_studio_app(
        None,
        tmp_path / "studio",
        mount_ui=False,
        mount_mcp=False,
        auth_config=auth,
    )
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/projects").status_code == 401
        assert client.get(
            "/api/v1/projects",
            headers={"Authorization": "Bearer wrong"},
        ).status_code == 401

        allowed = client.get(
            "/api/v1/projects",
            headers={"Authorization": "Bearer top-secret"},
        )
        assert allowed.status_code == 200

        forbidden = client.post(
            "/api/v1/projects/missing/generate",
            json={"voice_name": "Narrator"},
            headers={"Authorization": "Bearer top-secret"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["error"] == "insufficient_scope"
