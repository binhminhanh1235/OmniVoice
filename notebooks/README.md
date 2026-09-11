# OmniVoice hosted notebooks

This directory contains the maintained Colab/Kaggle entry points for OmniVoice Studio.

## Recommended notebooks

| Environment | Notebook | Purpose |
|---|---|---|
| Google Colab | `OmniVoice_Project_Studio_Colab.ipynb` | production Studio + local SSD + Drive persistence/cache + REST/SSE/MCP |
| Kaggle | `OmniVoice_Project_Studio_Kaggle.ipynb` | production Studio + local SSD + persistent startup-cache Dataset + dual-T4 mapping |
| Colab simple | `OmniVoice_Project_Studio_Colab_Gradio.ipynb` | simpler temporary Gradio workflow |
| Kaggle simple | `OmniVoice_Project_Studio_Kaggle_Gradio.ipynb` | simpler temporary Gradio workflow |
| Robust long-form Colab | `OmniVoice_Robust_LongForm_Colab.ipynb` | focused robust long-form demo |

For production work, prefer the two Project Studio notebooks.

## Production bootstrap

The production notebooks resolve an immutable OmniVoice source revision first, then execute `hosted_runtime_bootstrap.py` from that exact revision.

The bootstrap provides:

- exact source revision installation;
- exact model/ASR revision fingerprints;
- pip/wheel caching;
- exact wheel integrity validation;
- Hugging Face/model cache;
- Torch/Whisper cache reuse;
- versioned cache invalidation;
- safe cold fallback for corrupt or partial cache state;
- `startup-cache-evidence.json`.

A cached “last working revision” is intentionally not used as source-of-truth when the current exact revision cannot be resolved.

## Local-first rule

Active generation stays on runtime-local SSD.

### Colab

```text
/content/OmniVoiceStudio
```

Google Drive is the persistence/cache boundary.

### Kaggle

```text
/kaggle/working/OmniVoiceStudio
```

`/kaggle/input` is read-only and must not be used as the active render workspace.

## Persistent startup cache

### Colab

The persistent cache is stored under the Drive-backed Studio tree and restored into runtime-local cache storage on startup.

### Kaggle

The writable cache export is:

```text
/kaggle/working/OmniVoiceStartupCache
```

After a cold run, save/version that directory as a Kaggle Dataset named `omnivoice-startup-cache`. Attach it on the next run at:

```text
/kaggle/input/omnivoice-startup-cache
```

## Cold/warm production acceptance

Both production notebooks contain an acceptance checkpoint with:

```python
ACCEPTANCE_SAMPLE = ""
```

Use it only after the startup bootstrap has completed.

### Cold run

Set:

```python
ACCEPTANCE_SAMPLE = "cold"
```

and execute the acceptance cell. The notebook copies the current `startup-cache-evidence.json` into an exact-revision acceptance directory.

### Warm run

Restart the runtime with the compatible persistent cache mounted/attached, then set:

```python
ACCEPTANCE_SAMPLE = "warm"
```

and execute the same cell.

When both samples exist, the notebook fetches `scripts/hosted_cache_acceptance.py` from the same exact OmniVoice revision and runs the comparison.

PASS requires:

```text
same package_ref
warm.resource_fast_path == true
warm.wheel_fast_path == true
warm.bootstrap_seconds < cold.bootstrap_seconds
```

Do not label a warm session as cold. Do not publish synthetic hosted timing.

## Lazy CPU ASR Startup

For launchers using:

```text
--asr-device cpu
```

CPU ASR pipeline construction is deferred until the first real transcription/verification request.

Expected startup log:

```text
lazy_cpu_asr=True
CPU ASR startup deferred until first transcription/verification request.
```

Expected first-use log:

```text
Initializing ASR on first use: ... device=cpu
```

Explicit accelerator ASR such as `cuda:1` remains eager by design.

### Kaggle dual-T4

The production Kaggle notebook normally maps:

```text
cuda:0 -> OmniVoice TTS
cuda:1 -> Whisper ASR verification
```

Because this is explicit accelerator ASR, Lazy CPU ASR is not expected to activate in the dual-T4 case.

## Stable public endpoint

Both production notebooks can run the unified Studio server with UI + REST + SSE + MCP. Stable public access uses a remotely managed Cloudflare Tunnel and secrets supplied by the hosted platform.

Never hard-code tokens in the notebook.

## Validation

Repository CI validates the production notebooks as JSON and runs robust Project Studio regression when these notebooks change.

For the full manual production checklist, see:

```text
docs/production-acceptance.md
```