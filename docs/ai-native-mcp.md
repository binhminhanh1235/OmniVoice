# OmniVoice Studio MCP

OmniVoice Studio exposes Model Context Protocol (MCP) from the same unified server as the Gradio UI and REST API.

```text
OmniVoice Studio :8000
├── /ui       Gradio Web UI
├── /api/v1   REST / OpenAPI
├── /mcp      Streamable HTTP MCP
└── /health   runtime health
```

The MCP adapter does not contain a second TTS implementation. Read operations use `StudioService`; mutations submit work to the same persistent `StudioJobManager` used by REST.

## Transport

MCP uses Streamable HTTP and is mounted at:

```text
/mcp
```

The unified launcher remains:

```bash
omnivoice-studio serve \
  --workspace /kaggle/working/OmniVoiceStudio \
  --host 0.0.0.0 \
  --port 8000
```

A future fixed hostname can therefore expose all three surfaces without changing the Studio process:

```text
https://omnivoice.example.com/ui
https://omnivoice.example.com/api/v1
https://omnivoice.example.com/mcp
```

## MCP tools v1

The initial tool set is intentionally task-oriented and small:

```text
studio_status
list_projects
inspect_project
queue_status
generate_project
get_job
cancel_job
```

`generate_project` is asynchronous. It submits a durable single-GPU job and immediately returns:

```json
{
  "job_id": "job_...",
  "status": "queued",
  "job_url": "/api/v1/jobs/job_...",
  "events_url": "/api/v1/jobs/job_.../stream"
}
```

AI clients should use a stable `idempotency_key` when retrying a command after a network timeout. Repeating the same key returns the existing job instead of duplicating GPU work.

Cancellation is cooperative. It never kills model inference in the middle of a section; the cancellation becomes effective at the next safe checkpoint.

## MCP resources

Read-only resources are also exposed:

```text
omnivoice://projects/{project_id}
omnivoice://queue
```

## Recommended agent workflow

```text
list_projects(statuses=[PENDING, GENERATING])
        ↓
inspect_project(project_id)
        ↓
generate_project(..., idempotency_key=...)
        ↓
get_job(job_id)
        ↓
SSE /api/v1/jobs/{job_id}/stream for live progress
```

The MCP server returns job IDs rather than holding one tool call open for the duration of a long TTS render.

## Transport security

The MCP SDK enables DNS-rebinding protection for local development. Public fixed-host deployments should provide explicit host/origin allowlists.

Example:

```bash
export OMNIVOICE_MCP_ALLOWED_HOSTS="omnivoice.example.com,omnivoice.example.com:*"
export OMNIVOICE_MCP_ALLOWED_ORIGINS="https://omnivoice.example.com"
```

When a trusted reverse proxy or named tunnel is intentionally the security boundary, protection can be explicitly delegated:

```bash
export OMNIVOICE_MCP_TRUST_PROXY=1
```

Do not enable that option for an untrusted direct public listener.

Authentication/scopes are a separate upcoming layer. Until API authentication is implemented, do not expose mutation-capable MCP endpoints on an unrestricted public hostname.

## ChatGPT, Claude, and Antigravity

The intended deployment model is one stable remote endpoint configured once in clients:

```text
https://omnivoice.example.com/mcp
```

Kaggle or Colab session URLs remain implementation details behind the publishing layer. The next milestone is the stable hostname / named tunnel path, followed by API authentication and the Universal OmniVoice Skill.
