import importlib.util
import json
import zipfile
from pathlib import Path

import pytest


BOOTSTRAP_PATH = Path(__file__).parents[1] / "notebooks" / "hosted_runtime_bootstrap.py"
spec = importlib.util.spec_from_file_location("hosted_runtime_bootstrap", BOOTSTRAP_PATH)
assert spec is not None and spec.loader is not None
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def test_exact_revision_validation_is_fail_closed():
    sha = "a" * 40
    assert bootstrap.validate_exact_revision(sha.upper(), label="test") == sha
    with pytest.raises(ValueError):
        bootstrap.validate_exact_revision("master", label="test")
    with pytest.raises(ValueError):
        bootstrap.validate_exact_revision("abc123", label="test")


def test_wheel_manifest_detects_content_corruption(tmp_path):
    package_ref = "b" * 40
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    wheel = wheel_dir / "omnivoice-0.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("omnivoice/__init__.py", "version = 1\n")

    bootstrap._write_wheel_manifest(wheel, package_ref)
    assert bootstrap._verified_wheel(wheel_dir, package_ref) == wheel

    with wheel.open("ab") as stream:
        stream.write(b"corruption")
    assert bootstrap._verified_wheel(wheel_dir, package_ref) is None


def test_bootstrap_source_rejects_partial_inventory(tmp_path):
    source = tmp_path / "namespace"
    (source / "pip").mkdir(parents=True)
    (source / "wheels").mkdir()
    (source / "pip" / "cache.bin").write_bytes(b"12345")
    compatibility = {
        "schema_version": 2,
        "cache_version": "v2",
        "python_version": "3.11",
        "system": "linux",
        "machine": "x86_64",
        "resource_signature": "model@sha|asr@sha",
    }
    metadata = {
        "state": "ready",
        "compatibility": compatibility,
        "inventory": {
            "pip": {"files": 1, "bytes": 5},
            "wheels": {"files": 0, "bytes": 0},
        },
    }
    (source / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    ready, _ = bootstrap._bootstrap_source_compatible(source, compatibility)
    assert ready is True

    (source / "pip" / "cache.bin").write_bytes(b"1")
    ready, reason = bootstrap._bootstrap_source_compatible(source, compatibility)
    assert ready is False
    assert "inventory mismatch" in reason


def test_cache_key_changes_when_exact_model_revision_changes():
    old = bootstrap._compatibility(model_revision="1" * 40, asr_revision="2" * 40)
    new = bootstrap._compatibility(model_revision="3" * 40, asr_revision="2" * 40)

    assert old["resource_signature"] != new["resource_signature"]
    assert bootstrap._cache_key(old) != bootstrap._cache_key(new)
