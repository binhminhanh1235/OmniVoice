#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Remote-first umbrella CLI for OmniVoice Studio AI-native tools."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

DEFAULT_URL = "http://127.0.0.1:8000"


def _csv(value: Optional[str]) -> Optional[list[str]]:
    if value is None:
        return None
    items = [item.strip() for item in value.replace(";", ",").split(",")]
    items = [item for item in items if item]
    return items or None


class StudioClient:
    def __init__(self, base_url: str, token: Optional[str] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Optional[dict[str, Any]] = None,
        query: Optional[dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        url = self.base_url + path
        if query:
            pairs: list[tuple[str, str]] = []
            for key, value in query.items():
                if value is None:
                    continue
                if isinstance(value, list):
                    pairs.extend((key, str(item)) for item in value)
                else:
                    pairs.append((key, str(value)))
            if pairs:
                url += "?" + urllib.parse.urlencode(pairs)

        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw)
            except json.JSONDecodeError:
                detail = raw
            raise SystemExit(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise SystemExit(f"Cannot reach OmniVoice Studio at {self.base_url}: {exc.reason}") from exc
        return json.loads(raw) if raw else {}


def _common_generation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--voice")
    parser.add_argument("--variant")
    parser.add_argument("--language")
    parser.add_argument("--quality", choices=("SAFE", "BALANCED", "FAST"))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--idempotency-key")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OmniVoice Studio AI-native CLI")
    parser.add_argument(
        "--url",
        default=os.environ.get("OMNIVOICE_STUDIO_URL", DEFAULT_URL),
        help="Studio origin URL. Defaults to $OMNIVOICE_STUDIO_URL or localhost:8000.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("OMNIVOICE_API_TOKEN"),
        help="Bearer token. Defaults to $OMNIVOICE_API_TOKEN.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    generate_audio = sub.add_parser("generate-audio", help="Generate one standalone WAV")
    generate_audio.add_argument("text")
    _common_generation_args(generate_audio)
    generate_audio.add_argument("--instruct")
    generate_audio.add_argument("--speed", type=float)
    generate_audio.add_argument("--style", default="DEFAULT")

    generate_project = sub.add_parser("generate-project", help="Generate/resume a project")
    generate_project.add_argument("project_id")
    _common_generation_args(generate_project)
    generate_project.add_argument("--sections")
    generate_project.add_argument("--no-resume", action="store_true")

    get_job = sub.add_parser("get-job", help="Read one durable job")
    get_job.add_argument("job_id")

    wait_job = sub.add_parser("wait-job", help="Wait efficiently for job completion")
    wait_job.add_argument("job_id")
    wait_job.add_argument("--timeout", type=float, default=60.0)
    wait_job.add_argument("--events", action="store_true")

    artifacts = sub.add_parser("list-artifacts", help="List generated audio artifacts")
    artifacts.add_argument("--project")
    artifacts.add_argument("--kind", action="append")

    preview = sub.add_parser("preview-audio", help="Generate direct or project preview audio")
    preview_target = preview.add_mutually_exclusive_group(required=True)
    preview_target.add_argument("--text")
    preview_target.add_argument("--project")
    _common_generation_args(preview)
    preview.add_argument("--labels")
    preview.add_argument("--instruct")
    preview.add_argument("--speed", type=float)
    preview.add_argument("--style", default="DEFAULT")

    section = sub.add_parser("regenerate-section", help="Force-regenerate one project section")
    section.add_argument("project_id")
    section.add_argument("section_id")
    _common_generation_args(section)

    chunk = sub.add_parser("regenerate-chunk", help="Regenerate one chunk and rebuild its section")
    chunk.add_argument("project_id")
    chunk.add_argument("section_id")
    chunk.add_argument("chunk_id")
    _common_generation_args(chunk)

    cancel = sub.add_parser("cancel-job", help="Request cooperative job cancellation")
    cancel.add_argument("job_id")
    return parser


def _overrides(args) -> dict[str, Any]:
    payload: dict[str, Any] = {"strict": bool(getattr(args, "strict", False))}
    mapping = {
        "voice": "voice_name",
        "variant": "voice_variant",
        "language": "language",
        "quality": "quality_preset",
    }
    for attr, key in mapping.items():
        value = getattr(args, attr, None)
        if value is not None:
            payload[key] = value
    return payload


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    client = StudioClient(args.url, args.token)
    command = args.command

    if command == "generate-audio":
        body = _overrides(args)
        body.update({"text": args.text, "style": args.style})
        if args.instruct is not None:
            body["instruct"] = args.instruct
        if args.speed is not None:
            body["speed"] = args.speed
        result = client.request(
            "POST",
            "/api/v1/audio/generate",
            body=body,
            idempotency_key=args.idempotency_key,
        )
    elif command == "generate-project":
        body = _overrides(args)
        body["resume"] = not args.no_resume
        sections = _csv(args.sections)
        if sections:
            body["sections"] = sections
        result = client.request(
            "POST",
            f"/api/v1/projects/{urllib.parse.quote(args.project_id)}/generate",
            body=body,
            idempotency_key=args.idempotency_key,
        )
    elif command == "get-job":
        result = client.request("GET", f"/api/v1/jobs/{urllib.parse.quote(args.job_id)}")
    elif command == "wait-job":
        result = client.request(
            "GET",
            f"/api/v1/jobs/{urllib.parse.quote(args.job_id)}/wait",
            query={"timeout_seconds": args.timeout, "include_events": str(args.events).lower()},
        )
    elif command == "list-artifacts":
        result = client.request(
            "GET",
            "/api/v1/artifacts",
            query={"project_id": args.project, "kind": args.kind},
        )
    elif command == "preview-audio":
        body = _overrides(args)
        if args.text is not None:
            body["text"] = args.text
        if args.project is not None:
            body["project_id"] = args.project
        labels = _csv(args.labels)
        if labels:
            body["labels"] = labels
        if args.instruct is not None:
            body["instruct"] = args.instruct
        if args.speed is not None:
            body["speed"] = args.speed
        body["style"] = args.style
        result = client.request(
            "POST",
            "/api/v1/audio/preview",
            body=body,
            idempotency_key=args.idempotency_key,
        )
    elif command == "regenerate-section":
        result = client.request(
            "POST",
            "/api/v1/projects/"
            f"{urllib.parse.quote(args.project_id)}/sections/"
            f"{urllib.parse.quote(args.section_id)}/regenerate",
            body=_overrides(args),
            idempotency_key=args.idempotency_key,
        )
    elif command == "regenerate-chunk":
        result = client.request(
            "POST",
            "/api/v1/projects/"
            f"{urllib.parse.quote(args.project_id)}/sections/"
            f"{urllib.parse.quote(args.section_id)}/chunks/"
            f"{urllib.parse.quote(args.chunk_id)}/regenerate",
            body=_overrides(args),
            idempotency_key=args.idempotency_key,
        )
    elif command == "cancel-job":
        result = client.request(
            "POST",
            f"/api/v1/jobs/{urllib.parse.quote(args.job_id)}/cancel",
            body={},
        )
    else:
        raise SystemExit(f"Unknown command: {command}")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
