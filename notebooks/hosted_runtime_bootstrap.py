#!/usr/bin/env python3
"""Stdlib-first bootstrap used by the production Colab/Kaggle notebooks.

The notebook resolves this file by an immutable OmniVoice commit SHA before
executing it. This module intentionally has no import-time side effects so its
integrity helpers can be unit tested without a hosted runtime.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Mapping, Optional

CACHE_SCHEMA_VERSION = 2
CACHE_VERSION = "v2"
MODEL_ID = "k2-fsa/OmniVoice"
ASR_MODEL = "openai/whisper-small.en"
_SHA_RE = re.compile(r"[0-9a-fA-F]{40}")


def validate_exact_revision(value: str, *, label: str) -> str:
    value = str(value).strip().lower()
    if not _SHA_RE.fullmatch(value):
        raise ValueError(f"{label} must be an exact 40-character commit SHA, got {value!r}")
    return value


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _component_inventory(root: Path) -> dict[str, int]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    files = 0
    total_bytes = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        stat = path.stat()
        files += 1
        total_bytes += stat.st_size
    return {"files": files, "bytes": total_bytes}


def _bootstrap_source_compatible(
    source_namespace: Optional[Path], compatibility: Mapping[str, object]
) -> tuple[bool, str]:
    if source_namespace is None:
        return False, "no persistent cache source"
    metadata = _read_json(source_namespace / "metadata.json")
    if metadata.get("state") != "ready":
        return False, "persistent cache is not in ready state"
    if metadata.get("compatibility") != dict(compatibility):
        return False, "persistent cache fingerprint differs"
    inventory = metadata.get("inventory")
    if not isinstance(inventory, dict):
        return False, "persistent cache inventory is missing"
    try:
        for component in ("pip", "wheels"):
            expected = inventory.get(component)
            if expected != _component_inventory(source_namespace / component):
                return False, f"persistent {component} cache inventory mismatch"
    except OSError as exc:
        return False, f"persistent bootstrap cache is unreadable: {exc}"
    return True, "bootstrap pip/wheel cache is structurally valid"


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        symlinks=False,
        ignore=shutil.ignore_patterns("*.tmp", ".nfs*"),
    )


def _verified_wheel(wheel_dir: Path, package_ref: str) -> Optional[Path]:
    manifest = _read_json(wheel_dir / "wheel-manifest.json")
    if manifest.get("package_ref") != package_ref:
        return None
    filename = manifest.get("filename")
    expected_size = manifest.get("size")
    expected_sha = manifest.get("sha256")
    if not isinstance(filename, str) or not isinstance(expected_size, int):
        return None
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        return None
    wheel = wheel_dir / filename
    try:
        if not wheel.is_file() or wheel.stat().st_size != expected_size:
            return None
        if _sha256_file(wheel) != expected_sha:
            return None
        with zipfile.ZipFile(wheel) as archive:
            if archive.testzip() is not None:
                return None
    except (OSError, zipfile.BadZipFile):
        return None
    return wheel


def _write_wheel_manifest(wheel: Path, package_ref: str) -> Path:
    manifest = wheel.parent / "wheel-manifest.json"
    _write_json_atomic(
        manifest,
        {
            "package_ref": package_ref,
            "filename": wheel.name,
            "size": wheel.stat().st_size,
            "sha256": _sha256_file(wheel),
        },
    )
    return manifest


def _resolve_hf_revision(
    model_id: str,
    *,
    override_name: str,
    environ: Mapping[str, str],
) -> str:
    override = str(environ.get(override_name, "")).strip()
    if override:
        return validate_exact_revision(override, label=override_name)
    encoded = urllib.parse.quote(model_id, safe="/")
    url = f"https://huggingface.co/api/models/{encoded}"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.load(response)
        return validate_exact_revision(str(payload["sha"]), label=f"{model_id} revision")
    except Exception as exc:
        raise RuntimeError(
            f"Cannot resolve the current exact revision for {model_id}. Enable Internet "
            f"for the small metadata lookup or set {override_name} to a verified 40-character "
            "commit SHA. OmniVoice will not silently reuse a cached model revision."
        ) from exc


def _runtime_kind(environ: Mapping[str, str]) -> str:
    if environ.get("COLAB_RELEASE_TAG") or environ.get("COLAB_GPU"):
        return "colab"
    if environ.get("KAGGLE_KERNEL_RUN_TYPE") or Path("/kaggle/working").exists():
        return "kaggle"
    raise RuntimeError("hosted_runtime_bootstrap supports Colab and Kaggle only")


def _compatibility(
    *,
    model_revision: str,
    asr_revision: str,
) -> dict[str, object]:
    libc_name, libc_version = platform.libc_ver()
    libc = f"{libc_name}-{libc_version}" if libc_name else "unknown"
    resource_signature = (
        f"{MODEL_ID}@{model_revision}|{ASR_MODEL}@{asr_revision}|libc={libc}"
    )
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "cache_version": CACHE_VERSION,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "system": platform.system().lower(),
        "machine": platform.machine().lower(),
        "resource_signature": resource_signature,
    }


def _cache_key(compatibility: Mapping[str, object]) -> str:
    payload = json.dumps(dict(compatibility), sort_keys=True, separators=(",", ":"))
    return f"{CACHE_VERSION}-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def bootstrap_hosted_runtime(
    package_ref: str,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, object]:
    """Install an exact OmniVoice revision and prepare persistent startup caches."""

    started = time.perf_counter()
    package_ref = validate_exact_revision(package_ref, label="OmniVoice package revision")
    env = os.environ if environ is None else environ
    runtime = _runtime_kind(env)

    model_revision = _resolve_hf_revision(
        MODEL_ID,
        override_name="OMNIVOICE_MODEL_REVISION",
        environ=env,
    )
    asr_revision = _resolve_hf_revision(
        ASR_MODEL,
        override_name="OMNIVOICE_ASR_REVISION",
        environ=env,
    )
    compatibility = _compatibility(
        model_revision=model_revision,
        asr_revision=asr_revision,
    )
    cache_key = _cache_key(compatibility)
    resource_signature = str(compatibility["resource_signature"])

    if runtime == "colab":
        workspace = Path("/content/OmniVoiceStudio")
        persistent_workspace = Path("/content/drive/MyDrive/OmniVoiceStudio")
        local_cache_base = Path("/content/.cache/omnivoice")
        source_base: Optional[Path] = persistent_workspace / ".startup-cache"
        persist_base = source_base
        bootstrap_base = Path("/content/.cache/omnivoice-bootstrap")
    else:
        workspace = Path("/kaggle/working/OmniVoiceStudio")
        persistent_workspace = None
        local_cache_base = Path("/kaggle/working/.cache/omnivoice")
        attached = Path("/kaggle/input/omnivoice-startup-cache")
        exported = Path("/kaggle/working/OmniVoiceStartupCache")
        source_base = attached if attached.exists() else (exported if exported.exists() else None)
        persist_base = exported
        bootstrap_base = Path("/kaggle/working/.cache/omnivoice-bootstrap")

    workspace.mkdir(parents=True, exist_ok=True)
    local_cache_base.mkdir(parents=True, exist_ok=True)
    source_namespace = source_base / cache_key if source_base else None
    bootstrap_cache = bootstrap_base / cache_key
    if bootstrap_cache.exists():
        shutil.rmtree(bootstrap_cache)
    (bootstrap_cache / "pip").mkdir(parents=True, exist_ok=True)
    (bootstrap_cache / "wheels").mkdir(parents=True, exist_ok=True)

    bootstrap_fast, bootstrap_reason = _bootstrap_source_compatible(
        source_namespace, compatibility
    )
    if bootstrap_fast and source_namespace is not None:
        _copy_tree(source_namespace / "pip", bootstrap_cache / "pip")
        _copy_tree(source_namespace / "wheels", bootstrap_cache / "wheels")

    os.environ["PIP_CACHE_DIR"] = str(bootstrap_cache / "pip")
    package_key = hashlib.sha256(package_ref.encode("utf-8")).hexdigest()[:16]
    wheel_dir = bootstrap_cache / "wheels" / package_key
    wheel_dir.mkdir(parents=True, exist_ok=True)
    wheel = _verified_wheel(wheel_dir, package_ref)

    if wheel is not None:
        wheel_fast_path = True
    else:
        wheel_fast_path = False
        if wheel_dir.exists():
            shutil.rmtree(wheel_dir)
        wheel_dir.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "-q",
                "--no-deps",
                f"git+https://github.com/binhminhanh1235/OmniVoice.git@{package_ref}",
                "--wheel-dir",
                str(wheel_dir),
            ]
        )
        wheels = sorted(wheel_dir.glob("omnivoice-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(
                f"Expected one exact OmniVoice wheel for {package_ref}, found {len(wheels)}"
            )
        wheel = wheels[0]
        _write_wheel_manifest(wheel, package_ref)
        wheel = _verified_wheel(wheel_dir, package_ref)
        if wheel is None:
            raise RuntimeError("newly built OmniVoice wheel failed integrity verification")

    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "--upgrade", str(wheel)]
    )

    os.environ["OMNIVOICE_LOCAL_CACHE_ROOT"] = str(local_cache_base)
    if source_base is not None:
        os.environ["OMNIVOICE_CACHE_SOURCE"] = str(source_base)
    else:
        os.environ.pop("OMNIVOICE_CACHE_SOURCE", None)
    os.environ["OMNIVOICE_CACHE_PERSIST_ROOT"] = str(persist_base)

    from omnivoice.runtime_cache import (
        RuntimeCacheFingerprint,
        apply_cache_environment,
        detect_runtime_cache,
        persist_runtime_cache,
        prepare_runtime_cache,
        write_startup_cache_evidence,
        write_workspace_cache_metadata,
    )

    fingerprint = RuntimeCacheFingerprint.current(
        cache_version=CACHE_VERSION,
        package_ref=package_ref,
        resource_signature=resource_signature,
    )
    preparation = prepare_runtime_cache(detect_runtime_cache(), fingerprint)
    apply_cache_environment(preparation)
    _copy_tree(bootstrap_cache / "pip", preparation.local_namespace / "pip")
    _copy_tree(bootstrap_cache / "wheels", preparation.local_namespace / "wheels")

    from huggingface_hub import snapshot_download

    snapshot_download(MODEL_ID, revision=model_revision)
    snapshot_download(ASR_MODEL, revision=asr_revision)
    persist_runtime_cache(preparation)
    write_workspace_cache_metadata(workspace, preparation)
    evidence_path = write_startup_cache_evidence(
        workspace,
        preparation,
        wheel_fast_path=wheel_fast_path,
        bootstrap_seconds=time.perf_counter() - started,
    )

    print("Package revision:", package_ref)
    print("OmniVoice model revision:", model_revision)
    print("ASR model revision:", asr_revision)
    print("Bootstrap cache:", "FAST" if bootstrap_fast else "COLD", "-", bootstrap_reason)
    print("Resource cache:", "FAST" if preparation.fast_path else "COLD", "-", preparation.reason)
    print("Exact wheel:", "FAST" if wheel_fast_path else "BUILT")
    print("Local cache:", preparation.local_namespace)
    print("Startup evidence:", evidence_path)

    return {
        "ASR_MODEL": ASR_MODEL,
        "ASR_MODEL_REVISION": asr_revision,
        "MODEL_ID": MODEL_ID,
        "MODEL_REVISION": model_revision,
        "WORKSPACE": str(workspace),
        "PERSISTENT_WORKSPACE": str(persistent_workspace) if persistent_workspace else None,
        "LOCAL_CACHE_BASE": local_cache_base,
        "CACHE_SOURCE_BASE": source_base,
        "CACHE_EXPORT_BASE": persist_base,
        "CACHE_PREPARATION": preparation,
        "WHEEL_FAST_PATH": wheel_fast_path,
        "STARTUP_CACHE_EVIDENCE": evidence_path,
        "persist_runtime_cache": persist_runtime_cache,
        "write_workspace_cache_metadata": write_workspace_cache_metadata,
        "Path": Path,
        "shutil": shutil,
        "subprocess": subprocess,
        "os": os,
    }
