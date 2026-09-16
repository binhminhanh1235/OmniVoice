# Data Management

OmniVoice Studio separates **normal runtime persistence** from **optional external backup**.

The platform-specific defaults are now:

1. **Kaggle:** keep Studio user data under `/kaggle/working/OmniVoiceStudio` and use Kaggle **Session Persistence → Files only** when cross-session/VM durability is required;
2. **Colab:** use the existing mounted Google Drive workspace/mirror when Drive is mounted;
3. **Storage & Backup:** optional manual Google Drive copy for selected projects/voices, independent of the normal Kaggle startup path.

This separation keeps Kaggle startup simple and prevents model/cache files from inflating the Files-only snapshot.

## Kaggle native Files-only persistence

Kaggle Studio state lives at:

```text
/kaggle/working/OmniVoiceStudio
```

Enable **Session Persistence → Files only** in Kaggle when that state must survive a new session or VM. OmniVoice does not require Google Drive credentials for this path.

The workspace includes normal user state such as:

```text
voices/                  saved voice manifests, encoded prompts and references
projects/                manifests, Studio settings, section state/history/audio
artifacts/               Quick Audio and other standalone artifacts
project-queue.json       Project Queue state
jobs.json                durable AI-native job state
hardware-quality.json    quality settings
advanced-settings.json   advanced settings
```

Heavy reproducible caches are deliberately kept outside `/kaggle/working`:

```text
/tmp/omnivoice/cache
/tmp/omnivoice/bootstrap
```

This includes Hugging Face/model, Torch, Whisper/ASR, pip, wheel and bootstrap caches. Therefore Kaggle Files-only persistence does not have to save/restore the large model cache together with voices and projects.

An optional read-only startup-cache Dataset can still be attached at:

```text
/kaggle/input/omnivoice-startup-cache
```

It accelerates startup but is separate from user-data persistence.

OmniVoice cannot reliably inspect the Kaggle notebook-level persistence toggle, so the runtime reports the backend as `kaggle-files-opt-in`. Cross-session/VM persistence occurs only when the user enables Files only.

## Colab workspace persistence

The maintained Colab notebook keeps the existing Google Drive behavior. When Drive is mounted, OmniVoice can use the mounted `MyDrive/OmniVoiceStudio` location or the notebook-managed local-first mirror as the durable backend.

This Colab behavior is independent of the Kaggle Files-only path.

## Manual project deletion

The Storage & Backup surface supports permanent project deletion. The delete selector starts empty and deletion requires explicit confirmation.

Safety rules:

- only direct children of `<workspace>/projects` containing `project.json` may be deleted;
- symlink projects and path traversal outside the workspace are rejected;
- a project that is actively `running` in Project Queue cannot be deleted;
- a project whose `section-status.json` still reports a section as `queued` or `generating` cannot be deleted;
- non-running Project Queue entries for deleted projects are removed so the queue does not keep stale paths.

On Kaggle, a deletion modifies the same `/kaggle/working/OmniVoiceStudio` tree that Files-only persistence carries. On Colab with the automatic Drive mirror, deletion is propagated to the mirror by the existing Colab persistence layer.

## Manual Google Drive backup

Google Drive sync remains optional. It is useful when you want an additional off-platform copy, want to move selected Studio data between machines, or want a backup independent of Kaggle Files-only persistence.

Manual Drive sync is **not required to start OmniVoice on Kaggle** and is no longer used as the automatic Kaggle persistence backend.

### Runtime rclone installation

If the current runtime does not already have `rclone`, click **Install rclone in this runtime** in Storage & Backup. The installer downloads the official Linux rclone binary for the current architecture into runtime temporary storage and verifies it with `rclone version`.

It does not modify the repository or persist credentials automatically.

### Account selection and token creation

Use a Google OAuth Client ID and Client Secret for a Desktop app. In Storage & Backup:

1. enter the Client ID and Client Secret;
2. click **Generate rclone authorize command**;
3. run that command on a computer with a browser and `rclone` installed;
4. choose the Google account;
5. copy the token JSON printed by `rclone authorize`;
6. paste it into **Authorization token JSON**;
7. click **Connect / replace Google account**.

Running the connection flow with another Google login switches the account for the current runtime.

### Credential storage

OAuth material is never stored in the repository or Studio workspace. Runtime connections are written only to a temporary directory with restrictive permissions where supported.

The Drive remote is supplied to each rclone subprocess through environment variables. OAuth client secrets and access/refresh tokens are not placed on the rclone command line.

Because Kaggle no longer depends on Drive for normal persistence, the Kaggle secrets:

```text
OMNIVOICE_GDRIVE_CLIENT_ID
OMNIVOICE_GDRIVE_CLIENT_SECRET
OMNIVOICE_GDRIVE_TOKEN_JSON
```

are no longer required for OmniVoice startup or Saved Voice / Project persistence.

### What manual sync copies

Selected projects are copied to:

```text
Google Drive/<destination>/projects/<project-id>/
```

The default destination is `OmniVoiceStudio`.

Optional checkboxes also copy:

```text
<workspace>/voices/                -> <destination>/voices/
<workspace>/hardware-quality.json  -> <destination>/hardware-quality.json
```

Manual sync intentionally remains narrower than the complete Studio workspace. On Kaggle, queue/jobs and other Studio state are preserved by Files-only persistence because they remain inside `/kaggle/working/OmniVoiceStudio`; manual Drive backup does not need to be part of every startup/shutdown cycle.

### Manual copy semantics

Manual sync uses `rclone copy`, not `rclone sync`. New or changed local files are uploaded, while extra files already present on Drive are not deleted. This conservative behavior is appropriate for explicit backup/export.

## Recommended Kaggle workflow

For the normal low-overhead path:

```text
1. Enable Session Persistence -> Files only.
2. Run the maintained Kaggle notebook.
3. Keep working normally; Studio reads/writes /kaggle/working/OmniVoiceStudio directly.
4. Let model and dependency caches live under /tmp/omnivoice.
5. Use Storage & Backup only when you explicitly want an additional external copy.
```

This avoids OAuth setup and background Drive synchronization while keeping the persisted Kaggle footprint focused on actual Studio state.
