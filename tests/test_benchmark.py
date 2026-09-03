import numpy as np
import pytest

from omnivoice.benchmark import (
    BenchmarkSampleResult,
    benchmark_generate,
    summarize_results,
)
from omnivoice.cli.project_studio_voice_doctor import (
    _should_eager_load_asr as project_studio_should_eager_load_asr,
)
from omnivoice.cli.studio_server import (
    _should_eager_load_asr as studio_server_should_eager_load_asr,
)


class FakeModel:
    device = "cpu"
    sampling_rate = 100

    def __init__(self):
        self.calls = 0

    def generate(self, *, text, **kwargs):
        self.calls += 1
        # Stable one-second waveform keeps audio-duration assertions simple.
        return [np.zeros(self.sampling_rate, dtype=np.float32)]


def test_summarize_results_uses_weighted_rtf():
    results = [
        BenchmarkSampleResult(
            sample="S01",
            repetition=1,
            text_chars=10,
            text_words=2,
            elapsed_seconds=1.0,
            audio_duration_seconds=2.0,
            rtf=0.5,
        ),
        BenchmarkSampleResult(
            sample="S02",
            repetition=1,
            text_chars=10,
            text_words=2,
            elapsed_seconds=3.0,
            audio_duration_seconds=3.0,
            rtf=1.0,
        ),
    ]

    summary = summarize_results(results)

    assert summary.samples == 2
    assert summary.total_elapsed_seconds == pytest.approx(4.0)
    assert summary.total_audio_seconds == pytest.approx(5.0)
    assert summary.weighted_rtf == pytest.approx(0.8)
    assert summary.median_rtf == pytest.approx(0.75)
    assert summary.max_peak_cuda_memory_mb is None


def test_benchmark_generate_excludes_warmup_and_repeats_samples():
    model = FakeModel()

    results = benchmark_generate(
        model,
        ["hello world", "second sample"],
        warmup=1,
        repeat=2,
    )

    assert model.calls == 5
    assert len(results) == 4
    assert [item.sample for item in results] == ["S01", "S02", "S01", "S02"]
    assert [item.repetition for item in results] == [1, 1, 2, 2]
    assert all(item.audio_duration_seconds == pytest.approx(1.0) for item in results)
    assert all(item.elapsed_seconds >= 0 for item in results)
    assert all(item.rtf >= 0 for item in results)


def test_benchmark_generate_validates_arguments():
    model = FakeModel()

    with pytest.raises(ValueError, match="non-empty benchmark text"):
        benchmark_generate(model, [" "])
    with pytest.raises(ValueError, match="warmup"):
        benchmark_generate(model, ["hello"], warmup=-1)
    with pytest.raises(ValueError, match="repeat"):
        benchmark_generate(model, ["hello"], repeat=0)


@pytest.mark.parametrize(
    ("device", "expected"),
    [
        ("cpu", False),
        ("CPU", False),
        ("cuda", True),
        ("cuda:1", True),
        ("xpu:0", True),
    ],
)
def test_studio_launchers_only_eager_load_accelerator_asr(device, expected):
    assert project_studio_should_eager_load_asr(device) is expected
    assert studio_server_should_eager_load_asr(device) is expected
