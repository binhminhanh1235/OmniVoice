# Voice Doctor

Voice Doctor is a non-destructive preflight check for voice-cloning reference audio.

It is designed to answer a simple question before GPU time is spent:

> Is this reference likely to be a stable input for voice cloning?

## Recommended workflow

1. Upload the intended reference in the **Voice Doctor** tab.
2. Click **Analyze reference**.
3. Prefer a score of **78+ / GOOD** or **90+ / EXCELLENT**.
4. Review any warnings.
5. Only then save the reference into Voice Library.

Voice Doctor never edits the uploaded file.

## What it checks

- duration, with 3–10 seconds treated as the preferred range;
- sample rate;
- mono/stereo channel count;
- peak level and clipping ratio;
- RMS level;
- silence ratio;
- DC offset;
- approximate non-silent noise floor;
- basic dynamic separation across short RMS frames.

## Score bands

| Score | Grade | Meaning |
| ---: | --- | --- |
| 90–100 | EXCELLENT | strong starting reference |
| 78–89 | GOOD | recommended, minor issues possible |
| 60–77 | REVIEW | listen/check before cloning |
| 0–59 | POOR | replace or clean the reference |

A reference is not marked recommended when it has a hard duration failure or measurable clipping, even if other metrics are good.

## Important limitation

Voice Doctor uses inexpensive signal heuristics. It does **not** yet perform speaker diarization, music detection, dereverberation, semantic transcript checks, or automatic best-segment extraction. Those belong to later roadmap items.

The current goal is to catch obvious bad references early without adding another large model or consuming GPU memory.
