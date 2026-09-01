# Project Queue

Project Queue renders multiple existing OmniVoice Studio projects continuously.

It is designed for long Colab jobs where one project may contain many sections and the runtime may disconnect before the full batch finishes.

## Persistence model

Queue state lives at:

```text
<workspace>/project-queue.json
```

Each project still owns its normal:

```text
<project>/project.json
<project>/section-status.json
```

The queue answers **which project comes next**. `section-status.json` answers **which section inside that project still needs work**.

Project-level render status is deliberately **derived** from `section-status.json`; there is no third project-status sidecar that could drift out of sync.

## Project render status

The Project Browser derives these statuses:

```text
DONE          every section is verified/complete
GENERATING    one or more sections are queued or generating
NEEDS_REVIEW  no section is generating, but at least one is unverified
FAILED        no section is generating, but at least one section is failed
PENDING       remaining work that has not reached one of the states above
```

These are **project render statuses**. They are separate from queue statuses such as `RUNNING`, `PAUSED`, and `COMPLETED`.

The Queue UI defaults to:

```text
☑ PENDING
☑ GENERATING
☐ NEEDS_REVIEW
☐ FAILED
☐ DONE
```

This keeps a workspace with hundreds of old projects focused on the small set that still needs work. `DONE` projects remain available by explicitly enabling that filter.

Projects already present in `project-queue.json` are hidden from the Project Browser so they cannot be accidentally selected twice.

The browser table shows:

- project render status;
- title;
- completed / total sections;
- active section when one is generating;
- last status update;
- project path.

The dropdown label also includes status and progress, for example:

```text
[PENDING 3/11] Video A
[GENERATING 7/11] Video B
```

## Batch add by status

For large workspaces, the Queue UI has:

```text
Add ALL filtered projects using saved settings
```

This adds every currently eligible project shown by the status filter. Each project uses its own saved `studio.json` voice / variant / language settings instead of applying one global voice to the entire batch.

Projects without valid saved voice settings are skipped and reported rather than poisoning the whole batch operation.

## Runtime behavior

For a queue such as:

```text
Project A
Project B
Project C
```

Studio runs:

```text
Project A / S01
Project A / S02
...
Project A / done
Project B / S01
...
Project C / done
```

Generation is invoked one section at a time. Queue state is written after every transition.

If Colab disconnects during `Project B / S05`:

```text
Project A        COMPLETED
Project B / S01  verified
Project B / S02  verified
Project B / S03  verified
Project B / S04  verified
Project B / S05  interrupted
Project C        PENDING
```

After reopening Studio and running the queue again:

```text
Project A        skipped
Project B        resumes unfinished sections
Project C        runs after Project B
```

Completed sections are not generated again as long as their verified section WAV still exists.

## Queue item settings

Each queued project stores:

- project path and title;
- voice name;
- voice variant (`AUTO`, `WARM`, `SOFT`, ...);
- language;
- strict-verification preference;
- auto-merge preference;
- current project/section progress;
- attempts and error message;
- optional merged `full.wav` path.

Changing another project's settings later does not silently mutate an already queued item's saved generation settings.

## Queue statuses

```text
PENDING       waiting to run
RUNNING       currently rendering
PAUSED        pause requested before next section
COMPLETED     all sections verified
NEEDS_REVIEW  render pass ended but one or more sections remain unverified
FAILED        an exception stopped that project
CANCELLED     intentionally skipped/removed from execution
```

A failed or needs-review item can be requeued. Resume semantics still skip any sections that are already complete.

## Failure policy

The UI exposes:

```text
Continue with next project if one project fails
```

When enabled, one bad project does not strand the rest of the overnight queue.

When disabled, the runner stops after the failed project so the operator can inspect it immediately.

## Pause behavior

`Pause after current section` is cooperative. It does not kill an in-flight GPU generation. The runner finishes the current section/checkpoint, then stops before starting the next section.

This avoids corrupting project state.

## Auto merge

When enabled for a queue item, Studio calls the existing verified-project merge after all sections complete and stores the resulting `full.wav` path in the queue manifest.

A merge failure does not erase successful section generation. The project remains completed and the merge error is retained for review.

## UI workflow

1. Create/save projects normally in **Project Studio**.
2. Open **4. Project Queue**.
3. Keep the default **PENDING + GENERATING** filter, or enable another status when needed.
4. Add one selected project, or use **Add ALL filtered projects using saved settings**.
5. Reorder with **Up / Down** if needed.
6. Click **Run Queue**.
7. Leave Colab running.
8. If the runtime disconnects, reopen the same Drive workspace and click **Run Queue** again.

The queue and the project section checkpoints are both persisted under the shared Studio workspace.
