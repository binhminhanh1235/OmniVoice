import threading
import time

import pytest

from omnivoice.lazy_asr import (
    configure_lazy_asr,
    ensure_asr_model,
    should_defer_asr_startup,
)


class FakeAsrPipe:
    def __init__(self, name, device):
        self.name = name
        self.device = device

    def __call__(self, audio):
        return {"text": f"transcript:{audio}"}


class FakeModel:
    def __init__(self, *, fail_first=False, load_delay=0.0):
        self._asr_pipe = None
        self._asr_model_name = "fake/whisper"
        self._asr_device = "cpu"
        self.device = "cuda:0"
        self.load_calls = []
        self.fail_first = fail_first
        self.load_delay = load_delay

    def load_asr_model(self, model_name=None, device=None):
        model_name = model_name or self._asr_model_name
        device = device or self._asr_device or self.device
        self.load_calls.append((model_name, device))
        if self.load_delay:
            time.sleep(self.load_delay)
        if self.fail_first:
            self.fail_first = False
            raise RuntimeError("synthetic ASR load failure")
        self._asr_pipe = FakeAsrPipe(model_name, device)

    def transcribe(self, audio):
        if self._asr_pipe is None:
            raise RuntimeError("ASR not loaded")
        return self._asr_pipe(audio)["text"]


def test_cpu_policy_is_lazy_but_accelerators_stay_eager():
    assert should_defer_asr_startup("cpu") is True
    assert should_defer_asr_startup("CPU:0") is True
    assert should_defer_asr_startup("cuda:0") is False
    assert should_defer_asr_startup("cuda:1") is False
    assert should_defer_asr_startup("xpu:0") is False
    assert should_defer_asr_startup(None) is False


def test_configuration_does_not_load_asr_until_first_transcription():
    model = FakeModel()

    configure_lazy_asr(model, model_name="fake/whisper", device="cpu")

    assert model._asr_pipe is None
    assert model.load_calls == []

    assert model.transcribe("first.wav") == "transcript:first.wav"
    assert model.load_calls == [("fake/whisper", "cpu")]
    first_pipe = model._asr_pipe

    assert model.transcribe("second.wav") == "transcript:second.wav"
    assert model.load_calls == [("fake/whisper", "cpu")]
    assert model._asr_pipe is first_pipe


def test_repeated_verification_load_reuses_same_pipeline():
    model = FakeModel()
    configure_lazy_asr(model, model_name="fake/whisper", device="cpu")

    first = ensure_asr_model(model)
    second = ensure_asr_model(model)

    assert first is second
    assert model.load_calls == [("fake/whisper", "cpu")]


def test_concurrent_first_use_initializes_exactly_once():
    model = FakeModel(load_delay=0.03)
    configure_lazy_asr(model, model_name="fake/whisper", device="cpu")
    barrier = threading.Barrier(8)
    results = []
    errors = []

    def worker(index):
        try:
            barrier.wait(timeout=2)
            results.append(model.transcribe(f"{index}.wav"))
        except Exception as exc:  # pragma: no cover - only used for diagnostics
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert errors == []
    assert len(results) == 8
    assert model.load_calls == [("fake/whisper", "cpu")]


def test_failed_first_load_does_not_poison_state_and_can_retry():
    model = FakeModel(fail_first=True)
    configure_lazy_asr(model, model_name="fake/whisper", device="cpu")

    with pytest.raises(RuntimeError, match="synthetic ASR load failure"):
        model.transcribe("first.wav")

    assert model._asr_pipe is None
    assert model.load_calls == [("fake/whisper", "cpu")]

    assert model.transcribe("retry.wav") == "transcript:retry.wav"
    assert model.load_calls == [
        ("fake/whisper", "cpu"),
        ("fake/whisper", "cpu"),
    ]


def test_explicit_different_asr_binding_still_reloads():
    model = FakeModel()
    configure_lazy_asr(model, model_name="fake/whisper", device="cpu")

    first = ensure_asr_model(model)
    second = model.load_asr_model(model_name="fake/other", device="cuda:1")

    assert second is not first
    assert model.load_calls == [
        ("fake/whisper", "cpu"),
        ("fake/other", "cuda:1"),
    ]
    assert model._asr_pipe.name == "fake/other"
    assert model._asr_pipe.device == "cuda:1"
