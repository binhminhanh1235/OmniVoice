# Data Management

OmniVoice Studio now has two complementary Google Drive workflows:

1. **automatic hosted workspace persistence** for keeping the complete Colab/Kaggle Studio state durable across runtime restarts;
2. **manual Storage & Backup sync** for explicitly copying selected projects and optional supporting data.

These workflows share the same rclone/Google Drive transport but have different semantics. Automatic persistence is the durability layer; manual sync remains an explicit backup/export tool.

## Automatic hosted workspace persistence

Hosted runtimes should keep generation on their fast local SSD while treating external storage as the durable mirror.

### Colab

The maintained Colab notebook mounts Google Drive, executes Studio from `/content/OmniVoiceStudio`, restores from `MyDrive/OmniVoiceStudio`, then mirrors the full durable workspace back to Drive. Direct launcher use also detects mounted Drive and applies the same persistence contract when the notebook does not already own the mirror.

### Kaggle

Kaggle `/kaggle/working` is ephemeral. To make Saved Voice, projects and the rest of Studio state survive a discarded session, configure these **Kaggle Secrets once**:

```text
OMNIVOICE_GDRIVE_CLIENT_ID
OMNIVOICE_GDRIVE_CLIENT_SECRET
OMNIVOICE_GDRIVE_TOKEN_JSON
```

Optional settings:

```text
OMNIVOICE_GDRIVE_DESTINATION=OmniVoiceStudio
OMNIVOICE_PERSISTENCE_INTERVAL_SECONDS=15
```

The token JSON is the value returned by the normal `rclone authorize drive ...` flow described below. Store the complete JSON object as the Kaggle Secret value.

At each Kaggle start OmniVoice stages those credentials into runtime-only storage, restores the full Studio workspace from Drive **before** model/UI startup, mirrors changes while Studio is running, and performs a final sync on graceful shutdown.

The automatic mirror covers normal Studio state including:

```text
voices/                  saved voice manifests, encoded prompts and references
projects/                manifests, Studio settings, section state/history/audio
artifacts/               Quick Audio and other standalone artifacts
project-queue.json       Project Queue state
jobs.json                durable AI-native job state
hardware-quality.json    quality settings
advanced-settings.json   advanced settings
```

Startup cache/evidence, temporary files and NFS scratch files are excluded because they belong to the runtime/cache subsystem rather than user state.

Queue/job paths are rebased after restore, so a workspace mirrored from Colab can resume on Kaggle and vice versa without retaining stale `/content/OmniVoiceStudio/...` or `/kaggle/working/OmniVoiceStudio/...` paths.

If Kaggle persistence secrets are missing, Studio still starts and logs an explicit warning that the workspace is ephemeral. It does not silently claim that local SSD data is durable.

## Manual project deletion

The Storage & Backup surface also supports permanent project deletion. The delete selector starts empty and deletion requires the explicit confirmation checkbox.

Safety rules:

- only direct children of `<workspace>/projects` containing `project.json` may be deleted;
- symlink projects and path traversal outside the workspace are rejected;
- a project that is actively `running` in Project Queue cannot be deleted;
- a project whose `section-status.json` still reports a section as `queued` or `generating` cannot be deleted, which also protects direct Generate / Resume jobs outside Project Queue;
- non-running Project Queue entries for deleted projects are removed so the queue does not keep stale paths.

With automatic full-workspace persistence enabled, that deletion is propagated to the persistent mirror on the next sync, so a deliberately deleted project is not resurrected after restart.

## Manual Google Drive sync

Manual Drive sync uses `rclone` and remains optional. It is useful when you want to copy selected projects without enabling automatic whole-workspace persistence.

### Runtime rclone installation

If the current Kaggle/Colab runtime does not already have `rclone`, click **Install rclone in this runtime** in Storage & Backup. The installer downloads the official Linux rclone archive for the current architecture, extracts only the `rclone` binary under the runtime temporary directory, marks it executable, adds that temporary bin directory to the current process `PATH`, and verifies it with `rclone version`.

It does not modify the repository, notebook image, or persistent credentials. A new hosted runtime can install its own temporary copy again.

### Account selection and token creation

Use a Google OAuth Client ID and Client Secret for a Desktop app. In Storage & Backup:

1. enter the Client ID and Client Secret;
2. click **Generate rclone authorize command**;
3. run that command on a computer with a browser and `rclone` installed;
4. Google opens its normal account chooser;
5. choose the Google account you want to use;
6. copy the token JSON printed by `rclone authorize`;
7. paste it into **Authorization token JSON**;
8. click **Connect / replace Google account**.

For one-time Kaggle automatic persistence setup, save the same Client ID, Client Secret and returned token JSON as the three Kaggle Secrets listed above. Future sessions can then reconnect without pasting credentials into Studio again.

Running the manual connection flow with another Google login switches the account for the current runtime.

### Credential storage

OAuth material is never stored in the repository or Studio workspace. Runtime connections are written only to a temporary directory with permission `0600` where supported. Kaggle automatic persistence reads encrypted Kaggle Secrets and stages them into that same runtime-only credential store.

The Drive remote is supplied to each rclone subprocess through environment variables. OAuth client secrets and access/refresh tokens are not placed on the rclone command line.

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

Manual sync intentionally remains narrower than automatic persistence. Project Queue/jobs and the rest of the workspace are handled by the automatic persistence layer instead.

### Manual copy semantics

Manual sync uses `rclone copy`, not `rclone sync`. New or changed local files are uploaded, while extra files already present on Drive are not deleted. This conservative behavior is appropriate for an explicit backup/export action.

Automatic hosted persistence uses mirror semantics instead, including deletion propagation, because its destination represents the current durable Studio workspace rather than an archival copy.
