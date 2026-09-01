# OmniVoice Project Studio — P0 workflow

This is the persistent long-form project layer built on top of `RobustLongFormGenerator`.

It is designed for narration scripts such as:

```markdown
# 5 People You Should Stop Enabling

## S01 — 0:00–0:45

[WARM] Not every time you step in, you are actually helping.

## S02 — 0:45–1:45

[SOFT] Let's be clear from the beginning.
```

The parser creates:

```text
Project
  Section S01
    Beat B01 [WARM]
      Chunk B01-C01
      Chunk B01-C02
  Section S02
    Beat B01 [SOFT]
      Chunk B01-C01
```

## Important directive behavior

Square-bracket directives at the beginning of a line are metadata. They are removed from spoken text.

Supported P0 style intents:

- `WARM`
- `SOFT`
- `EMPHASIZE`
- `NORMAL` / `DEFAULT`

These generic emotion/delivery tags are **not** passed to OmniVoice as raw `instruct` strings. OmniVoice does not officially expose `warm`, `soft`, or `emphasize` as voice-design attributes.

The style resolver instead makes conservative delivery adjustments such as speed and pause length.

Documented OmniVoice-native attributes can map directly. P0 includes examples:

- `[WHISPER]` -> `instruct="whisper"`
- `[LOW PITCH]` -> `instruct="low pitch"`
- `[HIGH PITCH]` -> `instruct="high pitch"`

This separation keeps the script format model-agnostic and leaves room for a future Voice Style Bank.

## Headings are not spoken

The following are project metadata and are excluded from TTS:

```markdown
# Project title
## S01 — 0:00–0:45
### Section subtitle
[WARM]
```

A Markdown line-ending backslash is also removed before TTS.

## Create a project

```python
from omnivoice import OmniVoiceProject

project = OmniVoiceProject.create(
    SCRIPT,
    "/content/drive/MyDrive/OmniVoiceProjects/5-people-stop-enabling",
    max_chunk_words=24,
    max_chunk_chars=220,
)

for row in project.summary():
    print(row)
```

Project files are stored like this:

```text
project/
  project.json
  script.md
  sections/
    S01/
      text.txt
      metadata.json
      chunks/
        B01-C01.wav
        B01-C01.json
      beats/
        B01.wav
      S01.wav
    S02/
      ...
  output/
```

## Generate

Create or load one reusable `VoiceClonePrompt`, then generate the project:

```python
from omnivoice import (
    OmniVoice,
    OmniVoiceProject,
    RobustLongFormConfig,
)

project = OmniVoiceProject.load(PROJECT_DIR)

project.generate(
    model,
    voice_clone_prompt=voice_prompt,
    robust_config=RobustLongFormConfig(
        verify_with_asr=True,
        asr_model_name="openai/whisper-small.en",
        asr_device="cpu",
        max_retries=3,
        max_split_depth=2,
    ),
    resume=True,
)
```

Every project chunk is passed through the robust generation quality gate. Its WAV and verification JSON are saved immediately after generation.

## Resume after a Colab interruption

Reopen Drive and load the project:

```python
project = OmniVoiceProject.load(PROJECT_DIR)
project.generate(
    model,
    voice_clone_prompt=voice_prompt,
    resume=True,
)
```

Chunks already marked `verified` and present on disk are skipped.

For example, if generation stopped here:

```text
S07
  B01-C01 verified
  B01-C02 verified
  B01-C03 verified
  B01-C04 pending
```

only `B01-C04` onward needs work.

## Regenerate one bad chunk

```python
project.mark_chunk_for_regeneration(
    "S07",
    "B01-C04",
)

project.generate(
    model,
    voice_clone_prompt=voice_prompt,
    section_ids=["S07"],
    resume=True,
)
```

Other verified chunks remain untouched.

## Generate only selected sections

```python
project.generate(
    model,
    voice_clone_prompt=voice_prompt,
    section_ids=["S03", "S04"],
    resume=True,
)
```

## Merge the finished project

By default merge requires all sections to be verified:

```python
full_wav = project.merge(
    section_pause_ms=300,
)
print(full_wav)
```

The output is written to:

```text
output/full.wav
output/timeline.json
```

`timeline.json` records both the planned script timestamps and the actual generated durations. Planned timestamps are metadata; P0 does not time-stretch speech to force the WAV to match them.

## Current P0 boundary

Implemented now:

- persistent Project model;
- `S01`, `S02`, ... parser;
- directive stripping and metadata;
- Project -> Section -> Beat -> Chunk hierarchy;
- separate section WAVs;
- chunk verification reports;
- checkpoint/resume;
- regenerate one failed chunk;
- optional full WAV merge;
- generic style resolver separated from native OmniVoice `instruct`.

Planned next:

- Simple Gradio Project UI;
- Voice Library and saved prompt picker;
- Voice Style Bank (`neutral`, `warm`, `soft`, `prayer` reference prompts);
- preview before full render;
- visual per-section/per-chunk regenerate controls;
- richer directives and adaptive retry.
