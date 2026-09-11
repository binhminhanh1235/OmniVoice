#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Persistent startup cache for ephemeral Colab/Kaggle runtimes.

Active generation always uses runtime-local SSD. Persistent storage is only a
restore/export source for pip wheels, Hugging Face/model data, Torch caches and
ASR/Whisper artifacts.

Cache reuse is deliberately fail-closed:

* compatibility is namespaced by runtime/resource fingerprint;
* persistent namespaces are reusable only after a completed ``ready`` export;
* a structural inventory detects missing/truncated/partial cache trees;
* an interrupted export is left in ``writing`` state and is never restored;
* exact OmniVoice wheels are isolated by source revision and may be protected by
  a SHA-256 wheel manifest in hosted notebooks.

A cache problem therefore degrades to the cold path instead of silently
changing the code/resource identity used by Studio.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from omnivoice.runtime_workspace import detect_runtime_environment


CACHE_SCHEMA_VERSION = 2
DEFAULT_CACHE_VERSION = "v2"
DEFAULT_RESOURCE_SIGNATURE = "k2-fsa/OmniVoice|openai/whisper-small.en"
CACHE_DIR_NAMES = ("pip", "wheels", "huggingface", "torch", "whisper")
READY_STATES = frozenset({"ready"})
LOCAL_READY_STATES = frozenset({"ready", "restored"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RuntimeCacheFingerprint:
    schema_version: int
    cache_version: str
    python_version: str
    system: str
    machine: str
    package_ref: str
    resource_signature: str = DEFAULT_RESOURCE_SIGNATURE

    @classmethod
    def current(
        cls,
        *,
        cache_version: str = DEFAULT_CACHE_VERSION,
        package_ref: str = "master",
        resource_signature: str = DEFAULT_RESOURCE_SIGNATURE,
    ) -> "RuntimeCacheFingerprint":
        return cls(
            schema_version=CACHE_SCHEMA_VERSION,
            cache_version=str(cache_version),
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
            system=platform.system().lower(),
            machine=platform.machine().lower(),
            package_ref=str(package_ref),
            resource_signature=str(resource_signature),
        )

    def compatibility_dict(self) -> dict[str, object]:
        """Fields that decide whether binary/model caches are reusable."""

        return {
            "schema_version": self.schema_version,
            "cache_version": self.cache_version,
            "python_version": self.python_version,
            "system": self.system,
            "machine": self.machine,
            "resource_signature": self.resource_signature,
        }

    @property
    def key(self) -> str:
        payload = json.dumps(
            self.compatibility_dict(), sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return f"{self.cache_version}-{digest}"

    @property
    def package_key(self) -> str:
        digest = hashlib.sha256(self.package_ref.encode("utf-8")).hexdigest()[:16]
        return digest

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeCacheLayout:
    environment: str
    local_root: Path
    source_root: Optional[Path] = None
    persist_root: Optional[Path] = None

    def local_namespace(self, fingerprint: RuntimeCacheFingerprint) -> Path:
        return self.local_root / fingerprint.key

    def source_namespace(self, fingerprint: RuntimeCacheFingerprint) -> Optional[Path]:
        return self.source_root / fingerprint.key if self.source_root else None

    def persist_namespace(self, fingerprint: RuntimeCacheFingerprint) -> Optional[Path]:
        return self.persist_root / fingerprint.key if self.persist_root else None


@dataclass(frozen=True)
class CachePreparation:
    layout: RuntimeCacheLayout
    fingerprint: RuntimeCacheFingerprint
    local_namespace: Path
    fast_path: bool
    restored_from: Optional[Path]
    reason: str

    def summary(self) -> str:
        mode = "fast-path" if self.fast_path else "cold-start"
        source = f" source={self.restored_from}" if self.restored_from else ""
        return f"{mode} cache={self.local_namespace}{source} · {self.reason}"


def _default_exists(path: Path) -> bool:
    return path.exists()


def detect_runtime_cache(
    *,
    environ: Optional[Mapping[str, str]] = None,
    path_exists: Callable[[Path], bool] = _default_exists,
    home: Optional[Path] = None,
) -> RuntimeCacheLayout:
    """Resolve local cache plus optional persistent source/sink.

    Environment overrides:
      OMNIVOICE_LOCAL_CACHE_ROOT
      OMNIVOICE_CACHE_SOURCE
      OMNIVOICE_CACHE_PERSIST_ROOT

    Colab automatically uses mounted MyDrive as both source and sink. Kaggle can
    restore from an attached read-only Dataset and exports a reusable cache tree
    under /kaggle/working by default.
    """

    env = os.environ if environ is None else environ
    environment = detect_runtime_environment(environ=env, path_exists=path_exists)

    configured_local = env.get("OMNIVOICE_LOCAL_CACHE_ROOT")
    if configured_local:
        local_root = Path(configured_local).expanduser()
    elif environment == "colab":
        local_root = Path("/content/.cache/omnivoice")
    elif environment == "kaggle":
        local_root = Path("/kaggle/working/.cache/omnivoice")
    else:
        local_root = (home or Path.home()) / ".cache" / "omnivoice"

    source_value = env.get("OMNIVOICE_CACHE_SOURCE")
    persist_value = env.get("OMNIVOICE_CACHE_PERSIST_ROOT")
    source_root = Path(source_value).expanduser() if source_value else None
    persist_root = Path(persist_value).expanduser() if persist_value else None

    if environment == "colab":
        drive_root = Path("/content/drive/MyDrive/OmniVoiceStudio/.startup-cache")
        if path_exists(Path("/content/drive/MyDrive")):
            source_root = source_root or drive_root
            persist_root = persist_root or drive_root

    if environment == "kaggle":
        conventional_dataset = Path("/kaggle/input/omnivoice-startup-cache")
        if source_root is None and path_exists(conventional_dataset):
            source_root = conventional_dataset
        if persist_root is None:
            persist_root = Path("/kaggle/working/OmniVoiceStartupCache")

    return RuntimeCacheLayout(
        environment=environment,
        local_root=local_root,
        source_root=source_root,
        persist_root=persist_root,
    )


def _metadata_path(namespace: Path) -> Path:
    return namespace / "metadata.json"


def _read_metadata(namespace: Path) -> Optional[dict[str, object]]:
    path = _metadata_path(namespace)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _fingerprint_matches(
    payload: Optional[dict[str, object]],
    fingerprint: RuntimeCacheFingerprint,
) -> bool:
    if not payload:
        return False
    stored = payload.get("compatibility")
    return isinstance(stored, dict) and stored == fingerprint.compatibility_dict()


def _sync_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    # Follow symlinks when copying. Hugging Face snapshots often link into a
    # blob store; dereferencing keeps a Drive/Kaggle export self-contained.
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        symlinks=False,
        ignore=shutil.ignore_patterns("*.tmp", ".nfs*"),
    )


def _ensure_cache_tree(namespace: Path) -> None:
    namespace.mkdir(parents=True, exist_ok=True)
    for name in CACHE_DIR_NAMES:
        (namespace / name).mkdir(parents=True, exist_ok=True)


def _reset_cache_tree(namespace: Path) -> None:
    if namespace.exists():
        shutil.rmtree(namespace)
    _ensure_cache_tree(namespace)


def _tree_inventory(namespace: Path) -> dict[str, dict[str, int]]:
    """Return a lightweight structural inventory without hashing large models.

    File count and total byte size are cheap enough for hosted startup while
    still detecting missing/truncated/partial exports. Exact package wheels are
    additionally SHA-256 verified by the hosted-notebook bootstrap.
    """

    result: dict[str, dict[str, int]] = {}
    for name in CACHE_DIR_NAMES:
        root = namespace / name
        if not root.is_dir():
            raise FileNotFoundError(f"missing cache component: {name}")
        files = 0
        total_bytes = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            stat = path.stat()
            files += 1
            total_bytes += stat.st_size
        result[name] = {"files": files, "bytes": total_bytes}
    return result


def _stored_inventory(payload: Optional[dict[str, object]]) -> Optional[dict[str, object]]:
    if not payload:
        return None
    inventory = payload.get("inventory")
    return inventory if isinstance(inventory, dict) else None


def _validate_namespace(
    namespace: Path,
    fingerprint: RuntimeCacheFingerprint,
    *,
    allowed_states: Sequence[str] = ("ready",),
) -> tuple[bool, str, Optional[dict[str, dict[str, int]]]]:
    metadata = _read_metadata(namespace)
    if metadata is None:
        return False, "metadata missing or unreadable", None
    if not _fingerprint_matches(metadata, fingerprint):
        return False, "fingerprint is incompatible", None
    state = metadata.get("state")
    if state not in set(allowed_states):
        return False, f"cache state is {state!r}, not reusable", None
    expected = _stored_inventory(metadata)
    if expected is None:
        return False, "cache inventory missing", None
    try:
        actual = _tree_inventory(namespace)
    except (OSError, FileNotFoundError) as exc:
        return False, f"cache inventory unreadable: {exc}", None
    if actual != expected:
        return False, "cache inventory mismatch (missing/truncated/partial data)", actual
    return True, "cache is structurally valid", actual


def _write_metadata(
    namespace: Path,
    fingerprint: RuntimeCacheFingerprint,
    *,
    state: str,
    restored_from: Optional[Path] = None,
    inventory: Optional[dict[str, dict[str, int]]] = None,
    reason: Optional[str] = None,
) -> None:
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "fingerprint": fingerprint.to_dict(),
        "compatibility": fingerprint.compatibility_dict(),
        "state": state,
        "restored_from": str(restored_from) if restored_from else None,
        "inventory": inventory,
        "reason": reason,
        "updated_at": _utc_now(),
    }
    path = _metadata_path(namespace)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _cold_preparation(
    layout: RuntimeCacheLayout,
    fingerprint: RuntimeCacheFingerprint,
    local: Path,
    *,
    reason: str,
) -> CachePreparation:
    _reset_cache_tree(local)
    inventory = _tree_inventory(local)
    _write_metadata(
        local,
        fingerprint,
        state="cold",
        inventory=inventory,
        reason=reason,
    )
    return CachePreparation(
        layout=layout,
        fingerprint=fingerprint,
        local_namespace=local,
        fast_path=False,
        restored_from=None,
        reason=reason,
    )


def prepare_runtime_cache(
    layout: RuntimeCacheLayout,
    fingerprint: RuntimeCacheFingerprint,
) -> CachePreparation:
    """Restore a compatible, complete persistent cache into runtime-local SSD."""

    local = layout.local_namespace(fingerprint)
    source = layout.source_namespace(fingerprint)
    if source is None:
        return _cold_preparation(
            layout,
            fingerprint,
            local,
            reason="no persistent cache source configured",
        )

    valid, validation_reason, source_inventory = _validate_namespace(
        source,
        fingerprint,
        allowed_states=tuple(READY_STATES),
    )
    if not valid or source_inventory is None:
        return _cold_preparation(
            layout,
            fingerprint,
            local,
            reason=f"persistent cache rejected: {validation_reason}",
        )

    _reset_cache_tree(local)
    try:
        for name in CACHE_DIR_NAMES:
            _sync_tree(source / name, local / name)
        local_inventory = _tree_inventory(local)
    except (OSError, shutil.Error) as exc:
        return _cold_preparation(
            layout,
            fingerprint,
            local,
            reason=f"persistent cache restore failed; cold fallback: {exc}",
        )

    if local_inventory != source_inventory:
        return _cold_preparation(
            layout,
            fingerprint,
            local,
            reason="persistent cache restore inventory mismatch; cold fallback",
        )

    _write_metadata(
        local,
        fingerprint,
        state="restored",
        restored_from=source,
        inventory=local_inventory,
        reason="compatible persistent cache restored to local SSD",
    )
    return CachePreparation(
        layout=layout,
        fingerprint=fingerprint,
        local_namespace=local,
        fast_path=True,
        restored_from=source,
        reason="compatible persistent cache restored to local SSD",
    )


def apply_cache_environment(
    preparation: CachePreparation,
    *,
    environ: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Apply cache environment variables and return the values used."""

    env = os.environ if environ is None else environ
    root = preparation.local_namespace
    values = {
        "PIP_CACHE_DIR": str(root / "pip"),
        "HF_HOME": str(root / "huggingface"),
        "HUGGINGFACE_HUB_CACHE": str(root / "huggingface" / "hub"),
        "TRANSFORMERS_CACHE": str(root / "huggingface" / "transformers"),
        "TORCH_HOME": str(root / "torch"),
        "OMNIVOICE_WHISPER_CACHE": str(root / "whisper"),
    }
    for key, value in values.items():
        env[key] = value
        Path(value).mkdir(parents=True, exist_ok=True)
    return values


def persist_runtime_cache(preparation: CachePreparation) -> Optional[Path]:
    """Export local cache contents with a fail-closed two-phase ready marker."""

    target = preparation.layout.persist_namespace(preparation.fingerprint)
    if target is None:
        return None
    local = preparation.local_namespace
    _ensure_cache_tree(local)
    target.mkdir(parents=True, exist_ok=True)

    # Invalidate any previous ready marker before touching cache contents. If the
    # copy is interrupted, the next session observes ``writing`` and goes cold.
    _write_metadata(
        target,
        preparation.fingerprint,
        state="writing",
        inventory=None,
        restored_from=preparation.restored_from,
        reason="cache export in progress",
    )

    for name in CACHE_DIR_NAMES:
        destination = target / name
        if destination.exists():
            shutil.rmtree(destination)
        _sync_tree(local / name, destination)

    inventory = _tree_inventory(target)
    _write_metadata(
        target,
        preparation.fingerprint,
        state="ready",
        restored_from=preparation.restored_from,
        inventory=inventory,
        reason="cache export completed",
    )
    return target


def cache_status(
    layout: RuntimeCacheLayout,
    fingerprint: RuntimeCacheFingerprint,
) -> dict[str, object]:
    local = layout.local_namespace(fingerprint)
    source = layout.source_namespace(fingerprint)
    target = layout.persist_namespace(fingerprint)
    local_ready, local_reason, _ = _validate_namespace(
        local,
        fingerprint,
        allowed_states=tuple(LOCAL_READY_STATES),
    )
    if source is not None:
        source_ready, source_reason, _ = _validate_namespace(
            source,
            fingerprint,
            allowed_states=tuple(READY_STATES),
        )
    else:
        source_ready, source_reason = False, "no persistent source configured"
    return {
        "environment": layout.environment,
        "fingerprint": fingerprint.to_dict(),
        "cache_key": fingerprint.key,
        "package_key": fingerprint.package_key,
        "local_namespace": str(local),
        "local_ready": local_ready,
        "local_reason": local_reason,
        "source_namespace": str(source) if source else None,
        "source_ready": source_ready,
        "source_reason": source_reason,
        "persist_namespace": str(target) if target else None,
    }


def write_workspace_cache_metadata(
    workspace: Path | str,
    preparation: CachePreparation,
) -> Path:
    """Record reusable cache/runtime metadata beside the Studio workspace."""

    root = Path(workspace).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".runtime-cache.json"
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "environment": preparation.layout.environment,
        "cache_key": preparation.fingerprint.key,
        "package_key": preparation.fingerprint.package_key,
        "package_ref": preparation.fingerprint.package_ref,
        "cache_version": preparation.fingerprint.cache_version,
        "resource_signature": preparation.fingerprint.resource_signature,
        "fast_path": preparation.fast_path,
        "reason": preparation.reason,
        "local_namespace": str(preparation.local_namespace),
        "source_root": (
            str(preparation.layout.source_root)
            if preparation.layout.source_root
            else None
        ),
        "persist_root": (
            str(preparation.layout.persist_root)
            if preparation.layout.persist_root
            else None
        ),
        "updated_at": _utc_now(),
    }
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
    return path


def write_startup_cache_evidence(
    workspace: Path | str,
    preparation: CachePreparation,
    *,
    wheel_fast_path: bool,
    bootstrap_seconds: float,
) -> Path:
    """Write one machine-readable hosted-startup measurement sample."""

    root = Path(workspace).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "startup-cache-evidence.json"
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "environment": preparation.layout.environment,
        "package_ref": preparation.fingerprint.package_ref,
        "cache_key": preparation.fingerprint.key,
        "package_key": preparation.fingerprint.package_key,
        "resource_fast_path": preparation.fast_path,
        "wheel_fast_path": bool(wheel_fast_path),
        "cache_reason": preparation.reason,
        "bootstrap_seconds": round(float(bootstrap_seconds), 3),
        "recorded_at": _utc_now(),
    }
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
    return path
