#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""CLI for the unified OmniVoice Studio web/API/MCP server."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import torch

from omnivoice import OmniVoice
from omnivoice.hardware_quality import detect_hardware
from omnivoice.runtime_workspace import (
    RuntimeWorkspace,
    detect_runtime_workspace,
    ensure_runtime_workspace,
)
from omnivoice.server.app import create_studio_app
from omnivoice.tunnel import (
    DEFAULT_PUBLIC_URL_ENV,
    DEFAULT_TUNNEL_TOKEN_ENV,
    CloudflareTunnel,
    configure_mcp_security_for_public_url,
)
from omnivoice.utils.common import get_best_device

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OmniVoice Studio AI-native server")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser(
        "serve",
        help="Serve Gradio UI, REST API, and MCP from one FastAPI process.",
    )
    serve.add_argument("--model", default="k2-fsa/OmniVoice")
    serve.add_argument("--device", default=None)
    serve.add_argument("--workspace", default=None)
    serve.add_argument("--asr-model", default="openai/whisper-small.en")
    serve.add_argument("--asr-device", default="cpu")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--no-ui",
        action="store_true",
        default=False,
        help="Serve API/MCP only; do not mount Gradio at /ui.",
    )
    serve.add_argument(
        "--tunnel",
        action="store_true",
        default=False,
        help="Run a remotely-managed Cloudflare Tunnel connector with the Studio server.",
    )
    serve.add_argument(
        "--public-url",
        default=None,
        help=(
            "Stable external origin, e.g. https://omnivoice.example.com. "
            f"Defaults to ${DEFAULT_PUBLIC_URL_ENV}."
        ),
    )
    serve.add_argument(
        "--cloudflared",
        default="cloudflared",
        help="cloudflared binary name or path.",
    )
    serve.add_argument(
        "--tunnel-token-env",
        default=DEFAULT_TUNNEL_TOKEN_ENV,
        help="Environment variable containing the remotely-managed tunnel token.",
    )
    serve.add_argument(
        "--tunnel-loglevel",
        choices=("debug", "info", "warn", "error", "fatal"),
        default="info",
    )
    return parser


def _runtime_for_workspace(workspace: str | None) -> RuntimeWorkspace:
    detected = detect_runtime_workspace()
    if not workspace:
        return ensure_runtime_workspace(detected)
    custom = RuntimeWorkspace(
        environment=detected.environment,
        root=Path(workspace).expanduser(),
        ephemeral=detected.ephemeral,
        input_root=detected.input_root,
        persistence_backend=detected.persistence_backend,
        notes=detected.notes + ("Workspace overridden by --workspace.",),
    )
    return ensure_runtime_workspace(custom)


def _public_endpoint(args):
    value = str(args.public_url or os.environ.get(DEFAULT_PUBLIC_URL_ENV, "") or "").strip()
    if not value:
        if args.tunnel:
            raise ValueError(
                "--tunnel requires --public-url (or OMNIVOICE_PUBLIC_URL) so MCP can "
                "allow exactly the stable public hostname."
            )
        return None
    return configure_mcp_security_for_public_url(value)


def serve(args) -> int:
    import uvicorn

    runtime = _runtime_for_workspace(args.workspace)
    hardware = detect_hardware()
    device = args.device or get_best_device()
    public = _public_endpoint(args)

    logger.info("Runtime: %s", runtime.summary())
    logger.info("Hardware: %s", hardware.summary())
    logger.info(
        "Loading OmniVoice model=%s device=%s asr_device=%s",
        args.model,
        device,
        args.asr_device,
    )
    model = OmniVoice.from_pretrained(
        args.model,
        device_map=device,
        dtype=torch.float16,
        load_asr=True,
        asr_model_name=args.asr_model,
        asr_device=args.asr_device,
    )

    app = create_studio_app(
        model,
        runtime.root,
        runtime=runtime,
        mount_ui=not args.no_ui,
    )
    logger.info("Studio UI: http://%s:%s/ui", args.host, args.port)
    logger.info("REST API: http://%s:%s/api/v1", args.host, args.port)
    logger.info("MCP: http://%s:%s/mcp", args.host, args.port)
    logger.info("OpenAPI: http://%s:%s/docs", args.host, args.port)
    logger.info("Health: http://%s:%s/health", args.host, args.port)
    if public is not None:
        logger.info("Public UI: %s", public.ui_url)
        logger.info("Public REST API: %s", public.api_url)
        logger.info("Public MCP: %s", public.mcp_url)
        logger.info("Public Health: %s", public.health_url)

    if not args.tunnel:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        return 0

    tunnel = CloudflareTunnel(
        binary=args.cloudflared,
        token_env=args.tunnel_token_env,
        loglevel=args.tunnel_loglevel,
    )
    logger.info(
        "Starting Cloudflare Tunnel using token from $%s (token is not placed on the command line).",
        args.tunnel_token_env,
    )
    with tunnel:
        logger.info("Named tunnel connector is running; starting Studio origin server.")
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        return serve(args)
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
