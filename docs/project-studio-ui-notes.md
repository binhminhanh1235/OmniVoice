# Project Studio UI notes

The Gradio UI is a convenience layer over the persistent Project and Voice Library APIs.

## Main flow

1. Save a reference once in **Voice Library**.
2. Paste the full Markdown narration script.
3. **Parse Script** to inspect Sxx sections/styles/chunk counts.
4. **Create Project** to persist the script and manifest.
5. Choose a saved voice and **Generate / Resume**.
6. Inspect section/chunk status.
7. Regenerate only a bad chunk when needed.
8. Play individual section WAVs.
9. Merge verified sections to `full.wav`.

The workspace defaults to Google Drive when `/content/drive/MyDrive` is already mounted; otherwise it uses `/content/OmniVoiceStudio` on Colab.

Generic tags such as `[WARM]`, `[SOFT]`, and `[EMPHASIZE]` remain metadata and are never spoken or passed as unsupported raw OmniVoice `instruct` values.
