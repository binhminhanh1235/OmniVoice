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

Project persistence remains separate from execution storage. Startup-resource persistence is now implemented independently: dependency wheels, pip downloads, Hugging Face/OmniVoice assets and Whisper assets can be restored from a compatible cache into local SSD before Studio starts.

## Default workspace detection

`omnivoice.runtime_workspace.detect_runtime_workspace()` selects:

```text
Kaggle  -> /kaggle/working/OmniVoiceStudio
Colab   -> runtime detector may expose mounted MyDrive; the production Colab notebook explicitly runs generation from /content/OmniVoiceStudio and mirrors persistence outside the render hot path
Local   -> ./OmniVoiceStudio
```

`OMNIVOICE_STUDIO_HOME` overrides the default on every platform.

Kaggle is detected by its environment variables or by the presence of `/kaggle/working`.

## Ephemeral semantics

The Kaggle workspace is marked `ephemeral=True` and `persistence_backend="none"`.

`section-status.json` and `project-queue.json` still provide crash/resume behavior while the Kaggle working directory survives, but they do not protect against the Kaggle session being discarded.

Full Kaggle project persistence is still a separate layer. The startup cache does not make `/kaggle/working/OmniVoiceStudio` durable; it only avoids repeated install/model downloads. Project export/sync continues to use the separate Data Management boundary.

## Kaggle notebook

Use:

```text
notebooks/OmniVoice_Project_Studio_Kaggle.ipynb
```

The notebook resolves the exact current master revision, restores a compatible startup cache when available, installs an exact cached/rebuilt wheel, warms model/Whisper assets on local SSD, validates the runtime/GPU, reports free local disk, and launches:

```bash
omnivoice-project-studio \
  --model k2-fsa/OmniVoice \
  --workspace /kaggle/working/OmniVoiceStudio \
  --asr-model openai/whisper-small.en \
  --asr-device cpu \
  --share
```

On dual-T4 Kaggle sessions the production notebook pins OmniVoice to `cuda:0` and Whisper ASR to `cuda:1`; single-GPU sessions fall back to the hardware recommendation. Quality policy remains controlled by SAFE / BALANCED / FAST.

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


## Persistent startup cache

The runtime cache is intentionally separate from the project workspace:

```text
/kaggle/input/omnivoice-startup-cache     read-only cache source (optional)
                 |
                 v
/kaggle/working/.cache/omnivoice          runtime-local hot cache
                 |
                 v
/kaggle/working/OmniVoiceStartupCache     cache export for next Dataset version
```

A compatible attached Dataset activates the fast path. A missing/incompatible
cache falls back to normal network installation/download and produces a new
cache export. See `docs/hosted-runtime-cache.md` for fingerprint and
invalidation rules.
