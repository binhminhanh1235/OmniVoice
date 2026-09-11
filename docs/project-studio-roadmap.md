# OmniVoice Project Studio roadmap

Last status review: 2026-09-11.

This roadmap is the canonical status page for the production-oriented OmniVoice Studio fork. It distinguishes code already merged to `master`, experimental work, and future plans.

## Status legend

- **MERGED / VERIFIED**: on `master` and covered by the relevant regression boundary.
- **IN REVIEW**: implemented on a feature branch or PR but not yet production master.
- **EXPERIMENTAL**: research/prototype code that must not be enabled by assumption.
- **PLANNED**: accepted direction, not implemented yet.

## Current production baseline

Current verified `master` after Lazy CPU ASR Startup:

```text
master / squash merge:
b8cdb00fd07140e0f785991e5bfa5fac9486638b

tree:
14cedb7a40edcaec4a23e53627af6f145a502628
```

This baseline includes:

- robust Project Studio and recovery foundations;
- unified project-first workspace;
- English-first language selectors;
- leading conjunction narration safeguard;
- optional section-title narration;
- benchmark framework;
- persistent Colab/Kaggle startup caching;
- Lazy CPU ASR Startup;
- AI-native server, Job Manager, REST/SSE/MCP, tunnel and auth foundations.

## P0 - Production Project Studio foundation

Status: **MERGED / VERIFIED**

- [x] Persistent Project model.
- [x] `S01`, `S02`, ... Markdown parser.
- [x] Project -> Section -> Beat -> Chunk hierarchy.
- [x] Separate section WAV files.
- [x] Per-chunk generation and verification.
- [x] Checkpoint/resume.
- [x] Crash-safe section/chunk status.
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

### Lazy CPU ASR Startup

Status: **MERGED / VERIFIED**

Final implementation and merge evidence:

```text
PR #51
branch: feat/lazy-cpu-asr-startup
final feature head: a75326c34313f9aa440e70df8d6d64480e07f536
final feature tree: 14cedb7a40edcaec4a23e53627af6f145a502628

squash merge SHA: b8cdb00fd07140e0f785991e5bfa5fac9486638b
squash merge tree: 14cedb7a40edcaec4a23e53627af6f145a502628
```

Exact-head pre-merge CI at `a75326c34313f9aa440e70df8d6d64480e07f536`:

- Lazy ASR startup safety #1 / run `34613754527`: PASS.
- Unified Project Workspace tests #15 / run `34613754191`: PASS.
- Robust long-form/project #322 / run `34613754423`: PASS.

Post-merge exact-SHA CI at `b8cdb00fd07140e0f785991e5bfa5fac9486638b`:

- Lazy ASR startup safety #2 / run `34614167021`: PASS.
- Robust long-form/project #323 / run `34614167003`: PASS.

Acceptance scope:

- [x] CPU ASR is not constructed during Studio/server startup.
- [x] first real transcription/verification initializes ASR.
- [x] one model-scoped lock protects first initialization.
- [x] concurrent first-use initializes exactly once.
- [x] successful ASR pipeline is reused.
- [x] failed first initialization does not publish a poisoned partial state.
- [x] later request can retry after failed initialization.
- [x] explicit accelerator ASR placement remains eager.
- [x] direct Voice Doctor transcription remains functional through the lazy gate.
- [x] REST/MCP/Gradio continue to share the same model/request path.
- [x] fake-loader/call-count tests avoid real ASR model downloads in CI.
- [x] full robust/project regression passed before and after merge.
- [x] verification quality thresholds/semantics are unchanged.

No synthetic startup-speed claim is recorded. Deterministic CI proves deferred CPU loader call-count and concurrency/retry safety; hosted timing remains a separate real-runtime measurement.

### Local-first Colab workspace

Status: **SAFE CANDIDATE**

Goal:

- use local Colab VM storage for active generation;
- restore/sync persistent project state through a persistence boundary;
- avoid Drive FUSE in the render hot path;
- preserve checkpoint/resume semantics.

Before promotion to a measured optimization claim:

- [ ] benchmark local workspace vs direct Drive workspace on a real Colab runtime;
- [ ] validate restore/sync after runtime restart;
- [ ] validate no project-state regression;
- [ ] document worst-case unsynced interval and recovery behavior.

The production notebook already uses local-first architecture. The remaining item is measured external-runtime evidence, not a code-path enablement blocker.

### Target-only inference

Status: **EXPERIMENTAL**

The optimization branch contains an experimental engine that projects audio logits only for target positions. It remains outside production master behavior.

Required acceptance before production enablement:

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

**Rule:** do not merge or enable target-only inference solely because a mathematical projection test passes.

## P2 - Persistent Colab/Kaggle startup caching

Status: **MERGED / VERIFIED**

Final implementation and merge evidence:

```text
PR #49
branch: feat/persistent-hosted-runtime-cache
final PR head: a74b1ba60ba0558bba4d444ce012ad04a676fb75
final PR head tree: cbbb7397b2a99b7fc922f1472096863427757d4a

squash merge SHA: d75d772b85332b40b66eb22f35d5c96ff56b2081
squash merge tree: bb6d2e0e185dbf50cf7555a8032833fc3484fe62
```

Exact-head pre-merge CI:

- Hosted runtime cache safety #14 / run `34607378458`: PASS.
- Notebook JSON validation #27 / run `34607378477`: PASS.
- Robust long-form/project #317 / run `34607378410`: PASS.

Post-merge exact-SHA CI:

- Hosted runtime cache safety #15 / run `34607761811`: PASS.
- Notebook JSON validation #28 / run `34607761677`: PASS.
- Robust long-form/project #318 / run `34607761685`: PASS.

Acceptance scope:

- [x] dependency/wheel cache.
- [x] pip cache.
- [x] Hugging Face/model cache.
- [x] Torch cache.
- [x] Whisper cache.
- [x] workspace/cache metadata.
- [x] cache version/fingerprint.
- [x] invalidation path.
- [x] exact source-revision wheel path.
- [x] exact source wheel integrity: filename, size, SHA-256 and ZIP integrity.
- [x] exact model/ASR revision fingerprinting/invalidation.
- [x] interrupted/partial cache state rejection.
- [x] missing/truncated/corrupt cache cold fallback.
- [x] fast path.
- [x] local SSD remains generation hot path.
- [x] exact-head and exact-post-merge CI.

Real Colab/Kaggle timing remains external-runtime evidence. No local CI timing is treated as a hosted speed benchmark.

For real hosted evidence preserve one genuine cold and warm `startup-cache-evidence.json` pair and run:

```bash
python scripts/hosted_cache_acceptance.py cold.json warm.json
```

The checker requires the same exact package SHA, warm fast-path flags, numeric timings and a faster warm bootstrap.

- [ ] add a measured Colab/Kaggle cold-vs-warm table when real external-runtime evidence is collected.

### Follow-up cache work

Status: **PLANNED**

- [ ] cache reusable verification/preprocessing metadata.
- [ ] avoid repeated work when script/reference/config fingerprint is unchanged.
- [ ] expose cache health/invalidated reason in Studio diagnostics.
- [ ] document cache size and cleanup strategy.

## P3 - AI-native Studio

Status: **FOUNDATION MERGED, COMMAND SURFACE PARTIAL**

### Application/server foundation

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

- [x] single-worker GPU serialization.
- [x] persistent jobs state.
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

- [x] job stream endpoint.
- [x] durable replay.
- [x] `Last-Event-ID` resume.
- [x] heartbeat.
- [x] terminal stream close.

### MCP

Status: **MERGED / VERIFIED**

Current tools:

- [x] `studio_status`.
- [x] `list_projects`.
- [x] `inspect_project`.
- [x] `queue_status`.
- [x] `generate_project`.
- [x] `get_job`.
- [x] `cancel_job`.

Planned:

- [ ] preview tool.
- [ ] regenerate tool.
- [ ] merge/export tool.
- [ ] queue mutation tools after REST command contracts stabilize.

### Stable hostname / tunnel

Status: **MERGED / VERIFIED**

- [x] remotely managed Cloudflare Tunnel support.
- [x] stable `/ui`, `/api/v1`, `/mcp`, `/health` hostname.
- [x] tunnel token kept out of raw child-process command line.
- [x] MCP host/origin configuration from public URL.

### Authentication

Status: **MERGED / VERIFIED**

- [x] bearer token.
- [x] read/generate/queue/mcp/admin scopes.
- [x] constant-time token comparison.
- [x] 401 vs 403 semantics.
- [x] optional UI username/password.
- [x] fail-closed public deployment checks.

### AI client integration

Status: **PLANNED**

- [ ] Universal OmniVoice Skill describing safe production workflows.
- [ ] ChatGPT integration example.
- [ ] Claude Code integration example.
- [ ] generic MCP client example.
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
- [ ] worker authentication.

## P4 - Verification efficiency and voice intelligence

Status: **PLANNED**

### Verification cache

- [ ] fingerprint text/reference/settings.
- [ ] reuse safe preprocessing metadata.
- [ ] invalidate on meaningful input/config changes.

### Cascade verifier

- [ ] cheap verifier first.
- [ ] stronger verifier only for borderline chunks.
- [ ] benchmark quality vs latency/memory before enablement.

### Same-language reference selection

- [ ] prefer same-language reference when a voice has multiple language variants.
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

Status: **NO CURRENT UPSTREAM DRIFT AT LAST REVIEW, GUARD PLANNED**

Last checked upstream checkpoint:

```text
k2-fsa/OmniVoice master:
08be0b4ccbac3e13e374e86fbfead4b4cac343e2
```

At that review checkpoint the fork was ahead and not behind.

Planned guard:

- [ ] CI/report job records upstream HEAD and merge-base.
- [ ] warn/fail when fork becomes behind upstream.
- [ ] classify upstream changes by model/tokenizer/inference/training/dependency/docs.
- [ ] require regression protection before integrating risky changes.
- [ ] maintain compatibility notes for each upstream sync.
- [ ] never blindly merge upstream master into production fork.

## Next production order

1. Collect real Colab/Kaggle cold/warm startup-cache evidence using the exact-revision acceptance workflow.
2. Validate local-first Colab workspace with measured I/O/startup evidence and restart recovery.
3. Add upstream drift guard automation.
4. Add missing write REST/MCP commands.
5. Add Universal OmniVoice Skill and agent integration examples.
6. Continue verification/cache intelligence.
7. Improve authoring/export production tooling.
8. Evaluate target-only inference only after separate real quality and GPU acceptance.

## Architectural rules

### Automatic acceleration must not change truthfulness

A faster path is accepted only when it preserves output/quality semantics or has an explicit documented trade-off.

### Remote persistence is not the render hot path

Hosted runtimes generate on local SSD, then sync/export through a persistence boundary.

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