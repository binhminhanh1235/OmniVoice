# OmniVoice Project Studio roadmap

This roadmap prioritizes reliable long-form narration on hosted local GPU/SSD, then an AI-native service layer while keeping the Gradio web UI.

## Status legend

- **MERGED**: implementation and regression coverage are on the production line.
- **PARTIAL**: a production-safe subset is merged, but the listed surface is not complete.
- **EXPERIMENTAL**: code may exist outside the production line and is not enabled by default.
- **TODO**: not implemented yet.

## P0 — usable project workflow

- [x] Persistent Project model
- [x] `S01`, `S02`, ... Markdown parser
- [x] Directive stripping (`WARM`, `SOFT`, `EMPHASIZE`, `NORMAL`)
- [x] Project -> Section -> Beat -> Chunk hierarchy
- [x] Separate section WAV files
- [x] Robust per-chunk verification
- [x] Checkpoint / resume
- [x] Persistent `section-status.json` with crash-safe section resume
- [x] Skip completed sections after reload; resume only incomplete sections
- [x] Regenerate one chunk only
- [x] Merge verified sections into `full.wav`
- [x] Persistent Voice Library / cached `VoiceClonePrompt`
- [x] Simple Gradio Project Studio
- [x] Section/chunk status table
- [x] Live per-section generation status
- [x] Colab Project Studio launcher
- [x] Persistent multi-project queue with continuous section-by-section rendering
- [x] Queue crash recovery: completed projects/sections are skipped after runtime restart when the workspace still exists
- [x] Cooperative pause after current section and continue-on-project-error policy
- [x] Optional auto-merge per queued project
- [x] Project-level render status derived from `section-status.json`
- [x] Queue Project Browser filtered by `PENDING`, `GENERATING`, `NEEDS_REVIEW`, `FAILED`, `DONE`
- [x] Default queue filter hides `DONE` and shows `PENDING + GENERATING`
- [x] Hide projects already represented in the queue
- [x] Bulk-add all filtered projects using each project's saved Studio settings

## P1 — narration quality and recovery

- [x] Voice Style Bank: `DEFAULT`, `WARM`, `SOFT`, `PRAYER`, optional `EMPHASIZE` variants
- [x] Style Resolver with deterministic fallback
- [x] Preview opening / middle / ending before full rendering
- [x] Adaptive retry by failure reason: repetition, omission, pacing, text mismatch
- [x] Pacing anomaly detector with global fallback and optional Whisper word timestamps
- [x] Text Doctor: safe HTML/Unicode cleanup, diff, semantic review hints
- [x] Voice Doctor: reference duration, level, silence, clipping, DC offset and noise/dynamic checks
- [x] One-upload Voice Doctor -> Save Voice flow
- [x] Voice Stability Score from three real clone probes with ASR/pacing checks
- [x] Persistent Section Version History with play / snapshot / restore
- [x] Automatic snapshots before chunk regeneration and forced section rerender

## P2 — efficiency and lower-friction setup

1. [x] Auto Best Reference Segment: rank clean 3–10 second windows from long recordings, listen before selection, optional ASR transcript suggestion.
2. [x] Hardware detection and quality presets (`SAFE`, `BALANCED`, `FAST`) without exposing a wall of generation parameters.
   - hardware summary: CUDA, GPU, VRAM, compute capability, recommended ASR device;
   - T4 / 16 GB recommendation: `BALANCED` + ASR on CPU;
   - `SAFE`: 32 steps, 3 retries, adaptive retry + pacing guard + ASR verification;
   - `BALANCED`: 28 steps, 2 retries, adaptive retry + pacing guard + ASR verification;
   - `FAST`: 24 steps, 1 retry, no adaptive repair/pacing timestamps, but ASR text verification remains enabled;
   - workspace default in `hardware-quality.json`, optional per-project override in `studio.json`.
3. [x] Kaggle local execution workspace.
   - automatic Kaggle detection;
   - writable execution root: `/kaggle/working/OmniVoiceStudio`;
   - `/kaggle/input` treated as read-only source material only;
   - no Google Drive/rclone/remote persistence in this phase;
   - dedicated Kaggle notebook;
   - execution and future persistence kept as separate architectural layers.
4. [x] **MERGED** Optional project/data export and Google Drive sync through the separate Data Management/rclone boundary.
5. [x] **MERGED** Persistent hosted-runtime startup cache for pip/wheels, Hugging Face/model assets, Torch and Whisper/ASR resources, with cache versioning, compatibility invalidation, local-SSD restore, Colab Drive persistence, and Kaggle Dataset cache export/restore.
6. [ ] **TODO** Cache reusable verification/preprocessing results beyond startup/model resources.
7. [ ] **TODO** Cascade verification: cheap verifier first, stronger verifier only for borderline chunks, after benchmarking accuracy and memory cost.
8. [ ] **TODO** Same-language reference selection when one voice has multiple language variants.
9. [ ] **EXPERIMENTAL** Decoder acceleration candidates such as target-only projection, FlashInfer or CUDA graphs. None may become default without measured speed/memory gains plus output and TTS-quality equivalence.

## P2.5 — AI-native OmniVoice while keeping Web UI

The Gradio UI remains a first-class interface. AI-native clients use the same application services rather than duplicating generation logic.

1. [x] **MERGED** Protocol-neutral `StudioService` application layer for runtime, projects, queue and capabilities.
2. [x] **MERGED** Unified FastAPI server with Gradio mounted at `/ui`.
3. [x] **MERGED** Read-only REST/OpenAPI foundation: `/health`, `/api/v1/capabilities`, `/api/v1/hardware`, projects and queue summaries.
4. [x] **MERGED** Persistent single-GPU `StudioJobManager`: FIFO serialization, durable `jobs.json`, idempotency keys, restart recovery and cooperative cancellation.
5. [~] **PARTIAL** Write REST API. Merged today: async resumable `POST /api/v1/projects/{id}/generate` returning `job_id`, plus cooperative `POST /api/v1/jobs/{id}/cancel`. Still TODO: preview, queue mutation, regenerate and merge write handlers.
6. [x] **MERGED** Durable Server-Sent Events at `/api/v1/jobs/{id}/stream`, including event replay, `Last-Event-ID` resume, heartbeats and terminal close behavior.
7. [x] **MERGED** Streamable HTTP MCP mounted at `/mcp`, sharing `StudioService` and `StudioJobManager`. Initial tools cover status, projects, queue, generate, job inspection and cancel.
8. [x] **MERGED** Stable-hostname publishing through a remotely-managed Cloudflare named tunnel. Ephemeral Kaggle/Colab connectors can reconnect the same hostname.
9. [x] **MERGED** Machine bearer authentication and scopes independent from optional Gradio Basic auth. Public deployments fail closed unless explicitly overridden for insecure testing.
10. [ ] **TODO** Universal OmniVoice Skill describing safe production workflows and quality rules.
11. [ ] **TODO** Thin adapters/examples for ChatGPT, Claude Code and Antigravity.
12. [ ] **TODO** Optional persistent control plane + worker registry for graceful offline/reconnect handling without changing client configuration.

## P3 — authoring and production tools

1. [ ] Rich directive DSL (`PAUSE`, `SLOW`, `FAST`, `PITCH`, `VOICE`, combined tags).
2. [ ] Per-line and phrase-level style overrides.
3. [ ] Timeline and silence editor.
4. [ ] WAV/MP3 export profiles.
5. [ ] Project CLI runner for unattended local workflows.

## Next priority

The AI-native foundation is now production-merged. The next priority is to complete the **remaining write surfaces** without duplicating generation logic:

1. preview as a durable job;
2. queue mutation through the shared command/job layer;
3. chunk/section regenerate as a durable job;
4. merge/export as a durable job;
5. Universal OmniVoice Skill and thin client examples after the write contract is complete.

Current production topology:

```text
                       OmniVoice Studio
                              |
             +----------------+----------------+
             |                |                |
           /ui             /api/v1           /mcp
         Gradio              REST        Streamable HTTP
             |                |                |
             +-------- Application Services --+
                              |
                 Persistent StudioJobManager
                              |
                    Project / Queue / Voice
                              |
                         OmniVoice Core
```

Public hosted deployments can use a stable Cloudflare named-tunnel hostname. Machine-facing REST/MCP requests use bearer scopes; public Gradio can use Basic auth or a trusted external access layer.

The target-only projection engine remains **EXPERIMENTAL** outside the production line. Projection-unit equivalence alone is not sufficient to enable it: a real baseline-vs-candidate TTS benchmark and quality/equivalence acceptance are still required.

## Architectural rule

Script directives are model-agnostic intents. Do not expose unsupported OmniVoice instructions directly.

```text
[WARM]
   -> generic style intent
   -> style resolver
      -> matching Voice Library variant if available
      -> documented native OmniVoice instruct when supported
      -> conservative pacing/pause fallback
```

This keeps saved scripts portable to future TTS backends.
