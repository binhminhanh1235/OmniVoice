#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
# Licensed under the Apache License, Version 2.0

"""Persistent startup cache for ephemeral Colab/Kaggle runtimes.

Active generation always uses runtime-local SSD. Persistent storage is only a
restore/export source for pip wheels, Hugging Face/model data, Torch caches and
ASR/Whisper artifacts.

Caches are namespaced by an environment fingerprint instead of deleting stale
data in-place. A Python/image/package change therefore falls back to a cold
cache without risking reuse of incompatible binaries.
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
from typing import Callable, Mapping, Optional

from omnivoice.runtime_workspace import detect_runtime_environment


CACHE_SCHEMA_VERSION = 1
DEFAULT_CACHE_VERSION = "v1"
CACHE_DIR_NAMES = ("pip", "wheels", "huggingface", "torch", "whisper")


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

    @classmethod
    def current(
        cls,
        *,
        cache_version: str = DEFAULT_CACHE_VERSION,
        package_ref: str = "master",
    ) -> "RuntimeCacheFingerprint":
        return cls(
            schema_version=CACHE_SCHEMA_VERSION,
            cache_version=str(cache_version),
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
            system=platform.system().lower(),
            machine=platform.machine().lower(),
            package_ref=str(package_ref),
        )

    @property
    def key(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return f"{self.cache_version}-{digest}"

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
            # This becomes a reusable Kaggle output. Saving/versioning the notebook
            # can publish it as a Dataset for a later session.
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
    stored = payload.get("fingerprint")
    return isinstance(stored, dict) and stored == fingerprint.to_dict()


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


def _write_metadata(
    namespace: Path,
    fingerprint: RuntimeCacheFingerprint,
    *,
    state: str,
    restored_from: Optional[Path] = None,
) -> None:
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "fingerprint": fingerprint.to_dict(),
        "state": state,
        "restored_from": str(restored_from) if restored_from else None,
        "updated_at": _utc_now(),
    }
    path = _metadata_path(namespace)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def prepare_runtime_cache(
    layout: RuntimeCacheLayout,
    fingerprint: RuntimeCacheFingerprint,
) -> CachePreparation:
    """Restore a compatible persistent cache into runtime-local SSD."""

    local = layout.local_namespace(fingerprint)
    _ensure_cache_tree(local)

    source = layout.source_namespace(fingerprint)
    if source is None:
        _write_metadata(local, fingerprint, state="cold")
        return CachePreparation(
            layout=layout,
            fingerprint=fingerprint,
            local_namespace=local,
            fast_path=False,
            restored_from=None,
            reason="no persistent cache source configured",
        )

    metadata = _read_metadata(source)
    if not _fingerprint_matches(metadata, fingerprint):
        _write_metadata(local, fingerprint, state="cold")
        return CachePreparation(
            layout=layout,
            fingerprint=fingerprint,
            local_namespace=local,
            fast_path=False,
            restored_from=None,
            reason="persistent cache missing or fingerprint is incompatible",
        )

    for name in CACHE_DIR_NAMES:
        _sync_tree(source / name, local / name)
    _write_metadata(local, fingerprint, state="restored", restored_from=source)
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
        # OmniVoice's Whisper models are resolved through Hugging Face today.
        # Keep a dedicated ASR location for future/native Whisper consumers too.
        "OMNIVOICE_WHISPER_CACHE": str(root / "whisper"),
    }
    for key, value in values.items():
        env[key] = value
        Path(value).mkdir(parents=True, exist_ok=True)
    return values


def persist_runtime_cache(preparation: CachePreparation) -> Optional[Path]:
    """Export local cache contents to the compatible persistent namespace."""

    target = preparation.layout.persist_namespace(preparation.fingerprint)
    if target is None:
        return None
    local = preparation.local_namespace
    _ensure_cache_tree(local)
    target.mkdir(parents=True, exist_ok=True)
    for name in CACHE_DIR_NAMES:
        _sync_tree(local / name, target / name)
    _write_metadata(
        target,
        preparation.fingerprint,
        state="ready",
        restored_from=preparation.restored_from,
    )
    return target


def cache_status(
    layout: RuntimeCacheLayout,
    fingerprint: RuntimeCacheFingerprint,
) -> dict[str, object]:
    local = layout.local_namespace(fingerprint)
    source = layout.source_namespace(fingerprint)
    target = layout.persist_namespace(fingerprint)
    return {
        "environment": layout.environment,
        "fingerprint": fingerprint.to_dict(),
        "cache_key": fingerprint.key,
        "local_namespace": str(local),
        "local_ready": _fingerprint_matches(_read_metadata(local), fingerprint),
        "source_namespace": str(source) if source else None,
        "source_ready": (
            _fingerprint_matches(_read_metadata(source), fingerprint) if source else False
        ),
        "persist_namespace": str(target) if target else None,
    }
