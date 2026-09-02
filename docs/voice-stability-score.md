# Voice Stability Score

Voice Stability Score is an optional GPU preflight for a saved Voice Library prompt.

Voice Doctor asks whether the **reference file** looks healthy. Voice Stability Score asks whether OmniVoice can **actually clone from that prompt reliably** on a small test set.

## What happens

The test loads one saved voice variant and synthesizes three short English sentences chosen to exercise:

- ordinary narration;
- punctuation and pacing;
- a semantic-critical negation (`not`);
- a slightly longer sentence.

Each WAV is transcribed with the loaded ASR model and checked for:

- WER;
- sequence similarity;
- word-count drift;
- missing critical words such as `not`;
- extra repeated phrases;
- implausibly fast global pacing;
- speaking-rate consistency across the three samples.

The three WAVs and `stability.json` are saved under:

```text
voices/<voice>/stability/<variant>/
```

## Score

The 0–100 score combines text fidelity and pacing consistency. A voice is marked `stable` only when:

- the aggregate score is at least 80; and
- every clone test passes the fidelity/pacing gate.

This makes the flag intentionally conservative. A high aggregate score does not hide a single sample that drops a critical word.

## Important limitation

The current score is a **generation stability** score. It does not yet measure speaker-identity similarity because no speaker-embedding verifier has been added. The UI states this explicitly.

## Cost

Unlike Voice Doctor, this step performs real TTS generations and ASR, so it consumes GPU/CPU time. It is therefore optional and never runs automatically when a voice is saved.
