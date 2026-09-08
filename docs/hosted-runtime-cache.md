# Persistent hosted-runtime startup cache

OmniVoice Studio keeps **active generation on local SSD** while reusing unchanged
installation and model assets across ephemeral Colab/Kaggle sessions.

## What is cached

A cache namespace contains:

- `pip/`: pip download/build cache;
- `wheels/`: OmniVoice wheels, with each exact source revision isolated by package SHA;
- `huggingface/`: OmniVoice, audio-tokenizer, and Transformers/Hugging Face assets;
- `torch/`: Torch hub/runtime cache;
- `whisper/`: reserved ASR/Whisper cache for consumers that do not use the Hugging Face cache;
- `metadata.json`: compatibility/version state.

The current Whisper models are resolved through Hugging Face, so their model
weights live under the local `HF_HOME` and are persisted together with the main
OmniVoice model.

## Compatibility and invalidation

Cache reuse is conservative and deterministic.

The resource-cache namespace is keyed by:

- cache schema version;
- explicit cache version;
- Python major/minor;
- operating system;
- CPU architecture.

The exact OmniVoice package revision has a **separate package key**. This means a
new repository commit rebuilds only the small OmniVoice wheel while unchanged
model/Hugging Face/Whisper assets remain reusable.

A Python/runtime/cache-version mismatch selects another namespace and takes the
cold-start path. Old namespaces are not silently reused or destructively
overwritten.

## Fast path

1. Resolve the current OmniVoice source revision.
2. Find a compatible persistent cache namespace.
3. Restore it to runtime-local SSD.
4. Install the exact cached OmniVoice wheel when present, otherwise rebuild only
   that wheel.
5. Point `PIP_CACHE_DIR`, `HF_HOME`, `HUGGINGFACE_HUB_CACHE`,
   `TRANSFORMERS_CACHE`, and `TORCH_HOME` at local SSD.
6. Warm the OmniVoice and Whisper snapshots locally.
7. Continue generation entirely from local SSD.

## Cold-start fallback

If no compatible cache exists, Studio uses the normal network install/download
path, populates the local cache, and exports the finished cache for a later
session. A missing or stale cache therefore affects startup time only, not
correctness.

## Colab

The production Colab notebook uses:

```text
local cache:       /content/.cache/omnivoice
persistent cache:  MyDrive/OmniVoiceStudio/.startup-cache
active workspace:  /content/OmniVoiceStudio
persistent data:   MyDrive/OmniVoiceStudio
```

Project audio/checkpoint writes never occur on the Drive FUSE mount. The
persistent workspace is restored once to local SSD and mirrored back in the
background plus a final best-effort sync when Studio exits.

## Kaggle

The production Kaggle notebook uses:

```text
local cache:       /kaggle/working/.cache/omnivoice
cache export:      /kaggle/working/OmniVoiceStartupCache
active workspace:  /kaggle/working/OmniVoiceStudio
```

If a Dataset is attached at:

```text
/kaggle/input/omnivoice-startup-cache
```

it becomes the read-only startup-cache source. On a cold run, the notebook
exports a complete compatible cache under
`/kaggle/working/OmniVoiceStartupCache`. Save/version that directory as a
Kaggle Dataset named `omnivoice-startup-cache`, then attach it to later
sessions to activate the fast path.

For another persistence backend, set:

```text
OMNIVOICE_CACHE_SOURCE
OMNIVOICE_CACHE_PERSIST_ROOT
OMNIVOICE_LOCAL_CACHE_ROOT
```

The source may be read-only. The persist root is optional.

## Workspace metadata

Each prepared Studio workspace receives `.runtime-cache.json` with the cache
version, package revision, package/cache keys, source/persist roots, and whether
the session started on the fast path. This makes support/debugging reproducible
without embedding credentials or tokens.

## API

`omnivoice.runtime_cache` exposes:

- `RuntimeCacheFingerprint.current()`
- `detect_runtime_cache()`
- `prepare_runtime_cache()`
- `apply_cache_environment()`
- `persist_runtime_cache()`
- `write_workspace_cache_metadata()`
- `cache_status()`

No cache API downloads models by itself. Hosted notebooks explicitly warm the
known model IDs after local cache variables are applied.
