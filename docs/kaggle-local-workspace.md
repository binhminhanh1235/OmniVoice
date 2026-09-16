# Kaggle local execution and Files-only persistence

OmniVoice Studio keeps the active Kaggle workspace on the fast writable filesystem at:

```text
/kaggle/working/OmniVoiceStudio
```

For persistence across Kaggle sessions and replacement VMs, enable **Session Persistence → Files only** in the Kaggle notebook settings. OmniVoice deliberately keeps heavy startup/model caches outside `/kaggle/working`, so Kaggle only needs to carry the Studio data that is expensive or impossible to recreate.

No Google Drive OAuth, client secret, refresh token, or automatic Drive mirror is required for the normal Kaggle workflow.

## Runtime layout

```text
/kaggle/working/OmniVoiceStudio/     # user state; eligible for Files-only persistence
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

/tmp/omnivoice/cache/                # heavy runtime cache; NOT persisted by Files only
  <cache-key>/
    pip/
    wheels/
    huggingface/
    torch/
    whisper/

/tmp/omnivoice/bootstrap/            # temporary bootstrap/wheel workspace

/kaggle/input/omnivoice-startup-cache/  # optional read-only warm-cache Dataset
```

`/kaggle/input` is read-only source material. It can contain scripts, reference audio, or the optional startup-cache Dataset, but Studio never writes active projects or saved voices there.

## Why this is faster than persisting all of `/kaggle/working`

Kaggle Files-only persistence snapshots files under `/kaggle/working`. Model downloads, Hugging Face snapshots, Torch caches, pip wheels, Whisper caches, and bootstrap files can be many gigabytes and contain thousands of files. Persisting those together with the user workspace makes session restore/save much heavier than necessary.

OmniVoice therefore uses a split-storage contract:

```text
small durable state  -> /kaggle/working/OmniVoiceStudio
heavy reproducible cache -> /tmp/omnivoice
```

The result is that Files-only persistence focuses on Saved Voice, Projects, resume state, settings, and generated Studio artifacts instead of carrying the model warehouse on every VM transition.

## What survives with Files only enabled

The complete Studio workspace under `/kaggle/working/OmniVoiceStudio` is eligible to be carried to the next Kaggle session/VM, including:

```text
voices/                  saved voice manifests, encoded prompts and references
projects/                project manifests, Studio settings, section state/history/audio
artifacts/               Quick Audio and other standalone artifacts
project-queue.json       Project Queue state
jobs.json                durable AI-native job state
hardware-quality.json    quality defaults
advanced-settings.json   advanced Studio settings
```

Studio reads these files directly at startup. It does not copy them into a second internal persistence tree, so restarting the OmniVoice process in the same runtime also reuses the same state immediately.

OmniVoice cannot query Kaggle's notebook-level Session Persistence switch reliably, so the runtime summary remains conservative and calls this backend `kaggle-files-opt-in`. The user must enable **Files only** in Kaggle for cross-session/VM durability.

## What is intentionally not persisted by Files only

Heavy/reproducible runtime resources are kept under `/tmp/omnivoice`:

```text
Hugging Face model cache
Torch cache
Whisper / ASR cache
pip cache
built wheel cache
bootstrap scratch files
```

They disappear with the VM. That is intentional: it keeps the persisted notebook footprint small.

For faster model startup on a new VM, attach the separately managed startup-cache Dataset at:

```text
/kaggle/input/omnivoice-startup-cache
```

The bootstrap validates its compatibility/inventory and restores it into `/tmp/omnivoice/cache`. If the Dataset is absent or invalid, Studio uses the normal cold-download path without risking user data.

## Optional startup-cache Dataset

The startup-cache Dataset and Studio Files-only persistence solve different problems:

- **Files only** preserves user state such as voices and projects.
- **`omnivoice-startup-cache` Dataset** optionally accelerates dependency/model startup.

A runtime cache prepared under `/tmp/omnivoice/cache` can still be intentionally packaged/versioned as the `omnivoice-startup-cache` Dataset when you want a new warm-cache snapshot. It is no longer exported automatically into `/kaggle/working/OmniVoiceStartupCache`, because doing so would make Files-only persistence carry those large files again.

## Google Drive on Kaggle

Google Drive remains available from **Settings → Storage & Backup** as an optional manual backup/export destination. It is no longer part of Kaggle startup persistence and no Kaggle secrets named `OMNIVOICE_GDRIVE_CLIENT_ID`, `OMNIVOICE_GDRIVE_CLIENT_SECRET`, or `OMNIVOICE_GDRIVE_TOKEN_JSON` are required for normal startup.

Use manual Drive backup only when you want an additional off-Kaggle copy or need to move selected projects/voices elsewhere.

## Colab behavior

Colab keeps its existing behavior. The maintained Colab notebook can use mounted Google Drive as the durable workspace/mirror while generation stays on the local runtime path where appropriate. The Kaggle Files-only design does not change Colab persistence.

## Kaggle notebooks

Use either:

```text
notebooks/OmniVoice_Project_Studio_Kaggle.ipynb
```

or:

```text
notebooks/OmniVoice_Project_Studio_Kaggle_Gradio.ipynb
```

Before a production run that must survive a new Kaggle VM, enable:

```text
Session Persistence -> Files only
```

The notebooks keep Studio state at `/kaggle/working/OmniVoiceStudio` and heavy caches under `/tmp/omnivoice`.

## Operational caveat

Files-only persistence is a platform persistence mechanism, not an archival backup. For irreplaceable voices or completed production projects, an occasional manual external backup is still sensible. That backup is independent of the fast normal startup path and does not consume every session with automatic Drive synchronization.
