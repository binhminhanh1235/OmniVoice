# OmniVoice Voice Style Bank

Voice Style Bank lets one narrator have several reusable reference prompts and lets Project Studio choose the best prompt for each script beat.

## Why this exists

Generic script directives such as `[WARM]`, `[SOFT]`, and `[EMPHASIZE]` should not be spoken and should not be passed to OmniVoice as unsupported raw `instruct` values.

Instead, save multiple 3–10 second references from the same narrator:

```text
Warm American Male
  DEFAULT
  WARM
  SOFT
  EMPHASIZE   # optional
```

Project Studio can then use `AUTO` selection.

## Recommended setup

Start with one clean `DEFAULT` reference. It is the safety fallback.

Then add variants only when you have a genuinely useful sample of the same narrator:

- `WARM`: conversational, compassionate narration.
- `SOFT`: quieter, gentler delivery.
- `EMPHASIZE`: firmer delivery for important statements. Optional because `WARM` is a safe fallback.

Use the same Voice name for every variant. Example:

```text
Voice name: Warm American Male
Variant: DEFAULT
Reference: narrator-neutral.wav

Voice name: Warm American Male
Variant: WARM
Reference: narrator-warm.wav

Voice name: Warm American Male
Variant: SOFT
Reference: narrator-soft.wav
```

Each reference is encoded once into a reusable `VoiceClonePrompt` and persisted in the Voice Library.

## AUTO resolution

When the UI uses `Voice variant = AUTO`, variant selection happens per Beat:

```text
[WARM]       -> WARM -> DEFAULT
[SOFT]       -> SOFT -> DEFAULT
[EMPHASIZE]  -> EMPHASIZE -> WARM -> DEFAULT
[WHISPER]    -> WHISPER -> SOFT -> DEFAULT
```

The first available variant wins.

If a requested variant is missing, generation continues using the fallback and records that fallback in the chunk verification JSON.

## Locking one style

Choose a concrete variant such as `DEFAULT` instead of `AUTO` to use that same prompt for the entire generation request.

This is useful for A/B testing or when you want maximum voice consistency and do not want script tags to select reference variants.

## Script behavior

Input:

```markdown
## S01 — 0:00–0:45

[WARM] Not every time you step in, you are actually helping.

## S02 — 0:45–1:45

[SOFT] Let's be clear from the beginning.
```

Spoken text never contains the directives:

```text
Not every time you step in, you are actually helping.
Let's be clear from the beginning.
```

The directives remain project metadata and control reference selection and conservative delivery profiles.

## Python API

```python
from omnivoice import (
    OmniVoiceProject,
    StyleBankProjectRunner,
    VoiceLibrary,
)

project = OmniVoiceProject.load(PROJECT_DIR)
voices = VoiceLibrary(VOICE_LIBRARY_DIR)

runner = StyleBankProjectRunner(
    model,
    voices,
    voice_name="Warm American Male",
    preferred_variant="AUTO",
)

runner.generate(
    project,
    language="en",
    resume=True,
)
```

## Verification metadata

Each generated chunk report includes:

```json
{
  "style": "SOFT",
  "voice_name": "Warm American Male",
  "voice_variant": "SOFT",
  "voice_variant_fallback": false
}
```

If `SOFT` is missing and `DEFAULT` is used:

```json
{
  "style": "SOFT",
  "voice_variant": "DEFAULT",
  "voice_variant_fallback": true
}
```

This makes the final render auditable and helps identify where another style reference would improve quality.

## Practical recommendation

Do not create ten style variants immediately. Start with:

1. `DEFAULT`
2. `WARM`
3. `SOFT`

That covers most long-form Christian narration while keeping reference management simple. Add `EMPHASIZE` only after listening tests show a real benefit.
