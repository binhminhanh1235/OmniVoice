from pathlib import Path

import numpy as np
import soundfile as sf

from omnivoice.project import OmniVoiceProject
from omnivoice.project_queue import ProjectQueueRunner, ProjectQueueStore, queue_rows
from omnivoice.section_status import ensure_section_status, write_section_status


SCRIPT = """# {title}

## S01 — 0:00–0:10

[WARM] First section for {title}.

## S02 — 0:10–0:20

[SOFT] Second section for {title}.
"""


class FakeQueueController:
    def __init__(self, workspace: Path, *, fail_once=None):
        self.workspace = workspace
        self.calls = []
        self.fail_once = fail_once
        self.failed = False

    def load_project(self, project_path):
        project = OmniVoiceProject.load(project_path)
        ensure_section_status(project)
        return project

    def load_project_settings(self, project):
        return {
            "voice_name": "Narrator",
            "voice_variant": "AUTO",
            "language": "en",
        }

    def generate(
        self,
        project_path,
        *,
        voice_name,
        voice_variant="AUTO",
        language="en",
        section_ids=None,
        resume=True,
        strict=False,
    ):
        project = self.load_project(project_path)
        section_id = list(section_ids or [])[0]
        key = (project.manifest.title, section_id)
        self.calls.append(key)
        if self.fail_once == key and not self.failed:
            self.failed = True
            raise RuntimeError("synthetic generation failure")

        section = project.get_section(section_id)
        section_dir = project.root / "sections" / section.id
        section_dir.mkdir(parents=True, exist_ok=True)
        wav_path = section_dir / f"{section.id}.wav"
        sf.write(wav_path, np.zeros(2400, dtype=np.float32), 24000)
        section.audio_file = str(wav_path.relative_to(project.root))
        section.status = "verified"
        for beat in section.beats:
            beat.status = "verified"
            for chunk in beat.chunks:
                chunk.status = "verified"
        project.save()
        write_section_status(project)
        return project

    def merge_project(self, project_path, *, require_verified=True):
        project = self.load_project(project_path)
        path = project.root / "output" / "full.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(path, np.zeros(2400, dtype=np.float32), 24000)
        return path


def make_project(workspace: Path, title: str) -> OmniVoiceProject:
    project = OmniVoiceProject.create(
        SCRIPT.format(title=title),
        workspace / "projects" / title.lower().replace(" ", "-"),
    )
    ensure_section_status(project)
    return project


def test_queue_runs_multiple_projects_in_order(tmp_path):
    controller = FakeQueueController(tmp_path)
    projects = [make_project(tmp_path, title) for title in ("Alpha", "Beta", "Gamma")]
    store = ProjectQueueStore(tmp_path)
    for project in projects:
        store.enqueue(controller, project.root, auto_merge=True)

    events = list(ProjectQueueRunner(controller, store).run())
    manifest = store.load()

    assert controller.calls == [
        ("Alpha", "S01"),
        ("Alpha", "S02"),
        ("Beta", "S01"),
        ("Beta", "S02"),
        ("Gamma", "S01"),
        ("Gamma", "S02"),
    ]
    assert all(item.status == "completed" for item in manifest.items)
    assert all(item.completed_sections == 2 for item in manifest.items)
    assert all(item.merged_audio for item in manifest.items)
    assert events[-1].project_title == "Gamma"


def test_queue_restarts_from_failed_project_without_repeating_completed_work(tmp_path):
    projects = [make_project(tmp_path, title) for title in ("Alpha", "Beta", "Gamma")]
    store = ProjectQueueStore(tmp_path)
    first = FakeQueueController(tmp_path, fail_once=("Beta", "S02"))
    for project in projects:
        store.enqueue(first, project.root, auto_merge=False)

    list(ProjectQueueRunner(first, store).run(continue_on_error=False))
    after_failure = store.load()
    assert after_failure.items[0].status == "completed"
    assert after_failure.items[1].status == "failed"
    assert after_failure.items[1].completed_sections == 1
    assert after_failure.items[2].status == "pending"

    second = FakeQueueController(tmp_path)
    list(ProjectQueueRunner(second, store).run())

    assert ("Alpha", "S01") not in second.calls
    assert ("Alpha", "S02") not in second.calls
    assert second.calls == [
        ("Beta", "S02"),
        ("Gamma", "S01"),
        ("Gamma", "S02"),
    ]
    assert all(item.status == "completed" for item in store.load().items)


def test_recover_interrupted_running_item_as_pending(tmp_path):
    controller = FakeQueueController(tmp_path)
    project = make_project(tmp_path, "Alpha")
    store = ProjectQueueStore(tmp_path)
    store.enqueue(controller, project.root)

    manifest = store.load()
    manifest.items[0].status = "running"
    manifest.items[0].current_section = "S01"
    manifest.paused = True
    store.save(manifest)

    recovered = store.recover_interrupted()
    assert recovered.items[0].status == "pending"
    assert recovered.paused is False
    assert "Recovered after interrupted runtime" in (recovered.items[0].error or "")


def test_duplicate_active_project_is_rejected(tmp_path):
    controller = FakeQueueController(tmp_path)
    project = make_project(tmp_path, "Alpha")
    store = ProjectQueueStore(tmp_path)
    item = store.enqueue(controller, project.root)

    for status in ("pending", "failed", "needs_review"):
        manifest = store.load()
        manifest.items[0].status = status
        store.save(manifest)
        try:
            store.enqueue(controller, project.root)
        except ValueError as exc:
            assert "already queued" in str(exc)
        else:
            raise AssertionError(f"Expected duplicate {status} project to be rejected")

    assert store.load().items[0].id == item.id


def test_running_item_cannot_be_removed_or_requeued(tmp_path):
    controller = FakeQueueController(tmp_path)
    project = make_project(tmp_path, "Alpha")
    store = ProjectQueueStore(tmp_path)
    item = store.enqueue(controller, project.root)

    manifest = store.load()
    manifest.items[0].status = "running"
    store.save(manifest)

    for action in (store.remove, store.requeue):
        try:
            action(item.id)
        except ValueError as exc:
            assert "running project" in str(exc)
        else:
            raise AssertionError("Expected running queue mutation to be blocked")


def test_future_pending_item_can_be_removed_while_queue_is_running(tmp_path):
    controller = FakeQueueController(tmp_path)
    alpha = make_project(tmp_path, "Alpha")
    beta = make_project(tmp_path, "Beta")
    store = ProjectQueueStore(tmp_path)
    store.enqueue(controller, alpha.root, auto_merge=False)
    beta_item = store.enqueue(controller, beta.root, auto_merge=False)

    events = ProjectQueueRunner(controller, store).run()
    first_event = next(events)
    assert first_event.project_title == "Alpha"
    store.remove(beta_item.id)

    list(events)
    assert controller.calls == [("Alpha", "S01"), ("Alpha", "S02")]
    assert [item.project_title for item in store.load().items] == ["Alpha"]


def test_queue_rows_include_progress_and_item_id(tmp_path):
    controller = FakeQueueController(tmp_path)
    project = make_project(tmp_path, "Alpha")
    store = ProjectQueueStore(tmp_path)
    item = store.enqueue(controller, project.root, auto_merge=False)

    rows = queue_rows(store.load())
    assert rows[0][1] == "Alpha"
    assert rows[0][2] == "PENDING"
    assert rows[0][3] == "0/2"
    assert rows[0][-1] == item.id
