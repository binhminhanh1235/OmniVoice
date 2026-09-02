# Kaggle local execution workspace

Project Studio treats Kaggle local SSD as an **execution workspace**, not as persistent storage.

## Runtime layout

```text
/kaggle/working/OmniVoiceStudio/
  projects/
    <project>/
      project.json
      studio.json
      section-status.json
      sections/
      output/
  voices/
  project-queue.json
  hardware-quality.json
```

`/kaggle/input` is read-only source material. It can contain scripts or reference audio supplied through Kaggle datasets, but Project Studio never writes projects, checkpoints, queue state, or generated WAVs there.

## Why local-first

Long-form generation creates many small checkpoint/report/audio files. Keeping the active project on Kaggle local storage avoids remote-filesystem latency and keeps the existing section/chunk resume logic unchanged.

This phase intentionally does **not** implement Google Drive, rclone, object storage, or background synchronization.

## Default workspace detection

`omnivoice.runtime_workspace.detect_runtime_workspace()` selects:

```text
Kaggle  -> /kaggle/working/OmniVoiceStudio
Colab   -> mounted MyDrive when already available, otherwise /content/OmniVoiceStudio
Local   -> ./OmniVoiceStudio
```

`OMNIVOICE_STUDIO_HOME` overrides the default on every platform.

Kaggle is detected by its environment variables or by the presence of `/kaggle/working`.

## Ephemeral semantics

The Kaggle workspace is marked `ephemeral=True` and `persistence_backend="none"`.

`section-status.json` and `project-queue.json` still provide crash/resume behavior while the Kaggle working directory survives, but they do not protect against the Kaggle session being discarded.

Remote persistence is a separate future layer. It should copy/synchronize the execution workspace without changing Project -> Section -> Beat -> Chunk generation semantics.

## Kaggle notebook

Use:

```text
notebooks/OmniVoice_Project_Studio_Kaggle.ipynb
```

The notebook installs the Kaggle branch, validates the runtime/GPU, reports free local disk, and launches:

```bash
omnivoice-project-studio \
  --model k2-fsa/OmniVoice \
  --workspace /kaggle/working/OmniVoiceStudio \
  --asr-model openai/whisper-small.en \
  --asr-device cpu \
  --share
```

T4-class runtimes should normally keep ASR on CPU so OmniVoice owns the GPU VRAM. Quality policy remains controlled by SAFE / BALANCED / FAST.

## Architectural boundary for future persistence

```text
future persistent backend
        <-> sync/export boundary
/kaggle/working/OmniVoiceStudio
        -> Project Studio
        -> Project Queue
        -> section-status.json
        -> generated WAVs
```

The execution path never needs to know whether persistence is Google Drive, another Drive account, S3-compatible storage, or something else.
