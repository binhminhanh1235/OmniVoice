# Preview Before Full Render

Project Preview generates a few representative samples before rendering the entire narration project.

It is designed to answer one question cheaply:

> Does this voice + style setup sound right before I spend GPU time on every Sxx section?

## What gets previewed

By default Project Studio selects three existing semantic chunks:

- `opening`: the first chunk in the project;
- `middle`: the chunk nearest the middle of the flattened project;
- `ending`: the final chunk.

The preview generator preserves the original Section, Beat and style metadata.

## Non-destructive behavior

Preview generation does **not**:

- mark project chunks as verified;
- replace `S01.wav`, `S02.wav`, etc.;
- modify project checkpoint status;
- make the full project appear completed.

Preview WAVs and reports are written separately under:

```text
project/
  previews/
    opening_S01_B01-C01.wav
    opening_S01_B01-C01.json
    middle_S06_B01-C03.wav
    middle_S06_B01-C03.json
    ending_S11_B01-C02.wav
    ending_S11_B01-C02.json
```

## Style Bank aware

Preview uses the same Voice Style Bank resolution intended for the final render.

Example with `preferred_variant="AUTO"`:

```text
opening [WARM] -> WARM reference
middle  [SOFT] -> SOFT reference
ending  [WARM] -> WARM reference
```

If a style reference is missing, the normal Style Bank fallback is used and recorded in the preview report.

## Python example

```python
from omnivoice import (
    OmniVoiceProject,
    ProjectPreviewGenerator,
    VoiceLibrary,
)

project = OmniVoiceProject.load(PROJECT_DIR)
voices = VoiceLibrary(VOICE_LIBRARY_DIR)

preview = ProjectPreviewGenerator(
    model,
    voices,
    voice_name="Warm American Male",
    preferred_variant="AUTO",
)

results = preview.generate(
    project,
    language="en",
)

for item in results:
    print(
        item.target.label,
        item.target.section_id,
        item.target.style,
        item.voice_variant,
        item.audio_file,
    )
```

Generate only the opening sample:

```python
preview.generate(
    project,
    labels=["opening"],
    language="en",
)
```

## Recommended workflow

```text
Create Project
    ↓
Choose Voice + AUTO Style Bank
    ↓
Generate 3 previews
    ↓
Listen opening / middle / ending
    ↓
Not good → change reference/style bank
    ↓
Good → Generate / Resume full project
```

The next UI step is to expose these three preview WAVs directly inside Project Studio with one `Generate Preview` button.
