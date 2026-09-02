# Persistent section status and crash-safe resume

Project Studio keeps the full project structure in `project.json` and now keeps a second, deliberately small checkpoint beside it:

```text
<project>/
  project.json
  section-status.json
  script.md
  sections/
    S01/S01.wav
    S02/S02.wav
```

`section-status.json` is the section-level source of truth for restart/resume decisions. It is written atomically so an interrupted Colab runtime cannot leave a half-written JSON file.

Example:

```json
{
  "version": 1,
  "project_source_hash": "...",
  "updated_at": "2026-09-01T...Z",
  "sections": {
    "S01": {
      "status": "verified",
      "audio_file": "sections/S01/S01.wav",
      "updated_at": "2026-09-01T...Z",
      "complete": true
    },
    "S02": {
      "status": "generating",
      "audio_file": null,
      "updated_at": "2026-09-01T...Z",
      "complete": false
    },
    "S03": {
      "status": "pending",
      "audio_file": null,
      "updated_at": null,
      "complete": false
    }
  }
}
```

## Resume rules

A section is complete only when both conditions hold:

1. its persisted status is `verified`;
2. its final section WAV still exists.

This prevents a stale JSON checkpoint from skipping a section whose audio was deleted or lost.

Interrupted states are safe:

```text
queued      -> pending on next load
generating  -> pending on next load
verified + WAV exists -> skip
verified + WAV missing -> pending
pending/unverified/failed -> generate/resume
```

Chunk checkpoints remain useful inside an incomplete section. If S02 stopped after several verified chunks, section-level resume selects S02 and the existing chunk-level logic skips the chunks that already have verified audio.

## Durability boundary

`StyleBankProjectRunner` flushes the section sidecar immediately after each section is assembled. It does not wait for the whole project batch.

```text
S01 generating
   -> S01.wav written
   -> S01 verified
   -> section-status.json flushed

S02 generating
   -> runtime disconnects

next Colab session
   -> load project
   -> S01 restored as verified and skipped
   -> S02 recovered as pending
   -> continue from S02
```

## Project Studio launcher

For the Text Doctor + resume-aware workflow use:

```bash
python -m omnivoice.cli.project_studio_text_resume \
  --model k2-fsa/OmniVoice \
  --workspace /content/drive/MyDrive/OmniVoiceStudio \
  --asr-model openai/whisper-small.en \
  --asr-device cpu \
  --share
```

Existing projects are migrated lazily. When an older project without `section-status.json` is loaded, the sidecar is created from the current manifest. No project conversion command is required.
