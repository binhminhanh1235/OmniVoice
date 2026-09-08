from omnivoice.project import OmniVoiceProject
from omnivoice.project_narration import (
    create_narration_project,
    parse_narration_project_script,
)


SCRIPT = """
# Demo

## S03 — 1:45–3:10

### The person who turns correction into a weapon

[EMPHASIZE] The question is what happens next.
Do they come back and listen?
Do they reflect?
Do they own what is true?
Or do they rewrite the conversation until you become the villain for saying anything at all?
""".strip()


def test_leading_or_sentence_keeps_previous_context():
    manifest = parse_narration_project_script(SCRIPT)
    section = manifest.sections[0]
    chunks = [chunk.text for beat in section.beats for chunk in beat.chunks]

    assert not any(text.startswith("Or ") for text in chunks)
    assert any(
        "Do they own what is true? Or do they rewrite the conversation" in text
        for text in chunks
    )


def test_section_title_is_optional_and_uses_section_style():
    without_titles = parse_narration_project_script(
        SCRIPT,
        speak_section_titles=False,
    )
    with_titles = parse_narration_project_script(
        SCRIPT,
        speak_section_titles=True,
    )

    title = "The person who turns correction into a weapon"
    assert title not in without_titles.sections[0].spoken_text

    section = with_titles.sections[0]
    assert section.beats[0].directives == ["SECTION_TITLE"]
    assert section.beats[0].style == "EMPHASIZE"
    assert section.beats[0].text == f"{title}."
    assert title in section.spoken_text


def test_create_project_saves_original_script_and_adjusted_manifest(tmp_path):
    root = tmp_path / "demo"
    project = create_narration_project(
        SCRIPT,
        root,
        speak_section_titles=True,
    )

    assert (root / "script.md").read_text(encoding="utf-8") == SCRIPT
    assert "The person who turns correction into a weapon." in (
        root / "sections" / "S03" / "text.txt"
    ).read_text(encoding="utf-8")

    loaded = OmniVoiceProject.load(root)
    chunks = [
        chunk.text
        for beat in loaded.get_section("S03").beats
        for chunk in beat.chunks
    ]
    assert not any(text.startswith("Or ") for text in chunks)
