# OmniVoice Project Studio — P0 workflow

Project Studio is the persistent long-form narration layer built on top of `RobustLongFormGenerator`.

It is designed for scripts such as:

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

## Fastest path: Project Studio UI

After installing the branch, launch:

```bash
omnivoice-project-studio \
  --model k2-fsa/OmniVoice \
  --workspace /content/drive/MyDrive/OmniVoiceStudio \
  --share
```

The UI is organized around three steps:

1. **Voice Library** — save a reference voice once.
2. **Project** — paste/parse the entire Markdown script and create a persistent project.
3. **Generate / Resume** — choose a voice, generate all or selected sections, regenerate one bad chunk, play section WAVs, and merge `full.wav`.

The UI is intentionally a thin wrapper over the Python project APIs, so project files remain usable without Gradio.

## Voice Library

A reference is encoded once into `VoiceClonePrompt` and saved for reuse across Colab sessions and projects:

```python
from omnivoice import VoiceLibrary

voices = VoiceLibrary(
    "/content/drive/MyDrive/OmniVoiceStudio/voices"
)

voices.create_from_reference(
    model,
    name="Warm American Male",
    reference_audio="ref.wav",
    ref_text="Exact words spoken in the reference clip.",
    language="en",
)

voice_prompt = voices.load_prompt("Warm American Male")
```

Voice files are stored like:

```text
voices/
  warm-american-male/
    voice.json
    prompts/
      default.pt
    references/
      default.wav
```

The storage format already supports variants (`DEFAULT`, `WARM`, `SOFT`, etc.), which prepares the project layer for a later Voice Style Bank. P0 only requires one default variant.

## Important directive behavior

Square-bracket directives at the beginning of a line are metadata. They are removed from spoken text.

Supported P0 generic style intents:

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

This separation keeps the script format model-agnostic.

## Headings are not spoken

The following are project metadata and are excluded from TTS:

```markdown
# Project title
## S01 — 0:00–0:45
### Section subtitle
[WARM]
```

A Markdown line-ending backslash is also removed before TTS.

## Create a project from Python

```python
from omnivoice import OmniVoiceProject

project = OmniVoiceProject.create(
    SCRIPT,
    "/content/drive/MyDrive/OmniVoiceStudio/projects/5-people-stop-enabling",
    max_chunk_words=24,
    max_chunk_chars=220,
)

for row in project.summary():
    print(row)
```

Project files are stored like:

```text
project/
  project.json
  studio.json
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

`studio.json` is written by the UI/controller and remembers the selected voice, voice variant, and language for the project.

## Generate

Load a reusable prompt from the Voice Library, then generate:

```python
from omnivoice import OmniVoiceProject, VoiceLibrary

project = OmniVoiceProject.load(PROJECT_DIR)
voices = VoiceLibrary(VOICE_LIBRARY_DIR)
voice_prompt = voices.load_prompt("Warm American Male")

project.generate(
    model,
    voice_clone_prompt=voice_prompt,
    resume=True,
    language="en",
)
```

Every project chunk is passed through the robust generation quality gate. Its WAV and verification JSON are saved immediately after generation.

## Resume after a Colab interruption

```python
project = OmniVoiceProject.load(PROJECT_DIR)
project.generate(
    model,
    voice_clone_prompt=voice_prompt,
    resume=True,
)
```

Chunks already marked `verified` and present on disk are skipped.

Example:

```text
S07
  B01-C01 verified
  B01-C02 verified
  B01-C03 verified
  B01-C04 pending
```

Generation resumes from the pending work instead of starting the whole project again.

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

Other verified chunks remain untouched. The Gradio UI exposes the same operation through the **Regenerate selected chunk** button.

## Generate only selected sections

```python
project.generate(
    model,
    voice_clone_prompt=voice_prompt,
    section_ids=["S03", "S04"],
    resume=True,
)
```

In the UI, enter for example:

```text
S03,S07,S10
```

Leave the field empty to generate the whole project.

## Project status

The UI shows section-level status:

```text
Section | Style | Chunks | Verified | Unverified | Status
S01     | WARM  | 4      | 4        | 0          | verified
S02     | WARM  | 6      | 6        | 0          | verified
S03     | EMPHASIZE | 7  | 6        | 1          | unverified
```

A chunk dropdown exposes every `Sxx/Bxx-Cxx` unit for targeted regeneration.

## Merge the finished project

By default merge requires all sections to be verified:

```python
full_wav = project.merge(section_pause_ms=300)
```

Outputs:

```text
output/full.wav
output/timeline.json
```

`timeline.json` records both planned script timestamps and actual generated durations. Planned timestamps are metadata; P0 does not time-stretch speech to force the WAV to match them.

## P0 status

Implemented:

- persistent Project model;
- `S01`, `S02`, ... parser;
- directive stripping and metadata;
- Project -> Section -> Beat -> Chunk hierarchy;
- separate section WAVs;
- robust chunk verification reports;
- checkpoint/resume;
- regenerate one chunk;
- optional full WAV merge;
- generic style resolver separated from native OmniVoice `instruct`;
- persistent Voice Library with saved `VoiceClonePrompt`;
- voice variants storage format;
- Simple Gradio Project UI;
- visual section/chunk status;
- play generated section;
- UI actions for Generate, Resume, targeted Regenerate, and Merge.

Next after P0 stabilizes:

- Voice Style Bank (`neutral`, `warm`, `soft`, `prayer` reference prompts) with automatic style selection;
- preview 3 samples before full render;
- reference Voice Doctor / quality score;
- adaptive retry based on failure type;
- pacing anomaly detector;
- richer directive DSL and per-line style overrides;
- timeline editor and section version history.
