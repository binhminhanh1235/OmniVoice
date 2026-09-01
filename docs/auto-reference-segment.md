# Auto Best Reference Segment

Auto Best Reference Segment helps when the source recording is much longer than the 3–10 second reference normally preferred for voice cloning.

## Workflow

1. Upload the longer recording in **Voice Doctor**.
2. Choose a candidate length from 3 to 10 seconds. Six seconds is the default.
3. Click **Find Best Segments**.
4. Studio scans overlapping windows and returns the top candidates.
5. Listen to the candidates.
6. Click **Use selected segment as reference** for the one you prefer.
7. Optionally request an ASR transcript suggestion, then review it against the audio.
8. Run normal Voice Doctor analysis and save the voice.

The top-ranked segment is never saved automatically. Human listening remains the final selection step.

## Ranking signals

The selector is lightweight and does not load another neural model. It ranks windows using:

- clipping ratio and peak headroom;
- RMS level;
- silence ratio;
- dynamic separation across short RMS frames;
- DC offset;
- activity at the segment boundaries, with a small penalty for cutting through strong speech at both edges.

Candidate metadata is stored under the Studio workspace in `reference_candidates/` together with a JSON ranking report.

## Transcript suggestion

When Project Studio already has Whisper loaded, **Suggest transcript with ASR** can fill the transcript field for the selected candidate.

This is only a suggestion. The transcript should still be checked against the candidate audio because an exact reference transcript improves voice-clone reliability.

## Limits

This first selector does not perform speaker diarization, source separation, music classification, or speaker-identity scoring. A recording with multiple speakers or strong music should still be cleaned or reviewed manually.
