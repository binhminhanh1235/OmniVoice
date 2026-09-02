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
                    Project / Voice / Queue
                               │
                         OmniVoice Core
```

The Gradio UI remains supported. It is mounted under the same FastAPI process instead of being the only way to reach the application.

## v1 server

Start the unified server:

```bash
omnivoice-studio serve \
  --workspace /kaggle/working/OmniVoiceStudio \
  --host 0.0.0.0 \
  --port 8000
```

Current endpoints:

```text
/ui                       Gradio web UI
/health                   lightweight health check
/api/v1/capabilities      runtime and feature discovery
/api/v1/hardware          GPU / VRAM / quality recommendation
/api/v1/projects          project list, optional status filter
/api/v1/projects/{id}     one project summary
/api/v1/queue             queue summary
/docs                     OpenAPI documentation
```

The legacy `omnivoice-project-studio --share` launcher remains available while the stable-hostname publishing layer is being built.

## Application service boundary

`StudioService` is protocol-neutral. REST and future MCP tools call this layer rather than importing Gradio callbacks.

```text
FastAPI route ─┐
               ├── StudioService ── project/status/queue modules
MCP tool ──────┘
```

This prevents separate Gradio, REST and MCP implementations from drifting apart.

## Long-running GPU work

Generation is intentionally not exposed as a synchronous REST write in this first slice. The next write-capable layer will add a single-GPU job manager:

```text
POST generate
     ↓
job_id
     ↓
GPU worker = 1
     ↓
section/chunk checkpoint events
```

The API will then expose job status and an event stream instead of keeping an HTTP request open during a long render.

## Stable hostname plan

AI clients should eventually configure one permanent endpoint such as:

```text
https://omnivoice.example.com/mcp
```

They must not point directly at a random `*.gradio.live` session URL.

The first publishing design is:

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

1. Application Service layer.
2. Unified FastAPI + mounted Gradio server.
3. Read-only REST/OpenAPI endpoints.
4. Async single-GPU Job Manager + event stream.
5. Write REST endpoints.
6. MCP server using the same services/jobs.
7. Stable hostname / named tunnel deployment path.
8. Universal OmniVoice Skill.
9. ChatGPT, Claude and Antigravity adapters.
10. Optional persistent control plane and worker registry.
