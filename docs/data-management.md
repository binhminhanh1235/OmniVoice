# Data Management

Project Studio exposes **8. Data Management** for two optional maintenance tasks:

1. permanently delete one or many local projects;
2. copy selected Studio data to a Google Drive account chosen at runtime.

## Delete projects

The delete selector starts empty. Deletion requires the explicit confirmation checkbox.

Safety rules:

- only direct children of `<workspace>/projects` containing `project.json` may be deleted;
- symlink projects and path traversal outside the workspace are rejected;
- a project that is actively `running` in Project Queue cannot be deleted;
- a project whose `section-status.json` still reports a section as `queued` or `generating` cannot be deleted, which also protects direct Generate / Resume jobs outside Project Queue;
- non-running Project Queue entries for deleted projects are removed so the queue does not keep stale paths.

Deletion is permanent and does not move a project to a trash folder.

## Optional Google Drive sync

Google Drive sync uses `rclone` and is deliberately optional. OmniVoice does not hard-code a Google account.

### Runtime rclone installation

If the current Kaggle/Colab runtime does not already have `rclone`, click **Install rclone in this runtime** in Data Management. The installer is opt-in and downloads the official Linux rclone archive for the current architecture, extracts only the `rclone` binary under the runtime temporary directory, marks it executable, adds that temporary bin directory to the current process `PATH`, and verifies it with `rclone version`.

It does not modify the repository, Studio workspace, notebook image, or Google Drive. A new hosted runtime can install its own temporary copy again.

### Account selection

Use a Google OAuth Client ID and Client Secret for a Desktop app. In the Data Management tab:

1. enter the Client ID and Client Secret;
2. click **Generate rclone authorize command**;
3. run that command on a computer with a browser and `rclone` installed;
4. Google opens its normal account chooser;
5. choose the Google account you want to use;
6. copy the token JSON printed by `rclone authorize`;
7. paste it into **Authorization token JSON**;
8. click **Connect / replace Google account**.

Running the flow again with another Google login switches the account for the current runtime.

The current rclone documentation recommends using your own Google OAuth Client ID because the shared rclone Google Drive client ID is being retired during 2026.

### Credential storage

OAuth material is never stored in the repository and is not stored inside the Studio workspace. It is written only to a runtime temporary directory with permission `0600` where supported.

This matters for Colab because the Studio workspace may itself live on a mounted Google Drive. Restarting the runtime removes the temporary connection and allows a different Google account to be selected next time.

The Drive remote is supplied to each rclone subprocess through environment variables. OAuth client secrets and access/refresh tokens are not placed on the rclone command line.

### What is synced

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

Project Queue state and Google OAuth credentials are intentionally not uploaded.

### Copy semantics

Sync uses `rclone copy`, not `rclone sync`.

That means new or changed local files are uploaded, but extra files already present on Google Drive are not deleted. This is safer for an optional backup/persistence workflow.

## Kaggle and Colab

For Kaggle/Colab, the normal flow is:

1. click **Install rclone in this runtime** if `rclone` is unavailable;
2. generate the authorization command in Studio;
3. run that authorization command on a computer with a browser;
4. choose the desired Google account and paste the returned token into Studio;
5. choose one or more projects and click **Sync selected to Google Drive**.

The OAuth authorization step itself should be run on a machine with a browser. This is the normal rclone remote-authorization flow for headless environments such as Kaggle.
