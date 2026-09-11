# Persistent hosted-runtime startup cache

OmniVoice Studio keeps **active generation on local SSD** while reusing compatible installation and model assets across ephemeral Colab/Kaggle sessions.

Correctness wins over startup speed. A cache is never accepted merely because a directory exists: source code, model revisions, runtime compatibility, export completion state, structural inventory and exact-wheel integrity are checked before reuse.

## What is cached

A cache namespace contains:

- `pip/`: pip download/build cache;
- `wheels/`: OmniVoice wheels isolated by exact source commit;
- `huggingface/`: OmniVoice, audio-tokenizer and Transformers/Hugging Face assets;
- `torch/`: Torch hub/runtime cache;
- `whisper/`: ASR/Whisper cache for consumers outside the Hugging Face cache;
- `metadata.json`: compatibility, inventory and transactional export state.

The hosted bootstrap itself lives at `notebooks/hosted_runtime_bootstrap.py`. Production notebooks resolve and execute that file from the same immutable OmniVoice commit that will be installed.

## Exact revisions and fail-closed behavior

The notebook first resolves an exact 40-character OmniVoice commit SHA. It never falls back to `last_package_ref` and never treats the mutable string `master` as a reusable package identity.

Resolution order:

1. use `OMNIVOICE_PACKAGE_REF` when it contains an explicit 40-character commit SHA;
2. otherwise resolve the current `master` SHA from GitHub;
3. if neither is possible, stop with a clear error instead of silently running old code.

The bootstrap also resolves exact Hugging Face revisions for:

- `k2-fsa/OmniVoice`;
- `openai/whisper-small.en`.

They may be explicitly pinned with:

```text
OMNIVOICE_MODEL_REVISION
OMNIVOICE_ASR_REVISION
```

Both overrides must also be exact 40-character revisions. If current model revisions cannot be resolved and no exact override was supplied, startup fails closed rather than silently reusing stale weights.

## Compatibility and invalidation

Cache schema/cache version are currently `2` / `v2`.

The resource-cache namespace is keyed by:

- cache schema version;
- explicit cache version;
- Python major/minor;
- operating system;
- CPU architecture;
- exact OmniVoice model revision;
- exact ASR model revision;
- libc identity/version folded into the resource signature.

The exact OmniVoice package revision has a **separate package key**. A new source commit can therefore rebuild only the small project wheel while an otherwise identical model/runtime namespace stays reusable.

Any incompatible fingerprint selects another namespace and takes the cold path.

## Transactional cache persistence

Persistent cache export is two-phase:

1. write metadata state `writing` before changing persistent cache contents;
2. replace cache components;
3. compute the structural inventory;
4. atomically publish metadata state `ready` only after the export completed.

If a runtime stops during export, the next session sees `writing` and rejects that namespace. A partially overwritten cache is never classified as warm.

The inventory records file count and total bytes for each cache component. Missing directories, deleted files, truncation and incomplete copies therefore force a clean local cold fallback. This avoids hashing multi-gigabyte model files on every startup.

## Exact-wheel integrity

Each exact-source wheel directory carries `wheel-manifest.json` containing:

- exact package SHA;
- wheel filename;
- byte size;
- SHA-256 digest.

Before a wheel is reused, the bootstrap verifies all four fields and validates the wheel ZIP. A missing, wrong, truncated or content-corrupted wheel is discarded and rebuilt from the exact source SHA.

## Fast path

1. Resolve exact OmniVoice, model and ASR revisions.
2. Select the matching compatibility namespace.
3. Reject any namespace not in `ready` state or with an inventory mismatch.
4. Restore persistent resources to runtime-local SSD.
5. Verify/install the exact cached OmniVoice wheel, or rebuild only that wheel.
6. Point pip, Hugging Face, Transformers, Torch and Whisper caches at local SSD.
7. Request the two pinned Hugging Face snapshots by exact revision.
8. Continue Studio generation entirely from local SSD.

GitHub/Hugging Face revision resolution and loading the exact bootstrap are small control-plane network operations. Large package/model assets are what the persistent cache removes from the warm path.

## Cold-start and corruption fallback

A missing, incompatible, incomplete or structurally corrupted resource namespace is rejected and recreated locally. After the required assets are available, the complete cache is exported again for future sessions.

A bad exact wheel is never installed from cache: its SHA-256/ZIP verification must pass or the wheel is rebuilt from the exact package revision.

## Colab

The production Colab notebook uses:

```text
local cache:       /content/.cache/omnivoice
persistent cache:  MyDrive/OmniVoiceStudio/.startup-cache
active workspace:  /content/OmniVoiceStudio
persistent data:   MyDrive/OmniVoiceStudio
```

Project audio/checkpoint writes do not use Drive as the render hot path. The persistent workspace is restored once to local SSD and mirrored back every 45 seconds plus a final sync when Studio exits.

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

it becomes the read-only startup-cache source. On a cold run, save/version `/kaggle/working/OmniVoiceStartupCache` as a Kaggle Dataset named `omnivoice-startup-cache`, then attach that Dataset to the next session.

For another persistence backend:

```text
OMNIVOICE_CACHE_SOURCE
OMNIVOICE_CACHE_PERSIST_ROOT
OMNIVOICE_LOCAL_CACHE_ROOT
```

## Deterministic local acceptance

The focused CI gate runs:

```bash
python -m py_compile omnivoice/runtime_cache.py notebooks/hosted_runtime_bootstrap.py
python -m json.tool notebooks/OmniVoice_Project_Studio_Colab.ipynb >/dev/null
python -m json.tool notebooks/OmniVoice_Project_Studio_Kaggle.ipynb >/dev/null
pytest -q tests/test_runtime_cache.py tests/test_hosted_runtime_bootstrap.py
```

Those tests cover cold -> persist -> warm restore, runtime/resource invalidation, interrupted `writing` state, missing/truncated cache data, exact-SHA validation, exact-wheel hash corruption and startup evidence.

## Real Colab/Kaggle cold/warm acceptance

Real startup time depends on hosted storage/network/runtime images, so it must be measured on the target platform rather than simulated in CI.

Run the startup cell once with no compatible v2 cache. Save the generated file:

```text
<WORKSPACE>/startup-cache-evidence.json
```

For Colab, restart the runtime while keeping the Drive cache. For Kaggle, save `/kaggle/working/OmniVoiceStartupCache` as Dataset `omnivoice-startup-cache`, attach it to a fresh session, and rerun the startup cell.

Then inspect:

```python
import json
from pathlib import Path
print(json.dumps(json.loads(Path(WORKSPACE, "startup-cache-evidence.json").read_text()), indent=2))
```

Warm acceptance requires:

```text
same package_ref when comparing the exact same code revision
resource_fast_path = true
wheel_fast_path = true
bootstrap_seconds(warm) < bootstrap_seconds(cold)
Studio still launches and renders from the local WORKSPACE path
```

Keep both evidence JSON files and record their `bootstrap_seconds` in the roadmap/table. Do not invent a hosted-runtime speedup from local CI timing.

## Workspace metadata

Each prepared Studio workspace receives:

- `.runtime-cache.json`: cache identity, exact package/model resource signature, local/source/persist roots, fast/cold reason;
- `startup-cache-evidence.json`: package SHA, cache/package keys, resource/wheel fast-path flags and measured bootstrap seconds.

Neither file contains credentials or tokens.

## API

`omnivoice.runtime_cache` exposes:

- `RuntimeCacheFingerprint.current()`
- `detect_runtime_cache()`
- `prepare_runtime_cache()`
- `apply_cache_environment()`
- `persist_runtime_cache()`
- `write_workspace_cache_metadata()`
- `write_startup_cache_evidence()`
- `cache_status()`
