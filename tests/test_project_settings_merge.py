import json

from omnivoice.cli.unified_controller import UnifiedWorkspaceController
from omnivoice.project_narration import create_narration_project


SCRIPT = """
# Demo

## S01 — 0:00–0:20
### Opening title
[WARM] This is a short narration sentence.
""".strip()


def test_generation_settings_do_not_erase_project_narration_options(tmp_path):
    controller = UnifiedWorkspaceController(object(), tmp_path)
    project = controller.create_project(
        SCRIPT,
        speak_section_titles=True,
    )

    controller._save_generation_settings(
        project,
        voice_name="Narrator",
        voice_variant="AUTO",
        language="en",
        quality_preset="BALANCED",
    )

    payload = json.loads((project.root / "studio.json").read_text(encoding="utf-8"))
    assert payload["speak_section_titles"] is True
    assert payload["voice_name"] == "Narrator"
    assert payload["voice_variant"] == "AUTO"
    assert payload["quality_preset"] == "BALANCED"


def test_legacy_title_project_is_inferred_and_backfilled(tmp_path):
    project = create_narration_project(
        SCRIPT,
        tmp_path / "projects" / "legacy",
        speak_section_titles=True,
    )
    controller = UnifiedWorkspaceController(object(), tmp_path)

    settings = controller.load_project_settings(project)

    assert settings["speak_section_titles"] is True
    persisted = json.loads((project.root / "studio.json").read_text(encoding="utf-8"))
    assert persisted["speak_section_titles"] is True
