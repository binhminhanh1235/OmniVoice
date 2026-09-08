# OmniVoice Project Studio roadmap

Last status review: 2026-09-08.

This roadmap is the canonical status page for the production-oriented OmniVoice Studio fork. It distinguishes code already merged to `master`, work under review, experimental work, and future plans.

## Status legend

- **MERGED / VERIFIED**: on `master` and covered by the relevant regression boundary.
- **IN REVIEW**: implemented on a feature branch or PR but not yet production master.
- **EXPERIMENTAL**: useful research/prototype code that must not be enabled by assumption.
- **PLANNED**: accepted direction, not implemented yet.

## Current production baseline

At this snapshot:

```text
master:
dfed08b5d2b26298b2417a92f904a862e2f83590

tree:
b956f59dd25470c49857c21879f9a63f70d86a22
```

This baseline includes:

- English-first language selectors;
- leading conjunction narration safeguard;
- optional section-title narration;
- unified project-first workspace;
- benchmark framework;
- existing Project Studio, recovery, AI-native server, MCP, tunnel and auth foundations.

Persistent hosted-runtime caching is tracked separately as **IN REVIEW** until merged.

## P0 - Production Project Studio foundation

Status: **MERGED / VERIFIED**

- [x] Persistent Project model.
- [x] `S01`, `S02`, ... Markdown parser.
- [x] Project -> Section -> Beat -> Chunk hierarchy.
- [x] Separate section WAV files.
- [x] Per-chunk generation and verification.
- [x] Checkpoint/resume.
- [x] Crash-safe `section-status.json`.
- [x] Skip verified work after restart.
- [x] Regenerate one chunk only.
- [x] Render selected sections.
- [x] Merge verified sections into final output.
- [x] Persistent Voice Library / reusable `VoiceClonePrompt`.
- [x] Voice variants / Style Bank.
- [x] Preview before full render.
- [x] Text Doctor.
- [x] Voice Doctor.
- [x] Voice Stability Score.
- [x] Section Version History.
- [x] Multi-project queue.
- [x] Cooperative queue pause/recovery.
- [x] Project status filters.
- [x] Hardware detection and quality presets.
- [x] Advanced Settings.
- [x] Unified project-first workspace.
- [x] Language dropdowns with English first.
- [x] Optional `###` section-title narration.
- [x] Leading conjunction safeguard for fragile starts such as `Or`, `And`, and `But`.

### Production UX principle

The primary workflow remains:

```text
Script
  -> Voice
  -> Preview
  -> Render
  -> Review
  -> Export
```

Recovery, History, Quality, Advanced Settings, Queue and Storage support the same project rather than creating parallel workflows.

## P1 - Safe performance optimization

Status: **PARTLY MERGED / PARTLY PLANNED**

### Benchmark framework

Status: **MERGED / VERIFIED**

- [x] Reproducible raw `model.generate` benchmark.
- [x] RTF metrics.
- [x] generated audio duration.
- [x] model load time.
- [x] CUDA peak allocation when available.
- [x] CLI: `omnivoice-benchmark`.
- [x] benchmark regression coverage.

### Local-first Colab workspace

Status: **SAFE CANDIDATE**

Goal:

- use local Colab VM storage for active generation;
- restore/sync persistent project state through a persistence boundary;
- avoid Drive FUSE in the render hot path;
- preserve existing checkpoint/resume semantics.

Before production merge:

- [ ] benchmark local workspace vs direct Drive workspace;
- [ ] validate restore/sync after runtime restart;
- [ ] validate no project-state regression;
- [ ] document worst-case unsynced interval and recovery behavior.

### Lazy CPU ASR startup

Status: **SAFE CANDIDATE**

The core model already supports on-demand ASR loading when transcription is first required.

Planned production acceptance:

- [ ] compare Studio startup time before/after;
- [ ] verify first ASR request loads correctly;
- [ ] verify explicit CPU ASR behavior;
- [ ] preserve eager accelerator ASR placement where requested;
- [ ] run full Project Studio and long-form regression;
- [ ] confirm no verification quality change.

### Target-only inference

Status: **EXPERIMENTAL**

The `optimize` branch contains an experimental engine that projects audio logits only for target positions.

Current evidence is not sufficient for production enablement.

Required acceptance:

- [ ] real GPU before/after benchmark;
- [ ] same prompts/config/seeds where deterministic comparison is possible;
- [ ] output/projection equivalence at all used positions;
- [ ] real voice-clone TTS generation;
- [ ] ASR WER/similarity comparison;
- [ ] duration/pacing comparison;
- [ ] perceptual A/B listening;
- [ ] long-form project acceptance;
- [ ] CUDA memory comparison;
- [ ] no regression to training or stable inference APIs.

**Rule:** do not merge or enable target-only inference solely because the mathematical projection test passes.

## P2 - Persistent Colab/Kaggle startup caching

Status: **IN REVIEW**

Tracked implementation:

```text
PR #49
feat/persistent-hosted-runtime-cache
head 27cf233ebb93edd6ff3ad5c57045ec5637a32ffb
```

At the latest review checkpoint:

- Notebook JSON validation: PASS.
- Robust regression CI #300: PASS.

The feature is still classified as **IN REVIEW** until it is merged to `master`.

Acceptance scope:

- [x] dependency/wheel cache implementation.
- [x] pip cache implementation.
- [x] Hugging Face/model cache implementation.
- [x] Torch cache implementation.
- [x] Whisper cache implementation.
- [x] reusable workspace/cache metadata.
- [x] cache version/fingerprint.
- [x] invalidation path.
- [x] exact source-revision wheel path.
- [x] fast path.
- [x] cold-start fallback.
- [x] local SSD execution remains the generation hot path.
- [ ] merge to master after final review.
- [ ] verify post-merge exact-head CI.
- [ ] add a user-facing measured cold-start vs warm-start table from real Colab/Kaggle runs.

### Follow-up cache work

Status: **PLANNED**

- [ ] cache reusable verification/preprocessing metadata.
- [ ] avoid repeated work when script/reference/config fingerprint is unchanged.
- [ ] expose cache health/invalidated reason in Studio diagnostics.
- [ ] document cache size and cleanup strategy.

## P3 - AI-native Studio

Status: **FOUNDATION MERGED, COMMAND SURFACE PARTIAL**

The Gradio UI remains first-class. REST and MCP use shared service/job layers rather than reimplementing TTS.

### Application and server foundation

Status: **MERGED / VERIFIED**

- [x] protocol-neutral `StudioService`.
- [x] command service boundary.
- [x] unified FastAPI host.
- [x] Gradio mounted at `/ui`.
- [x] health/capabilities/hardware endpoints.
- [x] project/queue read APIs.
- [x] OpenAPI docs.

### Persistent Job Manager

Status: **MERGED / VERIFIED**

- [x] single-worker GPU job serialization.
- [x] persistent `jobs.json`.
- [x] durable event history.
- [x] idempotency keys.
- [x] cooperative cancellation.
- [x] restart recovery semantics.
- [x] async project generation.

### Write REST API

Status: **PARTIAL**

Merged:

- [x] resumable project/section generation returning `job_id`.
- [x] cooperative job cancellation.

Planned:

- [ ] preview job endpoint.
- [ ] queue mutation endpoints.
- [ ] regenerate chunk endpoint.
- [ ] merge/export endpoint.
- [ ] voice/diagnostic command endpoints where useful.
- [ ] stable command schema/versioning for external clients.

### SSE

Status: **MERGED / VERIFIED**

- [x] `GET /api/v1/jobs/{job_id}/stream`.
- [x] durable replay.
- [x] `Last-Event-ID` resume.
- [x] heartbeat.
- [x] terminal stream close.

### MCP

Status: **MERGED / VERIFIED**

Current task-oriented tools:

- [x] `studio_status`.
- [x] `list_projects`.
- [x] `inspect_project`.
- [x] `queue_status`.
- [x] `generate_project`.
- [x] `get_job`.
- [x] `cancel_job`.

Resources:

- [x] `omnivoice://projects/{project_id}`.
- [x] `omnivoice://queue`.

Planned:

- [ ] preview tool.
- [ ] regenerate tool.
- [ ] merge/export tool.
- [ ] explicit queue mutation tools after REST command contracts stabilize.

### Stable hostname / tunnel

Status: **MERGED / VERIFIED**

- [x] remotely-managed Cloudflare Tunnel support.
- [x] `--tunnel`.
- [x] `--public-url`.
- [x] stable `/ui`, `/api/v1`, `/mcp`.
- [x] tunnel token passed through a private temporary token file.
- [x] MCP host/origin configuration from public URL.

### Authentication

Status: **MERGED / VERIFIED**

Machine/API auth:

- [x] bearer token.
- [x] `omnivoice:read`.
- [x] `omnivoice:generate`.
- [x] `omnivoice:queue`.
- [x] `omnivoice:mcp`.
- [x] `omnivoice:admin`.
- [x] constant-time token comparison.
- [x] 401 vs 403 semantics.

UI protection:

- [x] username/password configuration.
- [x] fail-closed public deployment checks.
- [x] explicit trusted external UI auth boundary.

### AI client integration

Status: **PLANNED**

- [ ] Universal OmniVoice Skill describing safe production workflows.
- [ ] ChatGPT integration example.
- [ ] Claude Code integration example.
- [ ] generic MCP client example.
- [ ] Antigravity/other agent example where applicable.
- [ ] sample idempotent long-running render workflow.

### Optional control plane

Status: **PLANNED**

Goal:

```text
AI clients
    |
stable control endpoint
    |
worker registry / routing
    |
ephemeral Colab/Kaggle workers
```

Planned:

- [ ] worker registration.
- [ ] heartbeat/offline state.
- [ ] reconnect without client URL changes.
- [ ] job assignment/recovery contract.
- [ ] authentication between control plane and workers.

## P4 - Verification efficiency and voice intelligence

Status: **PLANNED**

### Verification cache

- [ ] fingerprint text/reference/settings.
- [ ] reuse safe preprocessing metadata.
- [ ] invalidate on meaningful input/config changes.

### Cascade verifier

- [ ] cheap verifier first.
- [ ] stronger verifier only for borderline chunks.
- [ ] benchmark accuracy vs memory/latency before enablement.

### Same-language reference selection

- [ ] when one voice has multiple language variants, prefer same-language reference.
- [ ] deterministic fallback when exact language variant is unavailable.
- [ ] preserve explicit user-selected variant.

## P5 - Authoring and production tools

Status: **PLANNED**

- [ ] richer directive DSL: `PAUSE`, `SLOW`, `FAST`, `PITCH`, `VOICE`, combined tags.
- [ ] line-level style overrides.
- [ ] phrase-level style overrides.
- [ ] timeline editor.
- [ ] silence editor.
- [ ] WAV export profiles.
- [ ] MP3 export profiles.
- [ ] unattended project CLI runner.
- [ ] production manifest/export bundle for downstream editors.

## P6 - Upstream drift and compatibility protection

Status: **NO CURRENT UPSTREAM DRIFT, GUARD PLANNED**

Latest checked upstream:

```text
k2-fsa/OmniVoice master:
08be0b4ccbac3e13e374e86fbfead4b4cac343e2
```

At the review checkpoint, that commit is also the fork merge-base:

```text
fork ahead: 348 commits
fork behind: 0 commits
```

Therefore there is no useful upstream delta to merge right now.

Planned guard:

- [ ] CI/report job that records upstream HEAD and merge-base.
- [ ] fail or warn when fork becomes behind upstream.
- [ ] classify upstream changes by model/tokenizer/inference/training/dependency/docs.
- [ ] require regression protection before integrating risky upstream changes.
- [ ] maintain a compatibility note for each upstream sync.
- [ ] never blindly merge upstream master into the production fork.

## Next production order

1. Finish review and merge persistent hosted-runtime caching.
2. Re-check post-merge master CI and real warm/cold hosted-runtime measurements.
3. Extract and validate lazy CPU ASR startup as a separate safe optimization.
4. Validate local-first Colab workspace with measured I/O/startup improvement.
5. Update all AI-native docs to the actual merged Job Manager/SSE/MCP/tunnel/auth state.
6. Add upstream drift guard.
7. Add missing write REST/MCP commands.
8. Add Universal OmniVoice Skill and agent examples.
9. Continue verification/cache intelligence.
10. Evaluate target-only inference only after real quality acceptance.

## Architectural rules

### Automatic acceleration must not change truthfulness

A faster path is accepted only when it preserves output/quality semantics or has an explicit documented trade-off.

### Remote persistence is not the render hot path

Hosted runtimes should generate on local SSD, then sync/export through a persistence boundary.

### Long-running commands return durable job IDs

REST/MCP should not keep one request/tool call open for an entire long render when the Job Manager can own the work.

### Script directives are model-agnostic intents

```text
[WARM]
   -> generic style intent
   -> style resolver
      -> matching Voice Library variant when available
      -> documented native OmniVoice attribute when supported
      -> conservative delivery fallback
```

### Experimental inference stays isolated

Benchmark and unit equivalence are necessary but not sufficient. Real TTS quality acceptance is required before production enablement.
