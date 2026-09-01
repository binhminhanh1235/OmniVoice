from omnivoice.cli.project_queue_ui import build_project_queue_demo


class FakeVoices:
    def voice_names(self):
        return []

    def variant_choices(self, name):
        return []


class FakeController:
    def __init__(self, model, workspace):
        self.model = model
        self.workspace = workspace
        self.voices = FakeVoices()

    def list_projects(self):
        return []


def test_project_queue_demo_builds(tmp_path):
    demo = build_project_queue_demo(
        object(),
        tmp_path,
        controller_cls=FakeController,
    )
    assert demo is not None
