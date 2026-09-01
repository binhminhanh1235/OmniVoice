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

This separation is intentional.

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

## Statuses

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
3. Choose project, voice/variant/language and queue preferences.
4. Add projects in the desired order.
5. Reorder with **Up / Down** if needed.
6. Click **Run Queue**.
7. Leave Colab running.
8. If the runtime disconnects, reopen the same Drive workspace and click **Run Queue** again.

The queue and the project section checkpoints are both persisted under the shared Studio workspace.
