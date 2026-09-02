# Live section status in Project Studio

The default `omnivoice-project-studio` entrypoint now launches the live generation UI.

## Why

A full project render can take many minutes. A single blocking Gradio callback makes the section table look empty while the job is running. The live UI instead generates one Sxx section at a time and yields a complete table before inference and after every section transition.

## States

```text
QUEUED
  -> GENERATING
  -> VERIFIED / UNVERIFIED / FAILED
```

With Resume enabled, a section whose chunks are already verified is shown as `SKIPPED`.

Sections not included in the optional section filter remain visible and are marked `not selected`.

## Recommended flow

1. Select the project and saved voice.
2. Click `Preflight` to populate the table before GPU inference.
3. Click `Generate / Resume`.
4. Watch each Sxx row update while the render runs.
5. If a section fails, the table remains visible and `generation_error.json` records the failing section and traceback.

The generated section audio picker updates after each completed section, so a finished section can be auditioned while later sections are still pending.
