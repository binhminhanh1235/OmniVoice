# OmniVoice notebooks

## Project Studio

| Environment | Notebook | Use when |
|---|---|---|
| Colab | `OmniVoice_Project_Studio_Colab.ipynb` | Advanced Studio: Google Drive workspace, optional stable hostname, REST/SSE/MCP, private UI/API auth |
| Kaggle | `OmniVoice_Project_Studio_Kaggle.ipynb` | Advanced Studio: Kaggle local SSD, optional stable hostname, REST/SSE/MCP, private UI/API auth |
| Colab | `OmniVoice_Project_Studio_Colab_Gradio.ipynb` | Simplest Colab workflow: install `master`, mount Google Drive, launch temporary Gradio share URL |
| Kaggle | `OmniVoice_Project_Studio_Kaggle_Gradio.ipynb` | Simplest Kaggle workflow: local SSD workspace and temporary Gradio share URL |

## Other notebooks

- `OmniVoice.ipynb`: general OmniVoice demo plus robust long-form examples.
- `OmniVoice_Robust_LongForm_Colab.ipynb`: direct robust long-form Python workflow with ASR verification.

All maintained notebooks install from `binhminhanh1235/OmniVoice@master` rather than feature branches.

### Recommended starting point

For normal interactive use, start with one of the two `*_Gradio.ipynb` notebooks. They require no MCP, Cloudflare Tunnel, API token, or public-hostname configuration.

Use the advanced Project Studio notebook when you want ChatGPT / Claude Code / Antigravity integration through REST/MCP or a stable hostname across notebook sessions.
