# OmniVoice Project Studio roadmap

This roadmap prioritizes the workflow for long-form narrated projects on Google Colab.

## P0 — usable project workflow

- [x] Persistent Project model
- [x] `S01`, `S02`, ... Markdown parser
- [x] Directive stripping (`WARM`, `SOFT`, `EMPHASIZE`, `NORMAL`)
- [x] Project -> Section -> Beat -> Chunk hierarchy
- [x] Separate section WAV files
- [x] Robust per-chunk verification
- [x] Checkpoint / resume
- [x] Persistent `section-status.json` checkpoint with crash-safe section resume
- [x] Skip completed sections after reload; resume only incomplete sections
- [x] Regenerate one chunk only
- [x] Merge verified sections into `full.wav`
- [x] Persistent Voice Library / cached `VoiceClonePrompt`
- [x] Simple Gradio Project Studio
- [x] Section/chunk status table
- [x] Live per-section generation status
- [x] Colab Project Studio launcher

## P1 — narration quality

- [x] Voice Style Bank: `DEFAULT`, `WARM`, `SOFT`, `PRAYER`, optional `EMPHASIZE` reference variants.
- [x] Style Resolver automatically chooses a matching saved voice variant when available, then falls back to delivery controls.
- [x] Preview three representative samples before full rendering.
- [x] Adaptive retry based on failure reason: repetition, omission, pacing, text mismatch.
- [x] Pacing anomaly detector with global fallback and optional Whisper word timestamps.
- [x] Text Doctor: HTML/Unicode cleanup plus visible diff and review hints for semantic changes.
- [ ] Voice Doctor: reference duration/noise/clipping/silence checks.
- [ ] Voice Stability Score from short clone probes.
- [ ] Section/chunk version history instead of overwriting the previous good output.

## P2 — efficiency

1. Cascade ASR verification: small model first, larger verifier only for borderline chunks.
2. Hardware detection and Colab-specific presets.
3. FlashInfer/CUDA-graph benchmark before enabling acceleration.
4. Cache generation metadata and avoid repeated preprocessing.
5. Automatic best 3–10 second reference extraction from long recordings.
6. Same-language reference selection when a voice has multiple language variants.

## P3 — production tools

1. Rich directive DSL (`PAUSE`, `SLOW`, `FAST`, `PITCH`, `VOICE`, combined tags).
2. Per-line and phrase-level style overrides.
3. Timeline and silence editor.
4. WAV/MP3 export profiles.
5. Project CLI runner / HTTP API.
6. Batch multiple projects.

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

This makes saved scripts portable to future TTS backends.