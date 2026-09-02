#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Authentication policy for public OmniVoice Studio deployments.

This first layer intentionally uses one operator-managed bearer token for
machine surfaces plus optional Gradio Basic auth. It is protocol-neutral and
can later be replaced by OAuth/JWT verification without changing Studio jobs
or generation services.
"""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from typing import Iterable, Optional

READ_SCOPE = "omnivoice:read"
GENERATE_SCOPE = "omnivoice:generate"
QUEUE_SCOPE = "omnivoice:queue"
MCP_SCOPE = "omnivoice:mcp"
ADMIN_SCOPE = "omnivoice:admin"
DEFAULT_MACHINE_SCOPES = frozenset(
    {READ_SCOPE, GENERATE_SCOPE, QUEUE_SCOPE, MCP_SCOPE}
)


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _scope_set(value: Optional[str]) -> frozenset[str]:
    if not str(value or "").strip():
        return DEFAULT_MACHINE_SCOPES
    return frozenset(
        item.strip()
        for item in str(value).split(",")
        if item.strip()
    )


@dataclass(frozen=True)
class StudioAuthConfig:
    bearer_token: Optional[str]
    scopes: frozenset[str]
    public_url: Optional[str]
    allow_insecure_public: bool
    ui_username: Optional[str]
    ui_password: Optional[str]
    trust_external_ui_auth: bool

    @classmethod
    def from_env(cls) -> "StudioAuthConfig":
        token = str(os.environ.get("OMNIVOICE_API_TOKEN", "") or "").strip() or None
        username = str(os.environ.get("OMNIVOICE_UI_USERNAME", "") or "").strip() or None
        password = str(os.environ.get("OMNIVOICE_UI_PASSWORD", "") or "").strip() or None
        public_url = str(os.environ.get("OMNIVOICE_PUBLIC_URL", "") or "").strip() or None
        return cls(
            bearer_token=token,
            scopes=_scope_set(os.environ.get("OMNIVOICE_API_TOKEN_SCOPES")),
            public_url=public_url,
            allow_insecure_public=_truthy(
                os.environ.get("OMNIVOICE_ALLOW_INSECURE_PUBLIC")
            ),
            ui_username=username,
            ui_password=password,
            trust_external_ui_auth=_truthy(
                os.environ.get("OMNIVOICE_TRUST_EXTERNAL_UI_AUTH")
            ),
        )

    @property
    def bearer_enabled(self) -> bool:
        return bool(self.bearer_token)

    @property
    def ui_basic_auth(self) -> Optional[tuple[str, str]]:
        if self.ui_username and self.ui_password:
            return self.ui_username, self.ui_password
        return None

    def validate(self, *, mount_ui: bool, mount_mcp: bool) -> None:
        if bool(self.ui_username) != bool(self.ui_password):
            raise RuntimeError(
                "Set both OMNIVOICE_UI_USERNAME and OMNIVOICE_UI_PASSWORD, or neither."
            )
        if not self.public_url or self.allow_insecure_public:
            return
        if not self.bearer_enabled:
            raise RuntimeError(
                "Public OmniVoice Studio requires OMNIVOICE_API_TOKEN. "
                "Set OMNIVOICE_ALLOW_INSECURE_PUBLIC=1 only for an intentional insecure test."
            )
        if mount_mcp and MCP_SCOPE not in self.scopes:
            raise RuntimeError(
                f"Public MCP requires {MCP_SCOPE} in OMNIVOICE_API_TOKEN_SCOPES."
            )
        if mount_ui and not (self.ui_basic_auth or self.trust_external_ui_auth):
            raise RuntimeError(
                "Public Gradio UI requires OMNIVOICE_UI_USERNAME + OMNIVOICE_UI_PASSWORD, "
                "or OMNIVOICE_TRUST_EXTERNAL_UI_AUTH=1 when a trusted external access layer protects /ui."
            )

    def token_matches(self, candidate: str) -> bool:
        if not self.bearer_token:
            return False
        return hmac.compare_digest(
            self.bearer_token.encode("utf-8"),
            str(candidate).encode("utf-8"),
        )

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes or ADMIN_SCOPE in self.scopes


def required_scope_for_request(method: str, path: str) -> Optional[str]:
    """Map machine-facing HTTP requests to the least privilege scope required."""

    method = str(method or "GET").upper()
    path = str(path or "")
    if path.startswith("/mcp"):
        return MCP_SCOPE
    if not path.startswith("/api/v1"):
        return None
    if method in {"GET", "HEAD", "OPTIONS"}:
        return READ_SCOPE
    if path.startswith("/api/v1/queue"):
        return QUEUE_SCOPE
    if path.startswith("/api/v1/projects/") and path.endswith("/generate"):
        return GENERATE_SCOPE
    if path.startswith("/api/v1/jobs/") and path.endswith("/cancel"):
        return GENERATE_SCOPE
    return ADMIN_SCOPE


def _header(scope, name: bytes) -> Optional[str]:
    target = name.lower()
    for key, value in scope.get("headers", []):
        if key.lower() == target:
            return value.decode("latin-1")
    return None


class StudioBearerAuthMiddleware:
    """ASGI bearer gate for REST and mounted MCP HTTP traffic."""

    def __init__(self, app, config: StudioAuthConfig) -> None:
        self.app = app
        self.config = config

    async def _reject(self, send, *, status: int, error: str, description: str) -> None:
        body = json.dumps(
            {"error": error, "error_description": description},
            separators=(",", ":"),
        ).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        if status == 401:
            headers.append(
                (
                    b"www-authenticate",
                    b'Bearer realm="omnivoice-studio", error="invalid_token"',
                )
            )
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        required = required_scope_for_request(
            scope.get("method", "GET"), scope.get("path", "")
        )
        if required is None or not self.config.bearer_enabled:
            await self.app(scope, receive, send)
            return

        raw = _header(scope, b"authorization") or ""
        scheme, _, value = raw.partition(" ")
        if scheme.lower() != "bearer" or not value or not self.config.token_matches(value.strip()):
            await self._reject(
                send,
                status=401,
                error="invalid_token",
                description="A valid OmniVoice bearer token is required.",
            )
            return
        if not self.config.has_scope(required):
            await self._reject(
                send,
                status=403,
                error="insufficient_scope",
                description=f"Required scope: {required}",
            )
            return

        state = scope.setdefault("state", {})
        state["omnivoice_auth_scopes"] = sorted(self.config.scopes)
        await self.app(scope, receive, send)
