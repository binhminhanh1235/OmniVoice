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
