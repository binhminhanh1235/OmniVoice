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

> **Fork note:** this repository extends the upstream [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice) model with **OmniVoice Studio**, a production-oriented long-form narration workspace, recovery layer, hosted-runtime workflow, REST/SSE/MCP server, and operational tooling. Model attribution, license, paper, and upstream links remain unchanged.

**Languages:** English | [Tiếng Việt](README.vi.md)

**Start here:** [Compact Vietnamese guide](docs/GUIDE-COMPACT.vi.md) | [Full Vietnamese guide](docs/GUIDE-FULL.vi.md) | [Studio roadmap](docs/project-studio-roadmap.md) | [Notebooks](notebooks/README.md)

OmniVoice is a massively multilingual zero-shot text-to-speech model supporting more than 600 languages. This fork keeps the core voice cloning, voice design, multilingual inference, pronunciation control, and training/evaluation stack, then adds a project-first Studio for reliable production of long-form narration.

## What this repository adds

### Production Studio

- **Unified project-first workspace** for Script, Voice, Preview, Render, Review, Export, History, Quality, Advanced Settings, and Storage.
- **Long-form project model**: Project -> Section -> Beat -> Chunk, with persistent manifests and section WAVs.
- **Crash-safe resume** using durable section/chunk state. Completed work is skipped after restart.
- **Targeted recovery**: regenerate one chunk or selected sections instead of rerendering the whole project.
- **Optional section-title narration** while keeping Markdown headings as metadata by default.
- **Leading conjunction protection** for fragile sentence starts such as "Or", "And", and "But".
- **Language selectors** across Studio workflows with English prioritized first while preserving backend language IDs.
- **Voice Library and Style Bank** with reusable voice-clone prompts and variants such as DEFAULT, WARM, SOFT, PRAYER, and EMPHASIZE.
- **Text Doctor, Voice Doctor, Voice Stability, preview, version history, quality presets, and advanced generation settings**.
- **Persistent multi-project queue** with pause/resume and project status filtering.
- **Local-first hosted execution** for Kaggle and Colab so active generation stays on local SSD rather than a remote filesystem.

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

Implemented production foundations include:

- persistent single-GPU Job Manager;
- resumable async project generation;
- idempotency keys;
- cooperative cancellation;
- durable job events and SSE replay;
- task-oriented MCP tools;
- stable Cloudflare named-tunnel support;
- scoped bearer authentication for machine APIs;
- optional Basic Auth protection for the Gradio UI.

### Performance and hosted-runtime work

- Reproducible benchmark framework with RTF, audio duration, model load time, and CUDA peak allocation.
- Kaggle local SSD workspace and dual-GPU-aware ASR placement.
- Persistent Colab/Kaggle dependency, model, and Whisper caching is being integrated separately and is **not considered merged until its PR lands on master**.
- Experimental target-only audio projection remains **off production master** until real TTS quality and end-to-end benchmark acceptance are proven.

## Current status

| Area | Status |
|---|---|
| Core OmniVoice inference and training | Merged |
| Robust long-form Project Studio | Merged |
| Unified project-first workspace | Merged |
| English-first language selectors | Merged |
| Leading "Or" pronunciation protection | Merged |
| Optional section-title narration | Merged |
| Job Manager + async generation | Merged |
| SSE job progress | Merged |
| MCP server | Merged |
| Stable named tunnel | Merged |
| API scopes / bearer auth | Merged |
| Benchmark framework | Merged |
| Persistent hosted-runtime cache | In review |
| Target-only inference | Experimental |
| Additional write APIs, agent adapters, control plane | Planned |

See [docs/project-studio-roadmap.md](docs/project-studio-roadmap.md) for the exact plan and status boundaries.

## Installation

### Recommended: install this fork

Create a fresh virtual environment, install the appropriate PyTorch build for your machine, then install this repository.

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

Apple Silicon can use `device_map="mps"` for direct Python inference. Production throughput is still best on a supported accelerator environment.

#### Development install

```bash
git clone https://github.com/binhminhanh1235/OmniVoice.git
cd OmniVoice
pip install -e .
```

The upstream PyPI package is useful for core OmniVoice features, but the Studio additions documented here track this fork's `master`.

## Fastest Studio start

### Local Gradio Studio

```bash
omnivoice-project-studio \
  --workspace ./OmniVoiceStudio \
  --port 7860
```

Use `--share` only when you intentionally want a temporary Gradio public URL.

### Unified UI + REST + SSE + MCP server

```bash
omnivoice-studio serve \
  --workspace ./OmniVoiceStudio \
  --host 127.0.0.1 \
  --port 8000
```

Open:

- UI: `http://127.0.0.1:8000/ui`
- API docs: `http://127.0.0.1:8000/docs`
- MCP: `http://127.0.0.1:8000/mcp`
- Health: `http://127.0.0.1:8000/health`

## Hosted notebooks

Maintained notebooks are under [notebooks/](notebooks/).

| Environment | Recommended notebook | Execution model |
|---|---|---|
| Colab | `OmniVoice_Project_Studio_Colab.ipynb` | local execution workspace with persistence boundary |
| Kaggle | `OmniVoice_Project_Studio_Kaggle.ipynb` | `/kaggle/working` local SSD, dual-T4 aware |
| Colab simple | `OmniVoice_Project_Studio_Colab_Gradio.ipynb` | temporary Gradio workflow |
| Kaggle simple | `OmniVoice_Project_Studio_Kaggle_Gradio.ipynb` | local SSD + temporary Gradio workflow |

Active generation should stay on local SSD. Remote Drive, Dataset, or cloud storage is a persistence/export boundary, not the render hot path.

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

Studio provides:

1. **Script**: paste and parse the full Markdown project.
2. **Voice**: create or reuse a saved voice and variant.
3. **Preview**: listen to representative samples.
4. **Render**: generate all or selected sections.
5. **Review**: inspect status and regenerate only failed chunks.
6. **Export**: merge verified sections and export production audio.
7. **Resume**: restart the runtime and continue unfinished work.

By default, Markdown section titles are not spoken. Enable **Read section titles (###)** when a project should narrate them.

## Quality presets

The primary presets are:

| Preset | Goal |
|---|---|
| SAFE | maximum verification and recovery effort |
| BALANCED | recommended production default |
| FAST | lower generation/retry effort while retaining text verification |

Advanced Settings can override selected behavior per project without replacing the preset as the normal configuration path.

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

### Reuse the voice prompt

```python
prompt = model.create_voice_clone_prompt(
    ref_audio="ref.wav",
    ref_text="Exact transcript of the reference audio.",
)
prompt.save("my_voice.pt")
```

Later:

```python
from omnivoice import VoiceClonePrompt

prompt = VoiceClonePrompt.load("my_voice.pt")
audio = model.generate(
    text="This session does not need to re-encode the reference.",
    voice_clone_prompt=prompt,
    language="en",
)
```

## Core generation modes

OmniVoice still supports the upstream generation modes:

- **Voice cloning** with reference audio;
- **Voice design** with supported speaker attributes;
- **Auto voice** without a reference;
- **Non-verbal controls** such as `[laughter]`;
- **English pronunciation overrides** using CMU phonemes;
- **Chinese pronunciation overrides** using pinyin with tones;
- optional text normalization via `omnivoice[tn]`.

See [docs/generation-parameters.md](docs/generation-parameters.md), [docs/voice-design.md](docs/voice-design.md), and [docs/tips.md](docs/tips.md).

## Command-line tools

| Command | Purpose |
|---|---|
| `omnivoice-project-studio` | production Project Studio UI |
| `omnivoice-studio serve` | unified Gradio + REST + SSE + MCP server |
| `omnivoice-benchmark` | reproducible inference benchmark |
| `omnivoice-demo` | interactive robust demo |
| `omnivoice-demo-legacy` | legacy upstream-style demo |
| `omnivoice-infer` | single-item inference |
| `omnivoice-infer-batch` | batch / multi-GPU inference |
| `omnivoice-merge-lora` | LoRA merge utility |

Run any command with `--help` for its current arguments.

## REST jobs

Submit generation asynchronously:

```http
POST /api/v1/projects/my-project/generate
Idempotency-Key: render-my-project-v1
Content-Type: application/json

{
  "voice_name": "Narrator",
  "voice_variant": "AUTO",
  "language": "en",
  "sections": ["S01", "S02"],
  "resume": true,
  "strict": false,
  "quality_preset": "BALANCED"
}
```

Track it through:

```text
GET  /api/v1/jobs/{job_id}
GET  /api/v1/jobs/{job_id}/events
GET  /api/v1/jobs/{job_id}/stream
POST /api/v1/jobs/{job_id}/cancel
```

## MCP

The mounted Streamable HTTP MCP endpoint is:

```text
http://HOST:PORT/mcp
```

Initial task-oriented tools include:

```text
studio_status
list_projects
inspect_project
queue_status
generate_project
get_job
cancel_job
```

Generation returns a durable `job_id` instead of holding an MCP call open for the full TTS render.

## Authentication and stable public hosting

For a public fixed hostname, use a named Cloudflare Tunnel and machine/API authentication.

Example environment:

```bash
export OMNIVOICE_API_TOKEN="replace-with-a-strong-secret"
export OMNIVOICE_API_TOKEN_SCOPES="omnivoice:read,omnivoice:generate,omnivoice:queue,omnivoice:mcp"
export OMNIVOICE_UI_USERNAME="studio"
export OMNIVOICE_UI_PASSWORD="replace-with-a-strong-password"
export CLOUDFLARE_TUNNEL_TOKEN="..."
export OMNIVOICE_PUBLIC_URL="https://omnivoice.example.com"
```

Then:

```bash
omnivoice-studio serve \
  --workspace ./OmniVoiceStudio \
  --host 0.0.0.0 \
  --port 8000 \
  --tunnel \
  --public-url https://omnivoice.example.com
```

Do not commit tokens or passwords. The tunnel implementation uses a private temporary token file rather than placing the raw tunnel token on the child-process command line.

See [docs/stable-tunnel.md](docs/stable-tunnel.md) and [docs/ai-native-mcp.md](docs/ai-native-mcp.md).

## Benchmarking

Use the production benchmark framework before changing inference behavior:

```bash
omnivoice-benchmark \
  --model k2-fsa/OmniVoice \
  --device cuda:0 \
  --preset BALANCED \
  --repeat 2 \
  --output benchmark.json
```

The framework reports model load time, generated audio duration, RTF, and CUDA peak allocation when available.

**Production rule:** speedups are not merged by assumption. Experimental inference must demonstrate measurable improvement plus output/projection equivalence and real TTS quality acceptance.

## Documentation map

- [Compact Vietnamese guide](docs/GUIDE-COMPACT.vi.md)
- [Full Vietnamese guide](docs/GUIDE-FULL.vi.md)
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

## Upstream compatibility policy

This fork follows upstream deliberately rather than blindly. Upstream changes are reviewed for:

- model and tokenizer compatibility;
- inference/output behavior;
- training compatibility;
- dependency and CUDA impact;
- interaction with Project Studio and verification;
- regression coverage before integration.

See the roadmap for current upstream-drift status and planned guard automation.

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

## Disclaimer

Do not use this model for unauthorized voice cloning, impersonation, fraud, scams, or illegal activity. Ensure that you have the rights and consent required for any voice data you use and comply with applicable laws and platform rules.
