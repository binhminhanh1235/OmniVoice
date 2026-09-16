# Kaggle local execution workspace

Project Studio treats Kaggle local SSD as an **execution workspace** and mirrors durable Studio state to external persistence when configured.

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
  artifacts/
  project-queue.json
  jobs.json
  hardware-quality.json
  advanced-settings.json
```

`/kaggle/input` is read-only source material. It can contain scripts or reference audio supplied through Kaggle datasets, but Project Studio never writes active projects, checkpoints, queue state, saved voices, jobs, or generated WAVs there.

## Why local-first

Long-form generation creates many small checkpoint/report/audio files. Keeping the active project on Kaggle local storage avoids remote-filesystem latency and keeps the existing section/chunk resume logic unchanged.

Durability is handled out-of-band. On startup, OmniVoice can restore the complete Studio workspace from Google Drive into local SSD. While Studio is running it mirrors durable state periodically and performs a final sync on graceful shutdown.

This full-workspace persistence covers saved voices, projects, queue/jobs, quality/advanced settings and generated artifacts. Startup cache metadata/evidence stays separate and is excluded from the user-data mirror.

## Default workspace detection

`omnivoice.runtime_workspace.detect_runtime_workspace()` selects:

```text
Kaggle  -> /kaggle/working/OmniVoiceStudio
Colab   -> runtime detector may expose mounted MyDrive; the production Colab notebook explicitly runs generation from /content/OmniVoiceStudio and mirrors persistence outside the render hot path
Local   -> ./OmniVoiceStudio
```

`OMNIVOICE_STUDIO_HOME` overrides the default on every platform.

Kaggle is detected by its environment variables or by the presence of `/kaggle/working`.

## Automatic persistence on Kaggle

Kaggle local SSD is discarded with the hosted session, so persistence requires an external backend. OmniVoice supports a Google Drive mirror without putting OAuth credentials in the repository or Studio workspace.

Configure these **Kaggle Secrets once**:

```text
OMNIVOICE_GDRIVE_CLIENT_ID
OMNIVOICE_GDRIVE_CLIENT_SECRET
OMNIVOICE_GDRIVE_TOKEN_JSON
```

Optional:

```text
OMNIVOICE_GDRIVE_DESTINATION=OmniVoiceStudio
OMNIVOICE_PERSISTENCE_INTERVAL_SECONDS=15
```

At Studio startup OmniVoice:

1. reads those secrets through Kaggle's secret API;
2. keeps the OAuth material only in runtime-only storage;
3. installs/reuses runtime `rclone` when needed;
4. creates the Drive destination if it does not exist;
5. restores the complete durable Studio workspace before the model/UI becomes active;
6. mirrors local changes back to Drive while Studio is running;
7. flushes once more on graceful shutdown.

The default Drive mirror is:

```text
Google Drive/OmniVoiceStudio/
```

If the secrets are missing, Studio still starts, but logs an explicit warning that the Kaggle workspace is ephemeral instead of silently implying durability.

## What survives restart

With automatic persistence enabled, the mirror includes at least:

```text
voices/                 saved voice manifests, prompts, references
projects/               project.json, studio.json, section state/history/audio
artifacts/              standalone/Quick Audio artifacts
project-queue.json       queue state
jobs.json                durable AI-native job state
hardware-quality.json    quality defaults
advanced-settings.json   advanced Studio settings
```

Deleted local projects are also deleted from the mirror on the next sync so they are not resurrected during a later restore.

The following runtime/cache evidence is deliberately excluded:

```text
.startup-cache/
.startup-evidence/
.runtime-cache.json
startup-cache-evidence.json
*.tmp
.nfs*
```

## Colab behavior

The maintained Colab notebook mounts Google Drive and already uses a local-first `/content/OmniVoiceStudio` execution workspace with a persistent `MyDrive/OmniVoiceStudio` mirror. The launcher detects that notebook-owned mirror and does not start a second competing mirror thread.

If Studio is launched directly on Colab outside the maintained notebook, the launcher can use the mounted `MyDrive/OmniVoiceStudio` directory as the same full-workspace persistence backend.

## Kaggle notebook

Use:

```text
notebooks/OmniVoice_Project_Studio_Kaggle.ipynb
```

or the full Gradio notebook:

```text
notebooks/OmniVoice_Project_Studio_Kaggle_Gradio.ipynb
```

Both launchers use the same hosted persistence contract, so saved voices and projects are restored before UI/server startup when the Kaggle Secrets above are configured.

On dual-T4 Kaggle sessions the production notebook pins OmniVoice to `cuda:0` and Whisper ASR to `cuda:1`; single-GPU sessions fall back to the hardware recommendation. Quality policy remains controlled by SAFE / BALANCED / FAST.

## Persistent startup cache

The runtime cache is intentionally separate from the Studio data mirror:

```text
/kaggle/input/omnivoice-startup-cache     read-only cache source (optional)
                 |
                 v
/kaggle/working/.cache/omnivoice          runtime-local hot cache
                 |
                 v
/kaggle/working/OmniVoiceStartupCache     cache export for next Dataset version
```

A compatible attached Dataset activates the fast path. A missing/incompatible cache falls back to normal network installation/download and produces a new cache export. See `docs/hosted-runtime-cache.md` for fingerprint and invalidation rules.
