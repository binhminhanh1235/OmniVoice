import json
from pathlib import Path
from types import SimpleNamespace

from omnivoice.cli.project_queue_ui import build_project_queue_demo


class EmptyVoices:
    def voice_names(self):
        return []

    def variant_choices(self, name):
        return []


class EmptyController:
    def __init__(self, model, workspace):
        self.model = model
        self.workspace = Path(workspace)
        self.projects_root = self.workspace / "projects"
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.voices = EmptyVoices()

    def list_projects(self):
        return []


class SavedVoices:
    def voice_names(self):
        return ["Default Voice", "Saved Voice"]

    def variant_choices(self, name):
        if not name:
            return []
        return ["AUTO", "DEFAULT", "WARM"]


class SavedSettingsController:
    def __init__(self, model, workspace):
        self.model = model
        self.workspace = Path(workspace)
        self.projects_root = self.workspace / "projects"
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.project_root = self.projects_root / "project-a"
        self.project_root.mkdir(parents=True, exist_ok=True)
        (self.project_root / "project.json").write_text(
            json.dumps(
                {
                    "title": "Project A",
                    "sections": [{"id": "S01", "status": "pending"}],
                }
            ),
            encoding="utf-8",
        )
        (self.project_root / "section-status.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "sections": {
                        "S01": {
                            "status": "pending",
                            "complete": False,
                            "audio_file": None,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        self.voices = SavedVoices()

    def list_projects(self):
        return [str(self.project_root)]

    def load_project(self, project_path):
        return SimpleNamespace(
            root=Path(project_path),
            manifest=SimpleNamespace(title="Project A"),
        )

    def load_project_settings(self, project):
        return {
            "voice_name": "Saved Voice",
            "voice_variant": "WARM",
            "language": "en",
        }


def test_project_queue_demo_builds_empty_workspace(tmp_path):
    demo = build_project_queue_demo(
        object(),
        tmp_path,
        controller_cls=EmptyController,
    )
    assert demo is not None


def test_project_queue_demo_builds_with_saved_project_settings(tmp_path):
    demo = build_project_queue_demo(
        object(),
        tmp_path,
        controller_cls=SavedSettingsController,
    )
    assert demo is not None
