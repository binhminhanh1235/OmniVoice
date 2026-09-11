# OmniVoice 🌍 + OmniVoice Studio

<p align="center">
  <img width="200" height="200" alt="OmniVoice" src="https://zhu-han.github.io/omnivoice/pics/omnivoice.jpg" />
</p>

<p align="center">
  <a href="https://huggingface.co/k2-fsa/OmniVoice"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Model-FFD21E" alt="Hugging Face Model"></a>
  &nbsp;
  <a href="https://arxiv.org/abs/2604.00688"><img src="https://img.shields.io/badge/arXiv-Paper-B31B1B.svg"></a>
  &nbsp;
  <a href="https://zhu-han.github.io/omnivoice"><img src="https://img.shields.io/badge/GitHub.io-Upstream_Demo-blue?logo=GitHub&style=flat-square"></a>
</p>

> **Fork note:** this repository extends upstream [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice) with **OmniVoice Studio**, a production-oriented long-form narration workspace, recovery layer, hosted-runtime workflow, REST/SSE/MCP server, persistent startup caching, and operational tooling. Model attribution, paper, license, and upstream links remain unchanged.

**Languages:** English | [Tiếng Việt](README.vi.md)

**Start here:** [Compact Vietnamese guide](docs/GUIDE-COMPACT.vi.md) | [Full Vietnamese guide](docs/GUIDE-FULL.vi.md) | [Production acceptance](docs/production-acceptance.md) | [Studio roadmap](docs/project-studio-roadmap.md) | [Notebooks](notebooks/README.md)

OmniVoice is a massively multilingual zero-shot text-to-speech model supporting more than 600 languages. This fork keeps the core voice-cloning, voice-design, multilingual inference, pronunciation-control, and training/evaluation stack, then adds a project-first Studio for reliable long-form production.

## What this repository adds

### Production Studio

- Unified project-first workflow for Script, Voice, Preview, Render, Review, Export, History, Quality, Advanced Settings, and Storage.
- Long-form project model: `Project -> Section -> Beat -> Chunk`, with persistent manifests and section audio.
- Crash-safe resume that skips already completed work after a runtime restart.
- Targeted recovery for one chunk or selected sections instead of full rerenders.
- Optional `###` section-title narration while headings remain metadata by default.
- Leading conjunction protection for fragile starts such as `Or`, `And`, and `But`.
- English-first language selectors while preserving backend language identifiers.
- Voice Library and Style Bank with reusable clone prompts and variants such as `DEFAULT`, `WARM`, `SOFT`, `PRAYER`, and `EMPHASIZE`.
- Text Doctor, Voice Doctor, Voice Stability, preview, version history, quality presets, and advanced settings.
- Persistent multi-project queue with pause/resume and project status filtering.
- Local-first execution for Colab and Kaggle so active generation stays on runtime-local SSD.

### AI-native Studio server

One process can expose:

```text
/ui                         Gradio Studio
/api/v1                     REST / OpenAPI
/api/v1/jobs/{id}/stream    Server-Sent Events
/mcp                        Streamable HTTP MCP
/health                     Health
/docs                       OpenAPI docs
```

Production foundations include persistent GPU jobs, resumable async generation, idempotency keys, cooperative cancellation, durable events and SSE replay, task-oriented MCP tools, Cloudflare named-tunnel support, bearer scopes for machine APIs, and optional Basic Auth for the UI.

### Hosted-runtime performance

The production hosted-runtime path now includes:

- exact OmniVoice source revision resolution;
- exact model and ASR revision fingerprints;
- persistent pip and wheel caches;
- exact wheel size, SHA-256, and ZIP-integrity validation;
- persistent Hugging Face/model, Torch, and Whisper caches;
- versioned cache namespaces with invalidation on incompatible revisions;
- safe rejection of interrupted, truncated, or corrupt cache state;
- local-SSD hot paths for active generation;
- deterministic startup evidence in `startup-cache-evidence.json`;
- **lazy CPU ASR startup** in Studio launchers, while explicit accelerator ASR remains eager.

No hosted speed number is claimed without a real Colab/Kaggle cold/warm run.

## Current status

| Area | Status |
|---|---|
| Core OmniVoice inference and training | Merged |
| Robust long-form Project Studio | Merged |
| Unified project-first workspace | Merged |
| English-first language selectors | Merged |
| Leading `Or` pronunciation protection | Merged |
| Optional section-title narration | Merged |
| Job Manager + async generation | Merged |
| SSE job progress | Merged |
| MCP server | Merged |
| Stable named tunnel | Merged |
| API scopes / bearer auth | Merged |
| Benchmark framework | Merged |
| Persistent Colab/Kaggle startup cache | **Merged / Verified** |
| Lazy CPU ASR startup | **Merged / Verified** |
| Target-only inference | Experimental, not production-enabled |
| Additional write APIs, agent adapters, control plane | Planned |

See [docs/project-studio-roadmap.md](docs/project-studio-roadmap.md) for status boundaries and [docs/production-acceptance.md](docs/production-acceptance.md) for hosted acceptance rules.

## Installation

### Recommended fork install

Create a fresh virtual environment, install the appropriate PyTorch build, then install this repository.

#### NVIDIA CUDA 12.8 example

```bash
python -m venv .venv
source .venv/bin/activate

pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 \
  --extra-index-url https://download.pytorch.org/whl/cu128

pip install "git+https://github.com/binhminhanh1235/OmniVoice.git@master"
```

On Windows, activate with `.venv\Scripts\activate`.

#### Apple Silicon

```bash
python -m venv .venv
source .venv/bin/activate
pip install torch==2.8.0 torchaudio==2.8.0
pip install "git+https://github.com/binhminhanh1235/OmniVoice.git@master"
```

Direct Python inference can use `device_map="mps"`. Production throughput is still best on a supported accelerator environment.

#### Development install

```bash
git clone https://github.com/binhminhanh1235/OmniVoice.git
cd OmniVoice
pip install -e .
```

## Fastest Studio start

### Local Gradio Studio

```bash
omnivoice-project-studio \
  --workspace ./OmniVoiceStudio \
  --port 7860
```

Use `--share` only when you intentionally want a temporary Gradio public URL.

### Unified UI + REST + SSE + MCP

```bash
omnivoice-studio serve \
  --workspace ./OmniVoiceStudio \
  --host 127.0.0.1 \
  --port 8000
```

Open:

- UI: `http://127.0.0.1:8000/ui`
- API: `http://127.0.0.1:8000/api/v1`
- OpenAPI: `http://127.0.0.1:8000/docs`
- MCP: `http://127.0.0.1:8000/mcp`
- Health: `http://127.0.0.1:8000/health`

## Lazy CPU ASR startup

Studio launchers no longer construct CPU Whisper during server startup. With the default CPU ASR placement:

```text
server/model startup
    -> ASR pipeline not constructed
first real transcription or verification
    -> one model-scoped ASR initialization
later requests
    -> reuse the same ASR pipeline
```

The initialization gate is thread-safe. A failed first load does not publish a partial pipeline, so a later request can retry. Explicit accelerator placement such as `--asr-device cuda:1` remains eager by design.

Useful startup evidence:

```text
lazy_cpu_asr=True
CPU ASR startup deferred until first transcription/verification request.
```

On first CPU ASR use, the runtime logs:

```text
Initializing ASR on first use: ...
```

Kaggle dual-T4 commonly uses `cuda:0` for TTS and `cuda:1` for ASR, so that explicit accelerator mapping intentionally stays eager.

## Hosted notebooks

Maintained notebooks are under [notebooks/](notebooks/).

| Environment | Recommended notebook | Execution model |
|---|---|---|
| Colab | `OmniVoice_Project_Studio_Colab.ipynb` | local SSD workspace + Drive persistence/cache boundary |
| Kaggle | `OmniVoice_Project_Studio_Kaggle.ipynb` | `/kaggle/working` local SSD + versioned startup-cache Dataset |
| Colab simple | `OmniVoice_Project_Studio_Colab_Gradio.ipynb` | temporary Gradio workflow |
| Kaggle simple | `OmniVoice_Project_Studio_Kaggle_Gradio.ipynb` | local SSD + temporary Gradio workflow |

Active generation should stay on local SSD. Remote Drive, Dataset, or cloud storage is a persistence/export boundary, not the render hot path.

### Cold/warm cache acceptance

The production notebooks write `startup-cache-evidence.json`. Save one genuine cold sample and one genuine warm sample from the **same exact package revision**, then run:

```bash
python scripts/hosted_cache_acceptance.py cold.json warm.json
```

A passing warm sample must have:

```text
same package_ref
resource_fast_path = true
wheel_fast_path    = true
warm bootstrap_seconds < cold bootstrap_seconds
```

The production notebooks include an acceptance checkpoint that can store `cold.json` / `warm.json` and execute the exact-revision acceptance script when both samples exist. Do not label an already-warm session as cold.

## Project workflow

A typical script:

```markdown
# Video title

## S01 - 0:00-0:45
### Opening

[WARM] Not every time you step in, you are actually helping.

## S02 - 0:45-1:30
[SOFT] The question is what happens next.
Do they own what is true?
Or do they rewrite the conversation until you become the villain?
```

Recommended flow:

1. **Script**: parse the full Markdown project.
2. **Voice**: create or reuse a saved voice and variant.
3. **Preview**: listen to representative samples.
4. **Render**: generate all or selected sections.
5. **Review**: inspect status and regenerate only failed chunks.
6. **Export**: merge verified sections and export production audio.
7. **Resume**: restart and continue unfinished work when necessary.

By default, Markdown section titles are not spoken. Enable **Read section titles (###)** when a project should narrate them.

## Quality presets

| Preset | Goal |
|---|---|
| SAFE | maximum verification and recovery effort |
| BALANCED | recommended production default |
| FAST | lower generation/retry effort while retaining verification |

Use Advanced Settings for deliberate per-project overrides, not as the default configuration path.

## Voice cloning Python API

```python
import soundfile as sf
import torch
from omnivoice import OmniVoice

model = OmniVoice.from_pretrained(
    "k2-fsa/OmniVoice",
    device_map="cuda:0",
    dtype=torch.float16,
)

audio = model.generate(
    text="Hello, this is a voice-cloning test.",
    ref_audio="ref.wav",
    ref_text="Exact transcript of the reference audio.",
    language="en",
)

sf.write("out.wav", audio[0], model.sampling_rate)
```

Reuse an encoded voice prompt when possible:

```python
prompt = model.create_voice_clone_prompt(
    ref_audio="ref.wav",
    ref_text="Exact transcript of the reference audio.",
)
prompt.save("my_voice.pt")
```

## Command-line tools

| Command | Purpose |
|---|---|
| `omnivoice-project-studio` | production Project Studio UI |
| `omnivoice-studio serve` | unified Gradio + REST + SSE + MCP server |
| `omnivoice-benchmark` | reproducible inference benchmark |
| `omnivoice-demo` | robust interactive demo |
| `omnivoice-demo-legacy` | legacy upstream-style demo |
| `omnivoice-infer` | single-item inference |
| `omnivoice-infer-batch` | batch / multi-GPU inference |
| `omnivoice-merge-lora` | LoRA merge utility |

Run a command with `--help` for its current arguments.

## REST jobs and MCP

Submit project generation asynchronously, then track the durable job ID through REST/SSE or MCP. Initial task-oriented MCP tools include:

```text
studio_status
list_projects
inspect_project
queue_status
generate_project
get_job
cancel_job
```

Generation returns a durable `job_id` instead of keeping one agent call open for the entire render.

## Stable public hosting

For a fixed public hostname, use a remotely managed Cloudflare Tunnel and machine/API authentication.

```bash
export OMNIVOICE_API_TOKEN="replace-with-a-strong-secret"
export OMNIVOICE_API_TOKEN_SCOPES="omnivoice:read,omnivoice:generate,omnivoice:queue,omnivoice:mcp"
export OMNIVOICE_UI_USERNAME="studio"
export OMNIVOICE_UI_PASSWORD="replace-with-a-strong-password"
export CLOUDFLARE_TUNNEL_TOKEN="..."
export OMNIVOICE_PUBLIC_URL="https://omnivoice.example.com"
```

Do not commit tokens or passwords.

## Benchmarking and optimization policy

```bash
omnivoice-benchmark \
  --model k2-fsa/OmniVoice \
  --device cuda:0 \
  --preset BALANCED \
  --repeat 2 \
  --output benchmark.json
```

The benchmark framework reports model load time, generated audio duration, RTF, and CUDA peak allocation when available.

**Production rule:** optimization claims require real evidence. Experimental target-only inference remains non-production until it has real GPU speed data, output/projection equivalence, voice-clone quality, ASR quality, pacing, perceptual A/B, long-form acceptance, memory evidence, and no training/API regression.

## Documentation map

- [Compact Vietnamese guide](docs/GUIDE-COMPACT.vi.md)
- [Full Vietnamese guide](docs/GUIDE-FULL.vi.md)
- [Production acceptance](docs/production-acceptance.md)
- [Project Studio roadmap](docs/project-studio-roadmap.md)
- [Project Studio details](docs/project-studio.md)
- [AI-native foundation](docs/ai-native-foundation.md)
- [SSE](docs/ai-native-sse.md)
- [MCP](docs/ai-native-mcp.md)
- [Stable tunnel](docs/stable-tunnel.md)
- [Hardware and quality presets](docs/hardware-quality-presets.md)
- [Advanced settings](docs/advanced-settings.md)
- [Kaggle workspace](docs/kaggle-local-workspace.md)
- [Notebooks](notebooks/README.md)

## Upstream compatibility

This fork follows upstream deliberately rather than blindly. Upstream changes are reviewed for model/tokenizer compatibility, inference behavior, training compatibility, dependency/CUDA impact, Studio interaction, and regression coverage before integration.

## Training & evaluation

The upstream training/evaluation pipeline remains available. See [examples/](examples/) for data preparation, training, evaluation, and fine-tuning workflows.

## Citation

```bibtex
@article{zhu2026omnivoice,
  title={OmniVoice: Towards Omnilingual Zero-Shot Text-to-Speech with Diffusion Language Models},
  author={Zhu, Han and Ye, Lingxuan and Kang, Wei and Yao, Zengwei and Guo, Liyong and Kuang, Fangjun and Han, Zhifeng and Zhuang, Weiji and Lin, Long and Povey, Daniel},
  journal={arXiv preprint arXiv:2604.00688},
  year={2026}
}
```

## License

See [LICENSE](LICENSE).