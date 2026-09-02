#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Stable public tunnel lifecycle for ephemeral Studio runtimes.

The first implementation targets remotely-managed Cloudflare Tunnel. Tunnel
routing/hostname configuration remains in Cloudflare; a Kaggle/Colab runtime
only needs the tunnel token to reconnect the same public hostname to the local
OmniVoice Studio server.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


DEFAULT_TUNNEL_TOKEN_ENV = "CLOUDFLARE_TUNNEL_TOKEN"
DEFAULT_PUBLIC_URL_ENV = "OMNIVOICE_PUBLIC_URL"


@dataclass(frozen=True)
class PublicEndpoint:
    url: str
    origin: str
    host: str

    @property
    def ui_url(self) -> str:
        return self.url.rstrip("/") + "/ui"

    @property
    def api_url(self) -> str:
        return self.url.rstrip("/") + "/api/v1"

    @property
    def mcp_url(self) -> str:
        return self.url.rstrip("/") + "/mcp"

    @property
    def health_url(self) -> str:
        return self.url.rstrip("/") + "/health"


def parse_public_url(value: str) -> PublicEndpoint:
    raw = str(value or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Public URL must be an absolute http(s) URL")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("Public URL must contain only scheme and host, without a path/query")

    default_port = (parsed.scheme == "https" and parsed.port in {None, 443}) or (
        parsed.scheme == "http" and parsed.port in {None, 80}
    )
    host = parsed.hostname if default_port else f"{parsed.hostname}:{parsed.port}"
    origin = f"{parsed.scheme}://{host}"
    return PublicEndpoint(url=origin, origin=origin, host=host)


def configure_mcp_security_for_public_url(value: str) -> PublicEndpoint:
    """Configure MCP DNS-rebinding allowlists unless the caller set them already."""

    endpoint = parse_public_url(value)
    if not os.environ.get("OMNIVOICE_MCP_ALLOWED_HOSTS"):
        hosts = [endpoint.host]
        if ":" not in endpoint.host:
            hosts.append(endpoint.host + ":*")
        os.environ["OMNIVOICE_MCP_ALLOWED_HOSTS"] = ",".join(hosts)
    if not os.environ.get("OMNIVOICE_MCP_ALLOWED_ORIGINS"):
        os.environ["OMNIVOICE_MCP_ALLOWED_ORIGINS"] = endpoint.origin
    os.environ.setdefault(DEFAULT_PUBLIC_URL_ENV, endpoint.url)
    return endpoint


class CloudflareTunnel:
    """Start/stop a remotely-managed cloudflared connector safely."""

    def __init__(
        self,
        *,
        binary: str = "cloudflared",
        token_env: str = DEFAULT_TUNNEL_TOKEN_ENV,
        loglevel: str = "info",
        startup_grace_seconds: float = 0.8,
    ) -> None:
        self.binary = str(binary).strip() or "cloudflared"
        self.token_env = str(token_env).strip() or DEFAULT_TUNNEL_TOKEN_ENV
        self.loglevel = str(loglevel).strip() or "info"
        self.startup_grace_seconds = max(0.0, float(startup_grace_seconds))
        self.process: Optional[subprocess.Popen] = None
        self._tempdir: Optional[tempfile.TemporaryDirectory] = None
        self.token_file: Optional[Path] = None

    def _resolve_binary(self) -> str:
        candidate = Path(self.binary).expanduser()
        if candidate.parent != Path(".") or os.sep in self.binary:
            if candidate.exists() and candidate.is_file():
                return str(candidate.resolve())
        resolved = shutil.which(self.binary)
        if not resolved:
            raise RuntimeError(
                "cloudflared was not found. Install it first or pass --cloudflared /path/to/cloudflared."
            )
        return resolved

    def _write_token_file(self) -> Path:
        token = str(os.environ.get(self.token_env, "") or "").strip()
        if not token:
            raise RuntimeError(
                f"Tunnel token is missing. Put it in environment variable {self.token_env}."
            )
        self._tempdir = tempfile.TemporaryDirectory(prefix="omnivoice-cloudflared-")
        path = Path(self._tempdir.name) / "tunnel-token"
        path.write_text(token, encoding="utf-8")
        path.chmod(0o600)
        self.token_file = path
        return path

    def start(self) -> "CloudflareTunnel":
        if self.process is not None and self.process.poll() is None:
            return self
        binary = self._resolve_binary()
        token_file = self._write_token_file()
        command = [
            binary,
            "tunnel",
            "--no-autoupdate",
            "--loglevel",
            self.loglevel,
            "run",
            "--token-file",
            str(token_file),
        ]
        try:
            self.process = subprocess.Popen(command)
            if self.startup_grace_seconds:
                time.sleep(self.startup_grace_seconds)
            code = self.process.poll()
            if code is not None:
                raise RuntimeError(f"cloudflared exited during startup with code {code}")
            return self
        except Exception:
            self.stop()
            raise

    def stop(self, timeout: float = 5.0) -> None:
        process = self.process
        self.process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=max(0.0, float(timeout)))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        if self._tempdir is not None:
            self._tempdir.cleanup()
            self._tempdir = None
        self.token_file = None

    def __enter__(self) -> "CloudflareTunnel":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
