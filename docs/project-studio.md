# OmniVoice Project Studio

Project Studio is the persistent long-form narration layer built on top of OmniVoice and the robust per-chunk verification pipeline.

For end-to-end setup, see [GUIDE-COMPACT.vi.md](GUIDE-COMPACT.vi.md) or [GUIDE-FULL.vi.md](GUIDE-FULL.vi.md).

## Project model

Scripts are parsed into:

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

A project persists script, settings, section/chunk status, generated audio and output so interrupted runtimes can resume rather than restart.

## Unified project-first UI

Launch:

```bash
omnivoice-project-studio \
  --model k2-fsa/OmniVoice \
  --workspace ./OmniVoiceStudio
```

The production workflow is organized around:

1. **Script**: parse/create a persistent project.
2. **Voice**: create/reuse Voice Library entries and variants.
3. **Preview**: validate representative output before a long render.
4. **Render**: generate all or selected sections with resume.
5. **Review**: inspect section/chunk state and regenerate targeted failures.
6. **Export**: merge verified output.

Recovery, Text Doctor, Section History, Hardware & Quality, Advanced Settings, Storage/Backup and Queue support the same project.

## Voice Library and variants

A reference can be encoded once into `VoiceClonePrompt` and reused:

```python
from omnivoice import VoiceLibrary

voices = VoiceLibrary("./OmniVoiceStudio/voices")

voices.create_from_reference(
    model,
    name="Narrator",
    reference_audio="ref.wav",
    ref_text="Exact words spoken in the reference clip.",
    language="en",
)
```

One voice can contain variants such as:

```text
DEFAULT
WARM
SOFT
PRAYER
EMPHASIZE
```

Selecting `AUTO` allows the Style Resolver to prefer a matching saved variant.

## Script format

Example:

```markdown
# Video title

## S01 - 0:00-0:45
### Opening

[WARM] Not every time you step in, you are actually helping.

## S02 - 0:45-1:30
[EMPHASIZE] Do they own what is true?
Or do they rewrite the conversation until you become the villain?
```

## Directive behavior

Square-bracket directives at the beginning of a line are metadata and are removed from spoken text.

Generic style intents include:

- `WARM`
- `SOFT`
- `EMPHASIZE`
- `NORMAL` / `DEFAULT`

Generic intents are not blindly forwarded as unsupported native OmniVoice `instruct` strings.

Documented native voice-design attributes can map directly where appropriate, for example whisper or pitch controls.

## Section-title narration

By default, Markdown headings are metadata.

```markdown
# Project title
## S01 - 0:00-0:45
### Section subtitle
```

`###` titles can optionally be narrated by enabling:

```text
Read section titles (###)
```

When enabled, the section title becomes a dedicated first spoken beat. The original Markdown script remains unchanged on disk.

## Leading conjunction safeguard

Sentence-initial conjunctions such as `Or`, `And`, `But`, `So`, `Yet`, and `Nor` can sound fragile when they begin an isolated chunk.

The narration parser attempts to merge such a chunk with the previous chunk when:

- a previous chunk exists;
- the previous chunk does not end a paragraph boundary;
- the combined text still satisfies configured word/character limits.

This keeps context for pronunciation without allowing chunks to grow unbounded.

## Language selection

Studio language controls use dropdown selectors and prioritize English first.

The UI still passes stable backend language IDs such as `en`, so presentation changes do not alter the generation API contract.

## Persistent project files

A project contains data similar to:

```text
project/
  project.json
  studio.json
  script.md
  section-status.json
  sections/
    S01/
      text.txt
      metadata.json
      chunks/
      beats/
      S01.wav
  output/
```

`studio.json` stores project-level generation choices. Unified Workspace preserves project-shaping metadata such as section-title narration when later generation settings are saved.

## Generate and resume

A direct Python path remains available:

```python
from omnivoice import OmniVoiceProject, VoiceLibrary

project = OmniVoiceProject.load(PROJECT_DIR)
voices = VoiceLibrary(VOICE_LIBRARY_DIR)
voice_prompt = voices.load_prompt("Narrator")

project.generate(
    model,
    voice_clone_prompt=voice_prompt,
    resume=True,
    language="en",
)
```

With `resume=True`, verified chunks with valid output on disk are skipped.

Example state:

```text
S07
  B01-C01 verified
  B01-C02 verified
  B01-C03 verified
  B01-C04 pending
```

Generation continues from pending work.

## Generate selected sections

```python
project.generate(
    model,
    voice_clone_prompt=voice_prompt,
    section_ids=["S03", "S04"],
    resume=True,
)
```

The UI exposes human-readable section selection while preserving stable section IDs.

## Regenerate one chunk

```python
project.mark_chunk_for_regeneration("S07", "B01-C04")

project.generate(
    model,
    voice_clone_prompt=voice_prompt,
    section_ids=["S07"],
    resume=True,
)
```

Other verified chunks remain untouched.

Section Version History provides an additional recovery boundary around targeted regeneration and forced rerenders.

## Quality and verification

The normal configuration path is one of:

```text
SAFE
BALANCED
FAST
```

`BALANCED` is the recommended starting point for most production work.

Advanced Settings can override specific project behavior while keeping the preset as the primary policy.

Each generated chunk passes through the configured verification/retry path. A failed chunk can be repaired independently.

## Preview

Preview representative opening/middle/ending samples before a long render.

Use preview to catch:

- wrong reference;
- pronunciation issues;
- pacing;
- style mismatch;
- language/accent problems.

## Queue

Project Queue supports multi-project workflows with persistent status, section-level resume, cooperative pause, error isolation and optional auto-merge.

Project states include:

```text
PENDING
GENERATING
NEEDS_REVIEW
FAILED
DONE
```

## Merge and export

By default, final merge requires verified sections:

```python
full_wav = project.merge(section_pause_ms=300)
```

Typical outputs:

```text
output/full.wav
output/timeline.json
```

Timeline metadata records planned script timing and actual generated duration. Planned timestamps are metadata and do not force time-stretching.

## Hosted-runtime rule

On Kaggle/Colab, use local SSD for active generation.

Remote Drive/Dataset/cloud storage should be treated as a restore/sync/export boundary.

This keeps section/chunk checkpoint I/O away from high-latency remote filesystems.

## Current production status

Merged:

- persistent Project model;
- robust section/chunk generation and verification;
- checkpoint/resume;
- targeted regeneration;
- Voice Library and Style Bank;
- preview;
- Text Doctor;
- Voice Doctor;
- Voice Stability;
- Section Version History;
- multi-project queue;
- quality presets;
- Advanced Settings;
- unified project-first workspace;
- English-first language selectors;
- optional section-title narration;
- leading conjunction safeguard;
- AI-native Job Manager/SSE/MCP/tunnel/auth foundation.

For current in-review, experimental and planned work, see [project-studio-roadmap.md](project-studio-roadmap.md).
