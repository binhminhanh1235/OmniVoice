import json

from omnivoice.cli import project_studio_quality as quality_module
from omnivoice.cli.project_studio_quality import (
    QualityPresetProjectStudioController,
    build_hardware_quality_demo,
    build_quality_project_demo,
)
from omnivoice.hardware_quality import HardwareCapabilities
from omnivoice.project_queue import ProjectQueueStore


SCRIPT = """# Quality Test

## S01 — 0:00–0:10

[WARM] This is a short quality preset test.
"""


class FakeRunner:
    created = []

    def __init__(
        self,
        model,
        voice_library,
        *,
        voice_name,
        preferred_variant="AUTO",
        style_profiles=None,
        quality_config=None,
    ):
        self.quality_config = quality_config
        self.calls = []
        FakeRunner.created.append(self)

    def generate(self, project, **kwargs):
        self.calls.append(kwargs)
        return project.manifest


class FakeModel:
    sampling_rate = 24000


def test_project_override_persists_to_studio_json(tmp_path):
    controller = QualityPresetProjectStudioController(object(), tmp_path)
    project = controller.create_project(SCRIPT)

    assert controller.project_quality_preset(project) == ("SAFE", "workspace")
    controller.set_workspace_quality_preset("BALANCED")
    assert controller.project_quality_preset(project) == ("BALANCED", "workspace")

    assert controller.set_project_quality_preset(project.root, "FAST") == ("FAST", "project")
    payload = json.loads((project.root / "studio.json").read_text(encoding="utf-8"))
    assert payload["quality_preset"] == "FAST"

    assert controller.set_project_quality_preset(project.root, "INHERIT") == (
        "BALANCED",
        "workspace",
    )
    payload = json.loads((project.root / "studio.json").read_text(encoding="utf-8"))
    assert "quality_preset" not in payload


def test_generate_routes_selected_policy_to_runner(tmp_path, monkeypatch):
    FakeRunner.created = []
    monkeypatch.setattr(quality_module, "StyleBankProjectRunner", FakeRunner)

    controller = QualityPresetProjectStudioController(object(), tmp_path)
    project = controller.create_project(SCRIPT)
    generated = controller.generate(
        project.root,
        voice_name="Narrator",
        voice_variant="AUTO",
        quality_preset="BALANCED",
    )

    assert generated.root == project.root
    assert len(FakeRunner.created) == 1
    runner = FakeRunner.created[0]
    assert runner.quality_config.adaptive_retry is True
    assert runner.quality_config.pacing_guard is True
    call = runner.calls[0]
    assert call["generation_config"].num_step == 28
    assert call["robust_config"].max_retries == 2
    assert call["robust_config"].verify_with_asr is True

    payload = json.loads((project.root / "studio.json").read_text(encoding="utf-8"))
    assert payload["voice_name"] == "Narrator"
    assert payload["quality_preset"] == "BALANCED"


def test_workspace_fast_policy_is_used_when_project_inherits(tmp_path, monkeypatch):
    FakeRunner.created = []
    monkeypatch.setattr(quality_module, "StyleBankProjectRunner", FakeRunner)

    controller = QualityPresetProjectStudioController(object(), tmp_path)
    controller.set_workspace_quality_preset("FAST")
    project = controller.create_project(SCRIPT)
    controller.generate(project.root, voice_name="Narrator")

    runner = FakeRunner.created[0]
    assert runner.quality_config.adaptive_retry is False
    assert runner.quality_config.pacing_guard is False
    call = runner.calls[0]
    assert call["generation_config"].num_step == 24
    assert call["robust_config"].max_retries == 1
    assert call["robust_config"].verify_with_asr is True


def test_queue_snapshots_project_quality_policy(tmp_path):
    controller = QualityPresetProjectStudioController(object(), tmp_path)
    project = controller.create_project(SCRIPT)

    # Queue requires a saved voice name. No actual prompt is loaded at enqueue time.
    (project.root / "studio.json").write_text(
        json.dumps(
            {
                "voice_name": "Narrator",
                "voice_variant": "AUTO",
                "language": "en",
                "quality_preset": "BALANCED",
            }
        ),
        encoding="utf-8",
    )
    store = ProjectQueueStore(tmp_path)
    item = store.enqueue(controller, project.root, auto_merge=False)
    assert item.quality_preset == "BALANCED"

    # Later project/workspace edits do not mutate the already persisted queue item.
    controller.set_project_quality_preset(project.root, "FAST")
    assert store.load().items[0].quality_preset == "BALANCED"


def test_hardware_quality_demo_builds(tmp_path):
    hardware = HardwareCapabilities(
        cuda_available=True,
        device_count=1,
        device_index=0,
        device_name="Tesla T4",
        total_vram_gb=16.0,
        compute_capability=(7, 5),
        recommended_asr_device="cpu",
        recommended_preset="BALANCED",
    )
    demo = build_hardware_quality_demo(
        FakeModel(),
        tmp_path,
        detector=lambda: hardware,
    )
    assert demo is not None


def test_quality_project_studio_builds(tmp_path):
    demo = build_quality_project_demo(FakeModel(), tmp_path)
    assert demo is not None
