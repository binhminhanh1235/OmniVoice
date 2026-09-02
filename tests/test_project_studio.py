from pathlib import Path

import torch

from omnivoice import VoiceClonePrompt
from omnivoice.cli.audio_download_ui import enable_audio_download_buttons
from omnivoice.cli.project_studio import (
    ProjectStudioController,
    _split_section_ids,
    build_demo,
    build_parser,
)


SCRIPT = """# Demo Project

## S01 — 0:00–0:20

[WARM] First section text for the project studio test.

## S02 — 0:20–0:40

[SOFT] Second section text for the project studio test.
"""


class FakeModel:
    sampling_rate = 24000

    def create_voice_clone_prompt(self, **kwargs):
        return VoiceClonePrompt(
            ref_audio_tokens=torch.zeros((2, 4), dtype=torch.long),
            ref_text=kwargs.get("ref_text") or "auto transcript",
            ref_rms=0.1,
        )


def test_split_section_ids():
    assert _split_section_ids(None) is None
    assert _split_section_ids("") is None
    assert _split_section_ids("s01, S03; s10") == ["S01", "S03", "S10"]


def test_controller_parse_create_and_list(tmp_path: Path):
    controller = ProjectStudioController(FakeModel(), tmp_path / "studio")

    rows, message = controller.parse_script(SCRIPT)
    assert [row[0] for row in rows] == ["S01", "S02"]
    assert "2 sections" in message

    project = controller.create_project(SCRIPT)
    assert project.root.exists()
    assert controller.list_projects() == [str(project.root)]

    status_rows, chunks, sections = controller.project_view(project.root)
    assert [row[0] for row in status_rows] == ["S01", "S02"]
    assert chunks
    assert sections == []


def test_controller_voice_library_and_project_settings(tmp_path: Path):
    controller = ProjectStudioController(FakeModel(), tmp_path / "studio")
    reference = tmp_path / "ref.wav"
    reference.write_bytes(b"fake")

    message = controller.create_voice(
        name="Narrator",
        reference_audio=reference,
        ref_text="exact words",
        language="en",
    )
    assert "Narrator" in message
    assert controller.voices.voice_names() == ["Narrator"]

    project = controller.create_project(SCRIPT)
    controller.save_project_settings(
        project,
        voice_name="Narrator",
        voice_variant="DEFAULT",
        language="en",
    )
    settings = controller.load_project_settings(project)
    assert settings == {
        "voice_name": "Narrator",
        "voice_variant": "DEFAULT",
        "language": "en",
    }


def test_project_studio_parser_defaults():
    args = build_parser().parse_args([])
    assert args.model == "k2-fsa/OmniVoice"
    assert args.asr_device == "cpu"
    assert args.port == 7860


def test_audio_players_expose_download_control_across_tabs():
    import gradio as gr

    with gr.Blocks() as first:
        audio_one = gr.Audio(label="First audio", type="filepath")
    with gr.Blocks() as second:
        audio_two = gr.Audio(label="Second audio", type="filepath")
    demo = gr.TabbedInterface([first, second], ["First", "Second"])

    assert enable_audio_download_buttons(demo) == 2
    for audio in (audio_one, audio_two):
        if hasattr(audio, "buttons"):
            assert "download" in audio.buttons
        else:
            assert audio.show_download_button is True


def test_project_studio_gradio_build_smoke(tmp_path: Path):
    demo = build_demo(FakeModel(), tmp_path / "studio")
    assert demo is not None
