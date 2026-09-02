# Adaptive Retry and Pacing Guard

Project Studio uses this quality layer on top of `RobustLongFormGenerator`.
It does not change OmniVoice's base decoder.

## Why

A blind retry can regenerate the same class of failure several times. The new
layer first classifies the failure, then changes the next attempt.

```text
candidate
  -> ASR text fidelity
  -> pacing guard
  -> classify failure
  -> adapt next attempt
  -> retry
  -> persistent severe failure -> split smaller
```

## Failure classes

- `critical_missing`: semantic negations such as `not`, `no`, `never`, or
  `without` disappeared.
- `omission`: generated transcript is materially shorter than the source.
- `repetition`: an n-gram appears more often than it does in the source.
- `pacing`: the generated speech is globally too fast or contains a strong
  local speed spike.
- `asr_mismatch`: WER/similarity failed without one of the more specific
  causes above.

## Adaptive actions

The defaults are intentionally conservative.

| Failure | Next action |
| --- | --- |
| repetition | lower position temperature; force greedy class sampling |
| critical missing / omission | add decoding steps and lower position temperature |
| pacing | reduce requested speed and lower position temperature |
| generic ASR mismatch | lower position temperature |
| same severe failure twice | split the semantic chunk early instead of burning all retries |

The exact action is stored in each chunk report, for example:

```json
{
  "recovered_from": ["repetition"],
  "retry_actions": ["position_temperature->0.70"],
  "global_wps": 2.64,
  "max_local_wps": 3.08,
  "pacing_anomaly": false
}
```

## Pacing guard

The guard always has a global fallback:

```text
intended words / WAV duration
```

When the configured Whisper pipeline supports `return_timestamps="word"`, the
same ASR pass also yields word timestamps. Project Studio then computes sliding
local speech-rate windows.

A pacing failure is raised when either:

1. global rate exceeds the conservative global limit, or
2. a local window exceeds the local limit *and* is much faster than the median
   local rate of the same chunk.

This second rule targets the OmniVoice failure mode where a sentence begins
normally and suddenly accelerates near the end.

If word timestamps are unavailable, generation does not fail because of the
missing feature. Text verification continues and pacing falls back to the
global WAV-duration check.

## Defaults

```python
from omnivoice import AdaptiveQualityConfig

quality = AdaptiveQualityConfig(
    adaptive_retry=True,
    pacing_guard=True,
    max_global_wps=4.6,
    max_local_wps=5.5,
    max_local_speed_ratio=1.70,
    pacing_window_words=5,
    early_split_after=2,
)
```

These values are guardrails for narration, not universal linguistic limits.
They should remain configurable for deliberately rapid speech.

## Project Studio integration

`StyleBankProjectRunner` and Preview Before Render both use
`AdaptiveRobustLongFormGenerator` on this branch. The persistent chunk JSON
therefore contains the adaptive quality fields automatically.

Checkpoint/resume semantics are unchanged: only a failed or explicitly reset
chunk is regenerated.