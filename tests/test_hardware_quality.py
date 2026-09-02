from types import SimpleNamespace

from omnivoice.hardware_quality import (
    HardwareQualitySettingsStore,
    detect_hardware,
    normalize_quality_preset,
    quality_policy,
    quality_preset_rows,
)


class FakeCuda:
    def __init__(
        self,
        *,
        available=True,
        name="Tesla T4",
        vram_gb=16.0,
        capability=(7, 5),
        devices=None,
    ):
        self.available = available
        self.name = name
        self.vram_gb = vram_gb
        self.capability = capability
        self.devices = devices

    def is_available(self):
        return self.available

    def device_count(self):
        if not self.available:
            return 0
        if self.devices is not None:
            return len(self.devices)
        return 1

    def _device(self, index):
        if self.devices is None:
            return {
                "name": self.name,
                "vram_gb": self.vram_gb,
                "capability": self.capability,
            }
        return self.devices[index]

    def get_device_name(self, index):
        return self._device(index)["name"]

    def get_device_properties(self, index):
        return SimpleNamespace(
            total_memory=int(self._device(index)["vram_gb"] * 1024**3)
        )

    def get_device_capability(self, index):
        return self._device(index).get("capability", self.capability)


class FakeTorch:
    def __init__(self, cuda):
        self.cuda = cuda


def test_single_t4_recommends_balanced_and_cpu_asr():
    hardware = detect_hardware(FakeTorch(FakeCuda()))
    assert hardware.cuda_available is True
    assert hardware.device_name == "Tesla T4"
    assert 15.9 <= hardware.total_vram_gb <= 16.1
    assert hardware.compute_capability == (7, 5)
    assert hardware.recommended_preset == "BALANCED"
    assert hardware.recommended_asr_device == "cpu"


def test_dual_t4_recommends_secondary_gpu_for_asr():
    cuda = FakeCuda(
        devices=[
            {"name": "Tesla T4", "vram_gb": 15.0, "capability": (7, 5)},
            {"name": "Tesla T4", "vram_gb": 15.0, "capability": (7, 5)},
        ]
    )
    hardware = detect_hardware(FakeTorch(cuda), device_index=0)
    assert hardware.device_count == 2
    assert hardware.recommended_preset == "BALANCED"
    assert hardware.recommended_asr_device == "cuda:1"
    assert any("Dedicated ASR GPU" in note for note in hardware.notes)


def test_secondary_gpu_below_four_gb_falls_back_to_cpu_asr():
    cuda = FakeCuda(
        devices=[
            {"name": "Tesla T4", "vram_gb": 16.0, "capability": (7, 5)},
            {"name": "Tiny GPU", "vram_gb": 2.0, "capability": (6, 1)},
        ]
    )
    hardware = detect_hardware(FakeTorch(cuda), device_index=0)
    assert hardware.recommended_asr_device == "cpu"


def test_high_vram_gpu_recommends_safe():
    hardware = detect_hardware(
        FakeTorch(FakeCuda(name="NVIDIA A100", vram_gb=40.0, capability=(8, 0)))
    )
    assert hardware.recommended_preset == "SAFE"
    assert hardware.recommended_asr_device == "cuda:0"


def test_cpu_detection_degrades_cleanly():
    hardware = detect_hardware(FakeTorch(FakeCuda(available=False)))
    assert hardware.cuda_available is False
    assert hardware.recommended_asr_device == "cpu"
    assert "CUDA not detected" in hardware.summary()


def test_safe_balanced_fast_preserve_text_verification():
    safe = quality_policy("safe")
    balanced = quality_policy("BALANCED")
    fast = quality_policy("fast")

    assert safe.generation_config().num_step == 32
    assert balanced.generation_config().num_step == 28
    assert fast.generation_config().num_step == 24

    assert safe.robust_config().verify_with_asr is True
    assert balanced.robust_config().verify_with_asr is True
    assert fast.robust_config().verify_with_asr is True

    assert safe.robust_config().max_retries == 3
    assert balanced.robust_config().max_retries == 2
    assert fast.robust_config().max_retries == 1

    assert safe.adaptive_config().adaptive_retry is True
    assert balanced.adaptive_config().adaptive_retry is True
    assert fast.adaptive_config().adaptive_retry is False
    assert fast.adaptive_config().pacing_guard is False


def test_preset_table_has_three_named_policies():
    rows = quality_preset_rows()
    assert [row[0] for row in rows] == ["SAFE", "BALANCED", "FAST"]
    assert all(row[4] == "ON" for row in rows)  # ASR verification


def test_workspace_quality_settings_round_trip(tmp_path):
    store = HardwareQualitySettingsStore(tmp_path)
    assert store.load().default_preset == "SAFE"
    store.set_default("balanced")
    assert store.load().default_preset == "BALANCED"
    assert (tmp_path / "hardware-quality.json").exists()


def test_invalid_preset_is_rejected():
    try:
        normalize_quality_preset("turbo")
    except ValueError as exc:
        assert "Unknown quality preset" in str(exc)
    else:
        raise AssertionError("Expected invalid quality preset to be rejected")
