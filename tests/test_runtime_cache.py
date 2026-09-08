import json
from pathlib import Path

from omnivoice.runtime_cache import (
    RuntimeCacheFingerprint,
    RuntimeCacheLayout,
    apply_cache_environment,
    cache_status,
    detect_runtime_cache,
    persist_runtime_cache,
    prepare_runtime_cache,
)


def fake_exists(*existing: str):
    resolved = {str(Path(item)) for item in existing}
    return lambda path: str(Path(path)) in resolved


def fingerprint(ref: str = "abc123"):
    return RuntimeCacheFingerprint(
        schema_version=1,
        cache_version="test-v1",
        python_version="3.11",
        system="linux",
        machine="x86_64",
        package_ref=ref,
    )


def test_colab_cache_uses_local_ssd_and_drive_persistence():
    layout = detect_runtime_cache(
        environ={"COLAB_RELEASE_TAG": "release"},
        path_exists=fake_exists("/content", "/content/drive/MyDrive"),
    )

    assert layout.environment == "colab"
    assert layout.local_root == Path("/content/.cache/omnivoice")
    assert layout.source_root == Path(
        "/content/drive/MyDrive/OmniVoiceStudio/.startup-cache"
    )
    assert layout.persist_root == layout.source_root


def test_kaggle_cache_restores_attached_dataset_and_exports_to_working():
    layout = detect_runtime_cache(
        environ={"KAGGLE_KERNEL_RUN_TYPE": "Interactive"},
        path_exists=fake_exists(
            "/kaggle/working",
            "/kaggle/input",
            "/kaggle/input/omnivoice-startup-cache",
        ),
    )

    assert layout.environment == "kaggle"
    assert layout.local_root == Path("/kaggle/working/.cache/omnivoice")
    assert layout.source_root == Path("/kaggle/input/omnivoice-startup-cache")
    assert layout.persist_root == Path("/kaggle/working/OmniVoiceStartupCache")


def test_environment_overrides_cache_roots():
    layout = detect_runtime_cache(
        environ={
            "KAGGLE_KERNEL_RUN_TYPE": "Interactive",
            "OMNIVOICE_LOCAL_CACHE_ROOT": "/tmp/local-cache",
            "OMNIVOICE_CACHE_SOURCE": "/mnt/read-only-cache",
            "OMNIVOICE_CACHE_PERSIST_ROOT": "/mnt/write-cache",
        },
        path_exists=fake_exists("/kaggle/working"),
    )

    assert layout.local_root == Path("/tmp/local-cache")
    assert layout.source_root == Path("/mnt/read-only-cache")
    assert layout.persist_root == Path("/mnt/write-cache")


def test_prepare_uses_cold_path_when_metadata_is_missing(tmp_path):
    fp = fingerprint()
    layout = RuntimeCacheLayout(
        environment="local",
        local_root=tmp_path / "local",
        source_root=tmp_path / "persistent",
        persist_root=tmp_path / "persistent",
    )

    result = prepare_runtime_cache(layout, fp)

    assert result.fast_path is False
    assert result.restored_from is None
    assert (result.local_namespace / "pip").is_dir()
    assert "fingerprint" in json.loads(
        (result.local_namespace / "metadata.json").read_text(encoding="utf-8")
    )


def test_persist_then_restore_compatible_cache(tmp_path):
    fp = fingerprint()
    persistent = tmp_path / "persistent"
    first_layout = RuntimeCacheLayout(
        environment="colab",
        local_root=tmp_path / "session-a",
        source_root=persistent,
        persist_root=persistent,
    )
    first = prepare_runtime_cache(first_layout, fp)
    (first.local_namespace / "pip" / "download.bin").write_bytes(b"pip-cache")
    (first.local_namespace / "huggingface" / "model.bin").write_bytes(b"model-cache")
    (first.local_namespace / "whisper" / "asr.bin").write_bytes(b"asr-cache")

    target = persist_runtime_cache(first)
    assert target is not None
    assert (target / "pip" / "download.bin").read_bytes() == b"pip-cache"

    second_layout = RuntimeCacheLayout(
        environment="colab",
        local_root=tmp_path / "session-b",
        source_root=persistent,
        persist_root=persistent,
    )
    second = prepare_runtime_cache(second_layout, fp)

    assert second.fast_path is True
    assert second.restored_from == target
    assert (second.local_namespace / "huggingface" / "model.bin").read_bytes() == (
        b"model-cache"
    )
    assert (second.local_namespace / "whisper" / "asr.bin").read_bytes() == b"asr-cache"


def test_incompatible_fingerprint_does_not_restore_stale_cache(tmp_path):
    persistent = tmp_path / "persistent"
    old_fp = fingerprint("old")
    old_layout = RuntimeCacheLayout(
        environment="local",
        local_root=tmp_path / "session-old",
        source_root=persistent,
        persist_root=persistent,
    )
    old = prepare_runtime_cache(old_layout, old_fp)
    (old.local_namespace / "pip" / "old.bin").write_bytes(b"old")
    persist_runtime_cache(old)

    new_fp = fingerprint("new")
    new_layout = RuntimeCacheLayout(
        environment="local",
        local_root=tmp_path / "session-new",
        source_root=persistent,
        persist_root=persistent,
    )
    new = prepare_runtime_cache(new_layout, new_fp)

    assert new.fast_path is False
    assert not (new.local_namespace / "pip" / "old.bin").exists()
    assert new.local_namespace != old.local_namespace


def test_apply_environment_points_all_hot_caches_to_local_namespace(tmp_path):
    fp = fingerprint()
    layout = RuntimeCacheLayout(environment="local", local_root=tmp_path / "local")
    prepared = prepare_runtime_cache(layout, fp)
    env = {}

    values = apply_cache_environment(prepared, environ=env)

    assert env["PIP_CACHE_DIR"].startswith(str(prepared.local_namespace))
    assert env["HF_HOME"].startswith(str(prepared.local_namespace))
    assert env["TORCH_HOME"].startswith(str(prepared.local_namespace))
    assert env["OMNIVOICE_WHISPER_CACHE"].startswith(str(prepared.local_namespace))
    assert all(Path(value).exists() for value in values.values())


def test_cache_status_reports_persistent_readiness(tmp_path):
    fp = fingerprint()
    persistent = tmp_path / "persistent"
    layout = RuntimeCacheLayout(
        environment="local",
        local_root=tmp_path / "local",
        source_root=persistent,
        persist_root=persistent,
    )
    prepared = prepare_runtime_cache(layout, fp)
    persist_runtime_cache(prepared)

    status = cache_status(layout, fp)

    assert status["cache_key"] == fp.key
    assert status["local_ready"] is True
    assert status["source_ready"] is True
