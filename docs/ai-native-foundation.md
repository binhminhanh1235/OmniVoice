# OmniVoice Studio AI-native foundation

OmniVoice Studio is one production engine with multiple interfaces:

```text
                         OmniVoice Studio
                               |
              +----------------+----------------+
              |                |                |
            /ui             /api/v1           /mcp
              |                |                |
           Gradio             REST            AI clients
              |                |                |
              +-------- Application Layer -----+
                               |
                      Persistent Job Manager
                               |
                    Project / Voice / Queue
                               |
                         OmniVoice Core
```

The Gradio UI remains first-class. REST and MCP reuse the same service/job layers rather than duplicating generation logic.

## Unified server

```bash
omnivoice-studio serve \
  --workspace /kaggle/working/OmniVoiceStudio \
  --host 0.0.0.0 \
  --port 8000
```

Current surfaces:

```text
/ui                                   Gradio web UI
/health                               lightweight health check
/api/v1/capabilities                  runtime and feature discovery
/api/v1/hardware                      GPU / VRAM / quality recommendation
/api/v1/projects                      project list
/api/v1/projects/{id}                 one project summary
POST /api/v1/projects/{id}/generate   async resumable generation
/api/v1/queue                         queue summary
/api/v1/jobs                          job list
/api/v1/jobs/{id}                     durable job + event history
/api/v1/jobs/{id}/events              durable events after a cursor
/api/v1/jobs/{id}/stream              SSE event stream
POST /api/v1/jobs/{id}/cancel         cooperative cancellation
/mcp                                  Streamable HTTP MCP
/docs                                 OpenAPI documentation
```

## Application service boundary

`StudioService` owns read operations. `StudioCommandService` owns generation command semantics. REST and MCP submit durable work through `StudioJobManager`.

```text
FastAPI route ----+
                  +--> StudioService / StudioCommandService
MCP tool ---------+                  |
                                     v
                              StudioJobManager
                                     |
                          project/status/queue modules
```

## Persistent single-GPU Job Manager

GPU-bound jobs are serialized through one worker so long-running tasks do not compete for the same GPU.

```text
QUEUED
  |
RUNNING
  +--> COMPLETED
  +--> FAILED
  +--> CANCEL_REQUESTED -> safe checkpoint -> CANCELLED
```

State and bounded event history are stored in:

```text
<workspace>/jobs.json
```

If a runtime stops while work is active, Job Manager recovery and Project Studio section checkpoints provide the durable resume boundary.

### Idempotency

`StudioJobManager.submit(..., idempotency_key=...)` returns the existing job for a repeated key instead of duplicating work.

REST exposes this through the `Idempotency-Key` header.

### Cooperative cancellation

Cancellation never force-kills model inference in the middle of a section. It becomes effective at a safe checkpoint.

## Async project generation

Example:

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

The request returns a durable job immediately.

With `resume=true`, completed sections are skipped according to persistent section state.

## SSE progress

Live progress is implemented at:

```text
GET /api/v1/jobs/{job_id}/stream
```

The stream supports durable event replay, `Last-Event-ID`, heartbeats and clean terminal closure.

See [ai-native-sse.md](ai-native-sse.md).

## MCP

MCP is implemented and mounted at:

```text
/mcp
```

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

Generation returns a `job_id` rather than holding one MCP call open for the full render.

See [ai-native-mcp.md](ai-native-mcp.md).

## Stable hostname

A remotely-managed Cloudflare Tunnel can expose a permanent hostname while Colab/Kaggle workers remain ephemeral.

```text
ChatGPT / Claude Code / other clients
                |
       stable public hostname
                |
      Cloudflare named tunnel
                |
       Colab / Kaggle :8000
                |
          OmniVoice Studio
```

The named-tunnel lifecycle and public URL support are implemented.

See [stable-tunnel.md](stable-tunnel.md).

## Authentication

Machine-facing REST/MCP traffic can be protected with a bearer token and scopes:

```text
omnivoice:read
omnivoice:generate
omnivoice:queue
omnivoice:mcp
omnivoice:admin
```

The Gradio UI can use username/password protection or an explicitly trusted external UI auth boundary.

Public deployment fails closed unless the required authentication boundary is configured, unless an explicit insecure test override is requested.

## Current development sequence

Merged:

1. [x] Application Service layer.
2. [x] Unified FastAPI + Gradio server.
3. [x] Read-only REST/OpenAPI endpoints.
4. [x] Persistent single-GPU Job Manager.
5. [x] Resumable async project generation.
6. [x] SSE event stream.
7. [x] MCP server.
8. [x] Stable named-tunnel path.
9. [x] API bearer authentication/scopes.
10. [x] UI authentication boundary.

Planned:

11. [ ] preview write API/tool.
12. [ ] queue mutation API/tools.
13. [ ] regenerate chunk API/tool.
14. [ ] merge/export API/tool.
15. [ ] Universal OmniVoice Skill.
16. [ ] ChatGPT / Claude Code / generic MCP examples.
17. [ ] optional persistent control plane + worker registry.

The canonical status is maintained in [project-studio-roadmap.md](project-studio-roadmap.md).
