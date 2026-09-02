from pathlib import Path

import pytest

from omnivoice.project import OmniVoiceProject
from omnivoice.section_status import write_section_status
from omnivoice.services.job_manager import JobCancelled
from omnivoice.services.studio_commands import StudioCommandService


SCRIPT = """# Command Test

## S01 — 0:00–0:10
[WARM] First section text for generation.

## S02 — 0:10–0:20
[SOFT] Second section text for generation.

## S03 — 0:20–0:30
Third section text for generation.
"""


class FakeController:
    def __init__(self, *, settings=None, unverified=None):
        self.settings = dict(settings or {})
        self.unverified = set(unverified or [])
        self.calls = []

    def load_project(self, project_path):
        return OmniVoiceProject.load(project_path)

    def load_project_settings(self, project):
        return dict(self.settings)

    def generate(self, project_path, **kwargs):
        section_id = list(kwargs["section_ids"])[0]
        self.calls.append((section_id, kwargs))
        project = OmniVoiceProject.load(project_path)
        section = project.get_section(section_id)
        audio = project.root / "sections" / section_id / f"{section_id}.wav"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"fake-wav")
        section.audio_file = str(audio.relative_to(project.root))
        section.status = "unverified" if section_id in self.unverified else "verified"
        project.save()
        write_section_status(project)
        return project


class FakeContext:
    def __init__(self, payload, *, cancel_after_checkpoints=None):
        self.payload = payload
        self.events = []
        self.checkpoints = 0
        self.cancel_after_checkpoints = cancel_after_checkpoints

    def emit(self, message, *, progress=None, event="progress", data=None):
        self.events.append(
            {
                "message": message,
                "progress": progress,
                "event": event,
                "data": data or {},
            }
        )

    def checkpoint(self):
        self.checkpoints += 1
        if (
            self.cancel_after_checkpoints is not None
            and self.checkpoints > self.cancel_after_checkpoints
        ):
            raise JobCancelled("cancelled by test")


def create_project(tmp_path: Path):
    return OmniVoiceProject.create(
        SCRIPT,
        tmp_path / "studio" / "projects" / "command-test",
    )


def mark_verified(project: OmniVoiceProject, section_id: str):
    section = project.get_section(section_id)
    audio = project.root / "sections" / section_id / f"{section_id}.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"existing")
    section.audio_file = str(audio.relative_to(project.root))
    section.status = "verified"
    project.save()
    write_section_status(project)


def test_generation_uses_saved_voice_and_runs_section_by_section(tmp_path):
    project = create_project(tmp_path)
    controller = FakeController(
        settings={
            "voice_name": "Narrator",
            "voice_variant": "WARM",
            "language": "en",
            "quality_preset": "BALANCED",
        }
    )
    commands = StudioCommandService(None, tmp_path / "studio", controller=controller)
    ctx = FakeContext({"project_path": str(project.root), "resume": True})

    result = commands.generate_project_job(ctx)

    assert [section_id for section_id, _ in controller.calls] == ["S01", "S02", "S03"]
    assert controller.calls[0][1]["voice_name"] == "Narrator"
    assert controller.calls[0][1]["voice_variant"] == "WARM"
    assert controller.calls[0][1]["language"] == "en"
    assert controller.calls[0][1]["quality_preset"] == "BALANCED"
    assert result["project_status"] == "DONE"
    assert result["completed_sections"] == 3
    assert [event["event"] for event in ctx.events].count("section.started") == 3
    assert ctx.events[-1]["event"] == "project.finished"


def test_resume_skips_already_verified_section(tmp_path):
    project = create_project(tmp_path)
    mark_verified(project, "S01")
    controller = FakeController(settings={"voice_name": "Narrator"})
    commands = StudioCommandService(None, tmp_path / "studio", controller=controller)
    ctx = FakeContext({"project_path": str(project.root), "resume": True})

    result = commands.generate_project_job(ctx)

    assert [section_id for section_id, _ in controller.calls] == ["S02", "S03"]
    assert result["project_status"] == "DONE"


def test_requested_sections_are_validated_and_project_order_is_preserved(tmp_path):
    project = create_project(tmp_path)
    controller = FakeController(settings={"voice_name": "Narrator"})
    commands = StudioCommandService(None, tmp_path / "studio", controller=controller)

    ctx = FakeContext(
        {
            "project_path": str(project.root),
            "sections": ["s03", "S01"],
            "resume": True,
        }
    )
    commands.generate_project_job(ctx)
    assert [section_id for section_id, _ in controller.calls] == ["S01", "S03"]

    bad = FakeContext(
        {"project_path": str(project.root), "sections": ["S99"], "resume": True}
    )
    with pytest.raises(ValueError, match="Unknown sections: S99"):
        commands.generate_project_job(bad)


def test_cancellation_is_honored_between_sections_only(tmp_path):
    project = create_project(tmp_path)
    controller = FakeController(settings={"voice_name": "Narrator"})
    commands = StudioCommandService(None, tmp_path / "studio", controller=controller)
    ctx = FakeContext(
        {"project_path": str(project.root), "resume": True},
        cancel_after_checkpoints=1,
    )

    with pytest.raises(JobCancelled):
        commands.generate_project_job(ctx)

    assert [section_id for section_id, _ in controller.calls] == ["S01"]
    assert any(event["event"] == "section.finished" for event in ctx.events)


def test_unverified_section_completes_job_with_needs_review_result(tmp_path):
    project = create_project(tmp_path)
    controller = FakeController(
        settings={"voice_name": "Narrator"},
        unverified={"S02"},
    )
    commands = StudioCommandService(None, tmp_path / "studio", controller=controller)
    ctx = FakeContext({"project_path": str(project.root), "resume": True})

    result = commands.generate_project_job(ctx)

    assert result["project_status"] == "NEEDS_REVIEW"
    by_id = {item["section_id"]: item["status"] for item in result["generated_sections"]}
    assert by_id["S02"] == "unverified"


def test_missing_saved_voice_is_rejected_before_generation(tmp_path):
    project = create_project(tmp_path)
    controller = FakeController(settings={})
    commands = StudioCommandService(None, tmp_path / "studio", controller=controller)
    ctx = FakeContext({"project_path": str(project.root)})

    with pytest.raises(ValueError, match="no saved voice"):
        commands.generate_project_job(ctx)
    assert controller.calls == []
