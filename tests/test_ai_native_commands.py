import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from omnivoice.models.omnivoice import OmniVoiceGenerationConfig
from omnivoice.robust_longform import RobustLongFormConfig, clean_tts_text
from omnivoice.services.job_manager import StudioJobManager, wait_for_terminal
from omnivoice.services.studio_commands import StudioCommandService


HASHMAP_SCRIPT = (
    "HashMap stores entries in a bucket array. It spreads the key’s hashCode, "
    "derives a bucket index, then resolves collisions inside that bucket by "
    "comparing hash and equals. With a good hash distribution, get and put are "
    "expected O(1), but that is not a hard guarantee. When size crosses the "
    "resize threshold, the table grows and entries are redistributed, which can "
    "create allocation and copy work. In current OpenJDK, a sufficiently long "
    "collision bin can be treeified when the table is large enough, but those "
    "thresholds are implementation details rather than the Map contract. The "
    "correctness contract is just as important as the mechanics: equal keys must "
    "have equal hash codes, and fields used by equals/hashCode should remain "
    "stable while the object is used as a key."
)


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
        del quality_preset
        return OmniVoiceGenerationConfig()

    def robust_config(self, *, strict=False, quality_preset=None):
        del quality_preset
        return RobustLongFormConfig(
            max_chunk_words=24,
            max_chunk_chars=220,
            pause_ms=0,
            paragraph_pause_ms=0,
            max_retries=1,
            max_split_depth=0,
            verify_with_asr=False,
            strict=strict,
        )


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
    assert finished.result["verified"] is True
    assert finished.result["chunk_count"] == 1
    assert finished.result["unverified_chunks"] == 0

    listed = commands.artifacts.list(kinds=["generated_audio"])
    assert [item["id"] for item in listed] == [artifact["id"]]


def test_generate_audio_uses_robust_chunks_for_hashmap_regression(tmp_path):
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
                "text": HASHMAP_SCRIPT,
                "voice_name": "Narrator",
                "language": "en",
                "quality_preset": "BALANCED",
            },
        )
        finished = wait_for_terminal(jobs, job.id)
    finally:
        jobs.shutdown()

    assert finished.status == "completed"
    assert finished.result["verified"] is True
    assert finished.result["chunk_count"] > 1
    assert len(model.calls) == finished.result["chunk_count"]
    assert all(call["text"] != HASHMAP_SCRIPT for call in model.calls)
    assert all(len(call["text"].split()) <= 24 for call in model.calls)
    assert all(len(call["text"]) <= 220 for call in model.calls)
    assert " ".join(call["text"] for call in model.calls) == clean_tts_text(HASHMAP_SCRIPT)

    sidecar = json.loads(Path(finished.result["metadata_file"]).read_text())
    assert sidecar["verified"] is True
    assert sidecar["chunk_count"] == len(model.calls)
    assert sidecar["unverified_chunks"] == 0
    assert sidecar["chunks"] == [call["text"] for call in model.calls]
    assert len(sidecar["chunk_reports"]) == len(model.calls)


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
    assert finished.result["verified"] is True
