# OmniVoice Studio AI-native foundation

OmniVoice Studio is evolving from a Gradio-only application into one production engine with multiple interfaces.

```text
                         OmniVoice Studio
                               │
              ┌────────────────┼────────────────┐
              │                │                │
            /ui             /api/v1           /mcp
              │                │                │
           Gradio             REST            AI clients
              │                │                │
              └──────── Application Services ──┘
                               │
                      Persistent Job Manager
                               │
                    Project / Voice / Queue
                               │
                         OmniVoice Core
```

The Gradio UI remains supported. It is mounted under the same FastAPI process instead of being the only way to reach the application.

## Unified server

```bash
omnivoice-studio serve \
  --workspace /kaggle/working/OmniVoiceStudio \
  --host 0.0.0.0 \
  --port 8000
```

Current endpoints:

```text
/ui                            Gradio web UI
/health                        lightweight health check
/api/v1/capabilities           runtime and feature discovery
/api/v1/hardware               GPU / VRAM / quality recommendation
/api/v1/projects               project list, optional status filter
/api/v1/projects/{id}          one project summary
/api/v1/queue                  queue summary
/api/v1/jobs                   job list
/api/v1/jobs/{id}              durable job + event history
/api/v1/jobs/{id}/events       events after a sequence number
/api/v1/jobs/{id}/cancel       cooperative cancellation request
/docs                          OpenAPI documentation
```

The legacy `omnivoice-project-studio --share` launcher remains available while the stable-hostname publishing layer is being built.

## Application service boundary

`StudioService` is protocol-neutral. REST and future MCP tools call this layer rather than importing Gradio callbacks.

```text
FastAPI route ─┐
               ├── StudioService ── project/status/queue modules
MCP tool ──────┘
```

## Persistent single-GPU Job Manager

GPU-bound tasks run through one FIFO worker. This prevents Preview, TTS generation and Voice Stability from competing for the same Kaggle GPU once their handlers are registered.

```text
QUEUED
  ↓
RUNNING
  ├──→ COMPLETED
  ├──→ FAILED
  └──→ CANCEL_REQUESTED → safe checkpoint → CANCELLED
```

State and bounded event history are stored in:

```text
<workspace>/jobs.json
```

If the server/runtime stops while a job is `RUNNING` or `CANCEL_REQUESTED`, startup recovers it to `QUEUED`. Project generation handlers can then rely on `section-status.json` to resume only unfinished sections.

### Idempotency

`StudioJobManager.submit(..., idempotency_key=...)` returns the existing job for the same key instead of duplicating work. This is essential for AI clients that may retry after a network timeout.

### Cooperative cancellation

The worker is never force-killed in the middle of model inference. Handlers call `ctx.checkpoint()` at safe boundaries such as between sections/chunks. A cancellation request becomes effective at the next checkpoint.

## Next write-capable slice

The next layer registers real handlers and write endpoints:

```text
POST /api/v1/projects/{id}/generate
          ↓
        job_id
          ↓
   single GPU worker
          ↓
 section-by-section generation
          ↓
 section-status.json checkpoint
```

The HTTP request returns immediately. Clients poll job state or consume the future SSE stream instead of keeping one request open for a long render.

## Stable hostname plan

AI clients should eventually configure one permanent endpoint such as:

```text
https://omnivoice.example.com/mcp
```

They must not point directly at a random `*.gradio.live` session URL.

```text
ChatGPT / Claude / Antigravity
             │
       stable hostname
             │
         named tunnel
             │
   Kaggle / Colab port 8000
             │
      OmniVoice Studio
```

A later control plane can replace direct tunnel routing without changing the MCP URL configured in clients.

## Security direction

The stable public endpoint will use API authentication independent from Gradio UI authentication. Planned scopes:

```text
omnivoice:read
omnivoice:generate
omnivoice:queue
omnivoice:admin
```

Destructive operations are not part of the initial MCP tool set.

## Development sequence

1. [x] Application Service layer.
2. [x] Unified FastAPI + mounted Gradio server.
3. [x] Read-only REST/OpenAPI endpoints.
4. [x] Persistent single-GPU Job Manager and durable event history.
5. [ ] Write REST handlers for preview/generate/queue/regenerate/merge.
6. [ ] SSE event stream.
7. [ ] MCP server using the same services/jobs.
8. [ ] Stable hostname / named tunnel deployment path.
9. [ ] Universal OmniVoice Skill.
10. [ ] ChatGPT, Claude and Antigravity adapters.
11. [ ] Optional persistent control plane and worker registry.
