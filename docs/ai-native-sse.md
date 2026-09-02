# AI-native live job streaming

OmniVoice Studio exposes durable Job Manager events as Server-Sent Events (SSE). This lets Gradio clients, REST clients, MCP adapters, and future AI agents follow long GPU jobs without polling `jobs.json` repeatedly.

## Endpoint

```text
GET /api/v1/jobs/{job_id}/stream
```

The stream uses standard SSE frames:

```text
id: 4
event: section.started
data: {"seq":4,"timestamp":"...","message":"Generating S02 (2/5).","progress":0.2,"data":{"section_id":"S02"}}

```

Normal generation can produce events such as:

```text
queued
started
project.started
section.started
section.finished
project.finished
completed
```

Failed and cancelled jobs terminate with `failed` or `cancelled`.

## Resume after disconnect

SSE event sequence numbers are durable because they are stored with the job in `<workspace>/jobs.json`.

A reconnecting client can send:

```http
Last-Event-ID: 7
```

or:

```text
GET /api/v1/jobs/{job_id}/stream?after=7
```

The server emits only events with a sequence greater than the cursor. If both are supplied, the greater cursor is used to avoid accidental replay.

## Heartbeats

If a running job produces no event for 15 seconds, the server sends an SSE comment:

```text
: keep-alive
```

This keeps reverse proxies and temporary Kaggle/Colab tunnels from treating an otherwise healthy long inference as an idle connection.

## Backpressure and GPU behavior

The stream never controls GPU execution. It observes the existing persistent single-worker Job Manager. Event consumers may disconnect at any time without cancelling the job.

The Job Manager provides `wait_for_events()` using its condition variable, so idle SSE clients do not busy-poll the filesystem.

## Terminal behavior

The stream closes after the durable terminal event has been emitted:

```text
completed
failed
cancelled
```

A client that reconnects after completion can still replay the stored event history and then receives a clean end-of-stream.

## Why this comes before MCP

MCP tools will submit durable jobs and can return a `job_id` immediately. The same event stream then provides progress to any protocol adapter without duplicating generation logic.

```text
ChatGPT / Claude / Antigravity
             |
            MCP
             |
      Studio Job Manager
          /       \
       REST       SSE
```

The next AI-native slice can therefore focus on task-oriented MCP tools rather than inventing another progress system.
