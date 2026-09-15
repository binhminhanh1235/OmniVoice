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

## Priority generation tools

The agent-facing generation surface is intentionally compact:

```text
generate_audio
generate_project
get_job
wait_job
list_artifacts
preview_audio
regenerate_section
regenerate_chunk
cancel_job
```

The server also keeps the read-only discovery helpers `studio_status`, `list_projects`, `inspect_project`, and `queue_status`.

### One durable lifecycle

Every GPU-bound generation mutation returns a `job_id` immediately. `generate_audio`, `generate_project`, `preview_audio`, `regenerate_section`, and `regenerate_chunk` all use the same persistent single-GPU worker.

```text
command
   |
 job_id
   |
wait_job
   |
list_artifacts
```

Prefer `wait_job` over repeated `get_job` polling. It waits on the Job Manager condition/event stream and returns when the job reaches `completed`, `failed`, or `cancelled`, or when the caller's timeout expires.

### generate_audio

Use `generate_audio` for a standalone WAV when a full Project Studio manifest is unnecessary. It supports saved voices, voice variants, language, style/instruct, speed, quality preset, and idempotent retry.

Standalone output is stored under the Studio workspace:

```text
<workspace>/artifacts/audio/job_....wav
```

### generate_project

`generate_project` remains resumable and section-aware. It reuses saved project voice/language/quality settings unless explicit overrides are supplied.

### preview_audio

`preview_audio` has two modes:

- direct text preview, written to `<workspace>/artifacts/previews/`;
- non-destructive representative project previews using the existing opening/middle/ending preview engine.

Preview generation never changes the project's selected final audio.

### regenerate_section

`regenerate_section` forces exactly one section through the established Project Studio generation path. Existing section history snapshot behavior remains active.

### regenerate_chunk

`regenerate_chunk` marks exactly one chunk for regeneration, then rebuilds only the required beat/section output using the existing chunk-resume controller.

### list_artifacts

`list_artifacts` discovers generated WAV files from durable workspace state instead of maintaining a second artifact database. Returned metadata includes:

```text
id
kind
project_id
section_id
chunk_id
filename
path
relative_path
size_bytes
duration_seconds
sample_rate
channels
```

Kinds currently include `generated_audio`, `preview_audio`, `chunk_audio`, `beat_audio`, `section_audio`, and `project_audio`.

### Idempotency and cancellation

Use a stable `idempotency_key` when retrying after a network timeout. Reusing the same key returns the existing job instead of duplicating GPU work.

Cancellation is cooperative. It takes effect at a safe checkpoint rather than killing model inference mid-section or mid-chunk.

## MCP resources

Read-only resources:

```text
omnivoice://projects/{project_id}
omnivoice://queue
```

## Recommended agent workflows

Standalone audio:

```text
generate_audio(..., idempotency_key=...)
        |
      job_id
        |
wait_job(job_id)
        |
list_artifacts(kinds=["generated_audio"])
```

Long-form project:

```text
inspect_project(project_id)
        |
preview_audio(project_id=...)
        |
wait_job(job_id)
        |
generate_project(...)
        |
wait_job(job_id)
        |
list_artifacts(project_id=...)
```

Targeted repair:

```text
regenerate_chunk(project_id, section_id, chunk_id)
        |
wait_job(job_id)
        |
list_artifacts(project_id=..., kinds=["chunk_audio", "section_audio"])
```

## CLI parity

The `omnivoice` umbrella CLI maps directly to the same REST/job contracts:

```text
omnivoice generate-audio
omnivoice generate-project
omnivoice get-job
omnivoice wait-job
omnivoice list-artifacts
omnivoice preview-audio
omnivoice regenerate-section
omnivoice regenerate-chunk
omnivoice cancel-job
```

Set `OMNIVOICE_STUDIO_URL` and optionally `OMNIVOICE_API_TOKEN` for remote Studio instances.

## Authentication

Bearer auth and scopes are implemented.

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

## Transport security

The MCP transport supports DNS-rebinding protection.

For a fixed public hostname:

```bash
export OMNIVOICE_MCP_ALLOWED_HOSTS="omnivoice.example.com,omnivoice.example.com:*"
export OMNIVOICE_MCP_ALLOWED_ORIGINS="https://omnivoice.example.com"
```

Only use `OMNIVOICE_MCP_TRUST_PROXY=1` when a trusted reverse proxy/tunnel is intentionally the security boundary.

## Still planned

The next useful command layers are download/range-resume, merge/export packaging, queue mutation tools, the Universal OmniVoice Skill, client examples, and an optional persistent control plane/worker registry.

See [project-studio-roadmap.md](project-studio-roadmap.md) for canonical status.
