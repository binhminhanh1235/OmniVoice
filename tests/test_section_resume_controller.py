import numpy as np

from omnivoice import VoiceClonePrompt
from omnivoice.cli.project_studio_resume import SectionResumeProjectStudioController
from omnivoice.project import OmniVoiceProject
from omnivoice.robust_longform import RobustLongFormConfig


SCRIPT = """# Controller Resume Test

## S01 — 0:00–0:10
First section is deliberately short and deterministic.

## S02 — 0:10–0:20
Second section is deliberately short and deterministic.
"""


def _prompt():
    import torch

    return VoiceClonePrompt(
        ref_audio_tokens=torch.tensor([[1, 2, 3, 4]], dtype=torch.long),
        ref_text="reference",
        ref_rms=0.1,
    )


class FakeModel:
    sampling_rate = 8000

    def __init__(self):
        self.calls = []

    def generate(self, text, generation_config=None, **kwargs):
        self.calls.append(text)
        return [np.full(1200, 0.01, dtype=np.float32)]


def _controller(tmp_path):
    model = FakeModel()
    controller = SectionResumeProjectStudioController(model, tmp_path / "workspace")
    controller.voices.save_prompt("David", _prompt(), variant="DEFAULT")
    controller.robust_config = lambda strict=False: RobustLongFormConfig(
        verify_with_asr=False,
        max_chunk_words=24,
        max_chunk_chars=220,
        strict=strict,
    )
    return controller, model


def test_controller_load_restores_verified_sections_from_sidecar(tmp_path):
    controller, model = _controller(tmp_path)
    project = controller.create_project(SCRIPT)
    controller.generate(project.root, voice_name="David", resume=True)
    assert len(model.calls) == 2

    # Make project.json stale while leaving section-status.json and WAVs intact.
    raw = OmniVoiceProject.load(project.root)
    for section in raw.manifest.sections:
        section.status = "pending"
        for beat in section.beats:
            beat.status = "pending"
            for chunk in beat.chunks:
                chunk.status = "pending"
    raw.save()

    restored = controller.load_project(project.root)
    assert [section.status for section in restored.manifest.sections] == [
        "verified",
        "verified",
    ]

    controller.generate(project.root, voice_name="David", resume=True)
    assert len(model.calls) == 2


def test_regenerate_chunk_marks_sidecar_pending_before_resume(tmp_path):
    controller, model = _controller(tmp_path)
    project = controller.create_project(SCRIPT)
    generated = controller.generate(project.root, voice_name="David", resume=True)
    assert len(model.calls) == 2

    chunk = generated.manifest.sections[0].beats[0].chunks[0]
    controller.regenerate_chunk(
        project.root,
        f"S01/{chunk.id} [verified]",
        voice_name="David",
    )

    # Exactly the selected chunk is synthesized again. S02 remains untouched.
    assert len(model.calls) == 3
    reloaded = controller.load_project(project.root)
    assert reloaded.get_section("S01").status == "verified"
    assert reloaded.get_section("S02").status == "verified"
