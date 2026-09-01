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
        self.workspace = workspace
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
        self.workspace = workspace
        self.voices = SavedVoices()

    def list_projects(self):
        return ["/tmp/project-a"]

    def load_project(self, project_path):
        return SimpleNamespace(manifest=SimpleNamespace(title="Project A"))

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
