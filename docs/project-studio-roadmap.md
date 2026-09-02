# OmniVoice Project Studio roadmap

This roadmap prioritizes reliable long-form narration on Google Colab first, then speed and production convenience.

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
- [x] Queue crash recovery: completed projects/sections are skipped after Colab restart
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
2. [x] Colab hardware detection and quality presets (`SAFE`, `BALANCED`, `FAST`) without exposing a wall of generation parameters.
   - hardware summary: CUDA, GPU, VRAM, compute capability, recommended ASR device;
   - T4 / 16 GB recommendation: `BALANCED` + ASR on CPU;
   - `SAFE`: 32 steps, 3 retries, adaptive retry + pacing guard + ASR verification;
   - `BALANCED`: 28 steps, 2 retries, adaptive retry + pacing guard + ASR verification;
   - `FAST`: 24 steps, 1 retry, no adaptive repair/pacing timestamps, but ASR text verification remains enabled;
   - workspace default in `hardware-quality.json`, optional per-project override in `studio.json`.
3. [ ] Cache reusable verification/preprocessing metadata and avoid repeated ASR/setup work.
4. [ ] Cascade verification: cheap verifier first, stronger verifier only for borderline chunks, after benchmarking accuracy and memory cost.
5. [ ] Same-language reference selection when one voice has multiple language variants.
6. [ ] Benchmark acceleration options such as FlashInfer/CUDA graphs before enabling them by default.

## P3 — authoring and production tools

1. [ ] Rich directive DSL (`PAUSE`, `SLOW`, `FAST`, `PITCH`, `VOICE`, combined tags).
2. [ ] Per-line and phrase-level style overrides.
3. [ ] Timeline and silence editor.
4. [ ] WAV/MP3 export profiles.
5. [ ] Project CLI runner / HTTP API.

## Next priority

The next implementation target is **reusable preprocessing / verification caching**.

The goal is to avoid repeating work that does not change between retries, resumes, and queued projects:

```text
normalized text / hashes
voice prompt resolution
ASR / verification metadata where safely reusable
project + chunk fingerprints
        ↓
cache
        ↓
less setup / repeated analysis
without skipping required verification of newly generated audio
```

The cache must never mark newly generated audio as verified merely because an older candidate with the same text once passed. Generated-audio verification remains tied to the audio fingerprint.

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
