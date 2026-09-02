# Project Status Filter

Project Queue derives a lightweight render status from each project's existing `section-status.json` instead of introducing another persistence file.

## Status precedence

```text
all complete          -> DONE
queued/generating     -> GENERATING
unverified            -> NEEDS_REVIEW
failed                -> FAILED
otherwise             -> PENDING
```

The default Queue browser filter is `PENDING + GENERATING`. `DONE` projects remain hidden unless explicitly requested.

Projects already represented in `project-queue.json` are also hidden from the browser, so a large workspace presents only useful queue candidates.

For bulk workflows, **Add ALL filtered projects using saved settings** queues every visible candidate and reads each project's own `studio.json` voice / variant / language settings.
