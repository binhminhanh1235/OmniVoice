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
2. [ ] Colab hardware detection and quality presets (`Safe`, `Balanced`, `Fast`) without exposing a wall of generation parameters.
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
6. [ ] Batch multiple projects.

## Next priority

The next implementation target is **Colab hardware detection + quality presets**.

The goal is not to add more knobs. It is to reduce them:

```text
GPU / VRAM / ASR availability
        ↓
automatic capability detection
        ↓
Safe | Balanced | Fast
        ↓
appropriate generation + verification defaults
```

`Safe` should preserve the current strongest verification behavior. `Balanced` may reduce retry/verification cost conservatively. `Fast` should only trade quality for speed when the user explicitly selects it.

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