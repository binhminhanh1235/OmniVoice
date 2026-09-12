# OmniVoice hosted notebooks

This directory contains the maintained Colab/Kaggle entry points for OmniVoice Studio.

## Recommended notebooks

| Environment | Notebook | Purpose |
|---|---|---|
| Google Colab | `OmniVoice_Project_Studio_Colab.ipynb` | production Studio + local SSD + Drive persistence/cache + REST/SSE/MCP |
| Kaggle stable server | `OmniVoice_Project_Studio_Kaggle.ipynb` | production Studio + local SSD + persistent startup-cache Dataset + dual-T4 mapping + optional stable named tunnel |
| Kaggle Gradio Full Studio | `OmniVoice_Project_Studio_Kaggle_Gradio.ipynb` | full Gradio Studio UI with exact-revision/P2 cache; default unified temporary Cloudflare URL also exposes REST/SSE/OpenAPI/MCP |
| Colab simple | `OmniVoice_Project_Studio_Colab_Gradio.ipynb` | simpler temporary Gradio workflow |
| Robust long-form Colab | `OmniVoice_Robust_LongForm_Colab.ipynb` | focused robust long-form demo |

For a stable remotely managed hostname on Kaggle, use `OmniVoice_Project_Studio_Kaggle.ipynb`. For an interactive Gradio-first Kaggle session that still needs the complete Studio platform surface, use `OmniVoice_Project_Studio_Kaggle_Gradio.ipynb` in its default `unified` mode.

## Kaggle Gradio Full Studio

`OmniVoice_Project_Studio_Kaggle_Gradio.ipynb` is no longer a minimal `@master` launcher. It uses the same immutable hosted-runtime bootstrap and cache contract as the production Kaggle notebook.

Its full interactive Gradio UI includes:

- Projects / Workspace;
- Text Doctor;
- Section History;
- Queue;
- Pause / Resume;
- Voice Library / Voice Doctor;
- Hardware & Quality;
- Advanced settings;
- Export;
- Storage & Backup;
- audio download controls.

The notebook has two launch modes:

```python
LAUNCH_MODE = "unified"  # "unified" or "gradio-share"
```

### `unified` (default)

A temporary Cloudflare Quick Tunnel is created and its exact public origin is supplied to the unified OmniVoice Studio server before startup. One process exposes:

```text
<public-url>/ui       Gradio Studio
<public-url>/api/v1   REST API + durable jobs/SSE
<public-url>/docs     OpenAPI
<public-url>/mcp      MCP
<public-url>/health   health/capabilities
```

Secure public mode reads these Kaggle Secrets:

```text
OMNIVOICE_API_TOKEN
OMNIVOICE_UI_USERNAME
OMNIVOICE_UI_PASSWORD
```

Do not hard-code these values into the notebook. Machine-token scopes include read, generate, queue and MCP.

For a deliberate disposable unauthenticated test only, set:

```python
ALLOW_INSECURE_PUBLIC = True
```

This enables `OMNIVOICE_ALLOW_INSECURE_PUBLIC=1`. Do not use that mode for a URL you intend to share or keep running unattended.

### `gradio-share`

This launches `omnivoice-project-studio --share`. It still provides the complete interactive Studio UI listed above, but REST/OpenAPI/MCP/SSE surfaces are intentionally not exposed.

## Production bootstrap

The maintained production-capable notebooks resolve an immutable OmniVoice source revision first, then execute `hosted_runtime_bootstrap.py` from that exact revision.

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

`/kaggle/input` is read-only and must not be used as the active render workspace. Project data in `/kaggle/working` remains ephemeral unless you export/sync it, including through **Settings > Storage & Backup**.

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

Both maintained Kaggle Studio notebooks use this boundary.

## Cold/warm production acceptance

The production-capable hosted notebooks contain an acceptance checkpoint with:

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

The maintained Kaggle Studio notebooks normally map:

```text
cuda:0 -> OmniVoice TTS
cuda:1 -> Whisper ASR verification
```

Because this is explicit accelerator ASR, Lazy CPU ASR is not expected to activate in the dual-T4 case. On a single-GPU session, the hardware recommendation may place ASR on CPU, where lazy startup applies.

## Public endpoints

`OmniVoice_Project_Studio_Kaggle.ipynb` is the choice for a stable remotely managed Cloudflare hostname.

`OmniVoice_Project_Studio_Kaggle_Gradio.ipynb` defaults to a temporary authenticated Cloudflare Quick Tunnel in `unified` mode. The public origin is discovered before Studio starts so the server's public-host and MCP security policy bind to the exact generated hostname.

Never hard-code tokens in a notebook.

## Validation

Repository CI validates the production-capable notebooks as JSON. The Kaggle Gradio Full Studio notebook is also covered by hosted-cache acceptance-contract tests and the robust Project Studio regression suite.

For the full manual production checklist, see:

```text
docs/production-acceptance.md
```
