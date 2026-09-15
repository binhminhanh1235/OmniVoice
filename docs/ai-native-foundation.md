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

The Gradio UI remains first-class. REST, CLI and MCP reuse the same service/job layers rather than duplicating generation logic.

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
/api/v1/audio/generate                standalone async audio generation
/api/v1/audio/preview                 direct/project non-destructive previews
/api/v1/projects                      project list
/api/v1/projects/{id}                 one project summary
POST /api/v1/projects/{id}/generate   async resumable generation
/api/v1/artifacts                     generated WAV artifact discovery
/api/v1/queue                         queue summary
/api/v1/jobs                          job list
/api/v1/jobs/{id}                     durable job + event history
/api/v1/jobs/{id}/wait                efficient condition-backed wait
/api/v1/jobs/{id}/events              durable events after a cursor
/api/v1/jobs/{id}/stream              SSE event stream
POST /api/v1/jobs/{id}/cancel         cooperative cancellation
/mcp                                  Streamable HTTP MCP
/docs                                 OpenAPI documentation
```

Targeted regeneration is also exposed for one section or one chunk through REST, MCP and the `omnivoice` umbrella CLI.

## Application service boundary

`StudioService` owns read operations. `StudioCommandService` owns generation command semantics. REST and MCP submit durable work through `StudioJobManager`.

```text
FastAPI route ----+
                  +--> StudioService / StudioCommandService
MCP tool ---------+                  |
CLI -> REST ------+                  v
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

State and bounded event history are stored in `<workspace>/jobs.json`. If a runtime stops while work is active, Job Manager recovery and Project Studio section checkpoints provide the durable resume boundary.

### Idempotency

`StudioJobManager.submit(..., idempotency_key=...)` returns the existing job for a repeated key instead of duplicating work. REST exposes this through the `Idempotency-Key` header.

### Cooperative cancellation

Cancellation never force-kills model inference in the middle of a section/chunk. It becomes effective at a safe checkpoint.

## Priority AI-native generation contract

Nine high-value tools form the small agent-facing control plane:

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

All generation mutations return a durable `job_id`. The preferred lifecycle is:

```text
command -> job_id -> wait_job -> list_artifacts
```

`wait_job` uses the same condition/event mechanism as SSE instead of repeated polling. `list_artifacts` derives audio metadata from durable workspace files and covers standalone audio, previews, chunks, beats, sections and merged project audio.

See [ai-native-mcp.md](ai-native-mcp.md).

## CLI

A remote-first umbrella CLI mirrors the same contracts:

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

Use `OMNIVOICE_STUDIO_URL` for remote Colab/Kaggle/hosted Studio and `OMNIVOICE_API_TOKEN` when bearer authentication is enabled.

## SSE progress

Live progress remains available at `GET /api/v1/jobs/{job_id}/stream`, with durable event replay, `Last-Event-ID`, heartbeats and clean terminal closure. See [ai-native-sse.md](ai-native-sse.md).

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

The Gradio UI can use username/password protection or an explicitly trusted external UI auth boundary. Public deployment fails closed unless the required authentication boundary is configured, unless an explicit insecure test override is requested.

## Current development sequence

Implemented foundation:

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
11. [x] Standalone `generate_audio` fast path.
12. [x] Condition-backed `wait_job`.
13. [x] Generated audio artifact discovery.
14. [x] Non-destructive `preview_audio`.
15. [x] Targeted section/chunk regeneration tools.
16. [x] Umbrella CLI parity for the nine priority tools.

Planned next:

17. [ ] artifact download endpoint + HTTP Range/resume.
18. [ ] merge/export API/tool and production package.
19. [ ] queue mutation API/tools.
20. [ ] Universal OmniVoice Skill.
21. [ ] ChatGPT / Claude Code / generic MCP examples.
22. [ ] optional persistent control plane + worker registry.

The canonical broader status remains in [project-studio-roadmap.md](project-studio-roadmap.md).
