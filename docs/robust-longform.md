# Robust long-form generation

This fork adds an opt-in long-form wrapper for narration where semantic accuracy
is more important than raw throughput.

It targets four failure modes reported with longer synthesis:

- skipped or clipped words;
- duplicated words/phrases;
- sentence mixing across chunk boundaries;
- low-level phonemes damaged by output trimming/fades.

The branch also includes the configurable silence-processing changes from
upstream PR #259.

## How it works

`RobustLongFormGenerator` uses a defensive pipeline:

1. Decode HTML entities and normalize layout-only whitespace.
2. Split by paragraph and hard sentence boundaries first.
3. Split an overlong sentence at semicolons/colons, using commas only as a
   fallback.
4. Reuse one `VoiceClonePrompt` for every chunk.
5. Disable nested OmniVoice automatic long-form chunking for those already-small
   chunks.
6. Disable per-chunk fade/padding by default, then join chunks with explicit
   silence instead of cross-fading speech.
7. Optionally transcribe each generated chunk with Whisper.
8. Reject a chunk when it has excessive WER, suspicious word-count drift,
   duplicated n-grams, or a missing critical negation such as `not`.
9. Retry only the failed chunk. If it still fails, recursively split it into
   smaller semantic pieces.

This does not change the base OmniVoice decoding algorithm. It is an opt-in
reliability layer for long-form content.

## Basic usage

```python
import soundfile as sf
import torch

from omnivoice import (
    OmniVoice,
    OmniVoiceGenerationConfig,
    RobustLongFormConfig,
    RobustLongFormGenerator,
)

model = OmniVoice.from_pretrained(
    "k2-fsa/OmniVoice",
    device_map="cuda:0",
    dtype=torch.float16,
)

voice_prompt = model.create_voice_clone_prompt(
    ref_audio="reference.wav",
    ref_text="Exact transcript of the reference audio.",
)

robust = RobustLongFormGenerator(
    model,
    RobustLongFormConfig(
        max_chunk_words=28,
        max_retries=3,
        max_split_depth=2,
        verify_with_asr=True,
        asr_model_name="openai/whisper-small.en",
        asr_device="cpu",
    ),
)

generation_config = OmniVoiceGenerationConfig(
    num_step=32,
    guidance_scale=2.0,
    position_temperature=1.0,
    class_temperature=0.0,
)

result = robust.generate(
    text=LONG_TEXT,
    language="en",
    voice_clone_prompt=voice_prompt,
    generation_config=generation_config,
)

sf.write("output.wav", result.audio, result.sampling_rate)

for report in result.reports:
    print(
        report.accepted,
        report.wer,
        report.text,
        "=>",
        report.transcript,
    )
```

## Reference audio

For voice cloning, use a clean 3–10 second reference whenever possible. Provide
an exact transcript instead of relying on automatic reference transcription.
The wrapper creates/reuses a single `VoiceClonePrompt`, so the reference is not
re-encoded independently for every chunk.

## HTML entities

Text copied from rich editors sometimes contains values such as `&#x20;` or
`&nbsp;`. The robust wrapper decodes these before synthesis so they do not become
unexpected tokenizer input.

## Verification thresholds

Defaults are intentionally practical rather than mathematically strict:

- `max_wer=0.18`
- `min_similarity=0.82`
- word-count ratio between `0.74` and `1.30`
- reject additional repeated bigrams
- reject missing `not`, `no`, `never`, or `without`

Whisper is itself fallible. If a chunk sounds correct but fails repeatedly due
to ASR, first try a better ASR model or relax `max_wer` slightly (for example,
`0.22`). Do not disable the negation check for content where a missing `not`
would reverse the meaning.

## Strict mode

By default, when all retries and recursive splits fail, the best candidate is
kept and the report marks it as unverified. For pipelines where semantic
correctness is mandatory:

```python
RobustLongFormConfig(strict=True)
```

This raises an exception instead of silently accepting the remaining bad chunk.

## Why no cross-fade?

Cross-fading speech chunks can overlap the release of one phoneme with the
attack of the next chunk. This wrapper joins verified chunks with explicit
silence instead. It also disables generic per-chunk fades/padding by default.
The silence post-processing patch from PR #259 preserves low-level attacks and
releases while allowing exact digital-silence edge targets.

## Colab

See `notebooks/OmniVoice_Robust_LongForm_Colab.ipynb` in this branch for a
ready-to-run Google Colab workflow.
