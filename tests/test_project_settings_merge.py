import json

from omnivoice.cli.project_studio import ProjectStudioController
from omnivoice.project_narration import create_narration_project


SCRIPT = """
# Demo

## S01 — 0:00–0:20
### Opening title
[WARM] This is a short narration sentence.
""".strip()


class FakeVoices:
    pass


class FakeController(ProjectStudioController):
    def __init__(self, workspace):
        self.model = object()
        self.workspace = workspace
        self.projects_root = workspace / "projects"
        self.voices_root = workspace / "voices"
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.voices = FakeVoices()


def test_generation_settings_do_not_erase_project_narration_options(tmp_path):
    project = create_narration_project(
        SCRIPT,
        tmp_path / "projects" / "demo",
        speak_section_titles=True,
    )
    controller = FakeController(tmp_path)
    controller.save_project_narration_settings(
        project,
        speak_section_titles=True,
    )
    controller.save_project_settings(
        project,
        voice_name="Narrator",
        voice_variant="AUTO",
        language="en",
    )

    payload = json.loads((project.root / "studio.json").read_text(encoding="utf-8"))
    assert payload["speak_section_titles"] is True
    assert payload["voice_name"] == "Narrator"
    assert payload["voice_variant"] == "AUTO"
