# Section Version History

Section Version History makes regeneration reversible without breaking project resume checkpoints.

## Automatic snapshots

A snapshot is created automatically before:

- regenerating one chunk from an already generated section;
- forcing a section rerender with Resume disabled.

Manual snapshots are also available from the **Section History** tab.

## Snapshot contents

Each version stores a coherent section checkpoint:

- `Sxx.wav`;
- beat WAV files;
- chunk WAV files;
- per-chunk verification JSON reports;
- section metadata / `ProjectSection` state;
- the project source hash and snapshot reason.

History is stored below the section itself:

```text
sections/S03/history/
├── history.json
├── v0001/
│   ├── section.json
│   ├── S03.wav
│   ├── beats/
│   ├── chunks/
│   ├── metadata.json
│   └── text.txt
└── v0002/
```

The history folder is never copied into a snapshot, so versions do not recursively contain older versions.

## Restore behavior

By default Studio snapshots the current section before restoring an older version. That makes restore itself reversible.

Restoring a version replaces the section's final/beat/chunk generation artifacts and serialized checkpoint state, then synchronizes:

- `project.json`;
- section `metadata.json`;
- `section-status.json`.

This keeps Resume behavior consistent after a restore.

## Script safety

A snapshot records the project source hash. Studio refuses to restore a version whose source hash belongs to a different script revision. This avoids silently attaching old audio/checkpoints to unrelated text.

## UI

Open:

**Project Studio → Section History**

Then select a project and section. You can:

- inspect the version list and snapshot reason;
- play any archived section WAV;
- create a manual snapshot;
- restore a selected version while preserving the current version first.
