from types import SimpleNamespace

import numpy as np

from omnivoice.services.job_manager import StudioJobManager, wait_for_terminal
from omnivoice.services.studio_commands import StudioCommandService


class FakeModel:
    sampling_rate = 24000

    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return [np.zeros(2400, dtype=np.float32)]


class FakeVoices:
    def resolve_prompt(self, name, *, style, preferred_variant):
        return SimpleNamespace(
            prompt="VOICE_PROMPT",
            voice_name=name,
            variant="DEFAULT" if preferred_variant == "AUTO" else preferred_variant,
            used_fallback=False,
        )


class FakeController:
    def __init__(self):
        self.voices = FakeVoices()

    def workspace_quality_preset(self):
        return "BALANCED"

    def generation_config(self, quality_preset=None):
        return SimpleNamespace(name=quality_preset or "BALANCED")


def test_generate_audio_job_writes_discoverable_artifact(tmp_path):
    workspace = tmp_path / "studio"
    model = FakeModel()
    commands = StudioCommandService(
        model,
        workspace,
        controller=FakeController(),
    )
    jobs = StudioJobManager(workspace)
    jobs.register("generate_audio", commands.generate_audio_job)
    jobs.start()
    try:
        job = jobs.submit(
            "generate_audio",
            {
                "text": "Hello from the durable audio job.",
                "voice_name": "Narrator",
                "voice_variant": "AUTO",
                "language": "en",
                "quality_preset": "FAST",
            },
        )
        finished = wait_for_terminal(jobs, job.id)
    finally:
        jobs.shutdown()

    assert finished.status == "completed"
    artifact = finished.result["artifact"]
    assert artifact["kind"] == "generated_audio"
    assert artifact["duration_seconds"] == 0.1
    assert artifact["sample_rate"] == 24000
    assert artifact["relative_path"].endswith(f"artifacts/audio/{job.id}.wav")
    assert model.calls[0]["voice_clone_prompt"] == "VOICE_PROMPT"
    assert model.calls[0]["language"] == "en"

    listed = commands.artifacts.list(kinds=["generated_audio"])
    assert [item["id"] for item in listed] == [artifact["id"]]


def test_preview_audio_uses_fast_default_without_mutating_project(tmp_path):
    workspace = tmp_path / "studio"
    model = FakeModel()
    commands = StudioCommandService(
        model,
        workspace,
        controller=FakeController(),
    )
    jobs = StudioJobManager(workspace)
    jobs.register("preview_audio", commands.preview_audio_job)
    jobs.start()
    try:
        job = jobs.submit("preview_audio", {"text": "Short preview"})
        finished = wait_for_terminal(jobs, job.id)
    finally:
        jobs.shutdown()

    assert finished.status == "completed"
    assert finished.result["preview"] is True
    assert finished.result["quality_preset"] == "FAST"
    assert finished.result["artifact"]["kind"] == "preview_audio"
