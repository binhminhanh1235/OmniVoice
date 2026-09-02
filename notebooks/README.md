# OmniVoice notebooks

## Project Studio

| Environment | Notebook | Use when |
|---|---|---|
| Colab | `OmniVoice_Project_Studio_Colab.ipynb` | Advanced Studio: Google Drive workspace, optional stable hostname, REST/SSE/MCP, private UI/API auth |
| Kaggle | `OmniVoice_Project_Studio_Kaggle.ipynb` | Advanced Studio: Kaggle local SSD, optional stable hostname, REST/SSE/MCP, private UI/API auth; optimized for dual-T4 with OmniVoice on `cuda:0` and Whisper on `cuda:1` |
| Colab | `OmniVoice_Project_Studio_Colab_Gradio.ipynb` | Simplest Colab workflow: install `master`, mount Google Drive, launch temporary Gradio share URL |
| Kaggle | `OmniVoice_Project_Studio_Kaggle_Gradio.ipynb` | Simplest Kaggle workflow: local SSD workspace and temporary Gradio share URL; auto-uses GPU1 for ASR when a second GPU is available |

## Kaggle dual-T4 profile

The maintained Kaggle notebooks assume `cuda:0` is the primary OmniVoice generation GPU. If Kaggle exposes a second CUDA device with enough VRAM, Whisper verification runs on that secondary GPU. A single-GPU session automatically falls back to CPU ASR so OmniVoice keeps the primary GPU VRAM to itself.

The notebooks also keep transient Hugging Face/Torch caches under `/kaggle/working/.cache` and enable PyTorch expandable CUDA segments to reduce allocator fragmentation during long queues.

## Other notebooks

- `OmniVoice.ipynb`: general OmniVoice demo plus robust long-form examples.
- `OmniVoice_Robust_LongForm_Colab.ipynb`: direct robust long-form Python workflow with ASR verification.

All maintained notebooks install from `binhminhanh1235/OmniVoice@master` rather than feature branches.

### Recommended starting point

For normal interactive use, start with one of the two `*_Gradio.ipynb` notebooks. They require no MCP, Cloudflare Tunnel, API token, or public-hostname configuration.

Use the advanced Project Studio notebook when you want ChatGPT / Claude Code / Antigravity integration through REST/MCP or a stable hostname across notebook sessions.
