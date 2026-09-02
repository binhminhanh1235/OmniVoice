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
/ui                                   Gradio web UI
/health                               lightweight health check
/api/v1/capabilities                  runtime and feature discovery
/api/v1/hardware                      GPU / VRAM / quality recommendation
/api/v1/projects                      project list, optional status filter
/api/v1/projects/{id}                 one project summary
POST /api/v1/projects/{id}/generate   async resumable generation
/api/v1/queue                         queue summary
/api/v1/jobs                          job list
/api/v1/jobs/{id}                     durable job + event history
/api/v1/jobs/{id}/events              events after a sequence number
POST /api/v1/jobs/{id}/cancel         cooperative cancellation request
/docs                                 OpenAPI documentation
```

The legacy `omnivoice-project-studio --share` launcher remains available while the stable-hostname publishing layer is being built.

## Application service boundary

`StudioService` owns read operations. `StudioCommandService` owns write semantics. REST and future MCP tools use these services rather than importing Gradio callbacks.

```text
FastAPI route ─┐
               ├── StudioService / StudioCommandService
MCP tool ──────┘                   │
                                   ↓
                        project/status/queue modules
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

If the server/runtime stops while a job is `RUNNING` or `CANCEL_REQUESTED`, startup recovers it to `QUEUED`. Project generation handlers then rely on `section-status.json` to resume only unfinished sections.

### Idempotency

`StudioJobManager.submit(..., idempotency_key=...)` returns the existing job for the same key instead of duplicating work. REST exposes this through the `Idempotency-Key` header. This is essential for AI clients that may retry after a network timeout.

### Cooperative cancellation

The worker is never force-killed in the middle of model inference. Project generation calls `ctx.checkpoint()` before each section. A cancellation request that arrives while a section is being synthesized takes effect before the next section. If it arrives during the final section and that section finishes successfully, the job is complete rather than falsely marked cancelled.

## Async project generation

Submit a full project or selected sections:

```http
POST /api/v1/projects/my-project/generate
Idempotency-Key: agent-turn-42-my-project
Content-Type: application/json

{
  "voice_name": "Narrator",
  "voice_variant": "AUTO",
  "language": "en",
  "sections": ["S03", "S04"],
  "resume": true,
  "strict": false,
  "quality_preset": "BALANCED"
}
```

The request returns immediately:

```json
{
  "job_id": "job_abc123",
  "status": "queued",
  "location": "/api/v1/jobs/job_abc123",
  "idempotency_key": "agent-turn-42-my-project"
}
```

The handler renders section-by-section:

```text
S03
 ↓
section-status.json checkpoint
 ↓
S04
```

With `resume=true`, sections already complete according to the existing section checkpoint are skipped. If generated audio remains unverified, the job itself can finish successfully while its result reports `project_status=NEEDS_REVIEW`; transport/job success is not confused with narration quality approval.

Saved `studio.json` values are used when voice, variant, language or quality preset are omitted. The persisted `project_path` in a job is additionally constrained to a direct child of the Studio `projects/` directory.

## Next AI-native slice

The next layer adds Server-Sent Events so clients do not need to poll JSON repeatedly:

```text
GET /api/v1/jobs/{id}/stream
        ↓
queued
section.started
section.finished
project.finished
completed
```

After SSE is stable, MCP can expose task-oriented tools using the same job service without maintaining a second generation implementation.

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
5. [x] First write REST handler: resumable project/section generation returning `job_id`.
6. [ ] Additional write handlers: preview, queue, regenerate, merge.
7. [ ] SSE event stream.
8. [ ] MCP server using the same services/jobs.
9. [ ] Stable hostname / named tunnel deployment path.
10. [ ] API authentication/scopes.
11. [ ] Universal OmniVoice Skill.
12. [ ] ChatGPT, Claude and Antigravity adapters.
13. [ ] Optional persistent control plane and worker registry.
