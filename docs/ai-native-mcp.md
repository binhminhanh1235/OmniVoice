# OmniVoice Studio MCP

OmniVoice Studio exposes Model Context Protocol from the same unified process as Gradio and REST.

```text
OmniVoice Studio :8000
├── /ui       Gradio Studio
├── /api/v1   REST / OpenAPI
├── /mcp      Streamable HTTP MCP
└── /health   runtime health
```

The MCP adapter does not own a second TTS implementation. Read operations use `StudioService`; generation mutations submit durable jobs through `StudioJobManager`.

## Transport

MCP uses Streamable HTTP and is mounted at:

```text
/mcp
```

Launch:

```bash
omnivoice-studio serve \
  --workspace /kaggle/working/OmniVoiceStudio \
  --host 0.0.0.0 \
  --port 8000
```

## MCP tools v1

Current task-oriented tools:

```text
studio_status
list_projects
inspect_project
queue_status
generate_project
get_job
cancel_job
```

### generate_project

`generate_project` is asynchronous. It submits a durable job and returns immediately:

```json
{
  "job_id": "job_...",
  "status": "queued",
  "job_url": "/api/v1/jobs/job_...",
  "events_url": "/api/v1/jobs/job_.../stream"
}
```

Use a stable `idempotency_key` when retrying after a network timeout. Reusing the same key returns the existing job instead of duplicating GPU work.

### Cancellation

Cancellation is cooperative. It takes effect at a safe checkpoint rather than killing model inference mid-section.

## MCP resources

Read-only resources:

```text
omnivoice://projects/{project_id}
omnivoice://queue
```

## Recommended agent workflow

```text
list_projects(...)
        |
inspect_project(project_id)
        |
generate_project(..., idempotency_key=...)
        |
      job_id
        |
get_job(job_id)
        |
SSE /api/v1/jobs/{job_id}/stream
```

## Authentication

Bearer auth and scopes are implemented.

Example:

```bash
export OMNIVOICE_API_TOKEN="strong-secret"
export OMNIVOICE_API_TOKEN_SCOPES="omnivoice:read,omnivoice:generate,omnivoice:queue,omnivoice:mcp"
```

Relevant scopes:

```text
omnivoice:read
omnivoice:generate
omnivoice:queue
omnivoice:mcp
omnivoice:admin
```

A valid token with insufficient scope receives a different authorization failure from an invalid/missing token.

## Transport security

The MCP transport supports DNS-rebinding protection.

For a fixed public hostname:

```bash
export OMNIVOICE_MCP_ALLOWED_HOSTS="omnivoice.example.com,omnivoice.example.com:*"
export OMNIVOICE_MCP_ALLOWED_ORIGINS="https://omnivoice.example.com"
```

When `--public-url` is used, Studio configures the public-host allowlist unless explicit values already exist.

Only use:

```bash
export OMNIVOICE_MCP_TRUST_PROXY=1
```

when a trusted reverse proxy/tunnel is intentionally the security boundary.

## Stable public MCP URL

Named Cloudflare Tunnel support is implemented, so clients can keep a stable URL:

```text
https://omnivoice.example.com/mcp
```

Example environment:

```bash
export OMNIVOICE_API_TOKEN="strong-secret"
export OMNIVOICE_API_TOKEN_SCOPES="omnivoice:read,omnivoice:generate,omnivoice:queue,omnivoice:mcp"
export CLOUDFLARE_TUNNEL_TOKEN="..."
export OMNIVOICE_PUBLIC_URL="https://omnivoice.example.com"
```

Launch:

```bash
omnivoice-studio serve \
  --workspace ./OmniVoiceStudio \
  --host 0.0.0.0 \
  --port 8000 \
  --tunnel \
  --public-url https://omnivoice.example.com
```

## What is still planned?

The MCP foundation is production-merged, but the command surface is intentionally small.

Planned after REST command contracts stabilize:

- preview tool;
- queue mutation tools;
- regenerate chunk tool;
- merge/export tool;
- Universal OmniVoice Skill;
- ChatGPT / Claude Code / generic MCP examples;
- optional control plane + worker registry.

See [project-studio-roadmap.md](project-studio-roadmap.md) for canonical status.
