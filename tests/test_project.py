import json

import numpy as np

from omnivoice.project import (
    OmniVoiceProject,
    OmniVoiceStyleResolver,
    StyleProfile,
    parse_project_script,
)
from omnivoice.robust_longform import RobustLongFormConfig


SCRIPT = r"""
# 5 People You Should Stop Enabling — What the Bible Actually Says

## S01 — 0:00–0:45

[WARM] Not every time you step in, you are actually helping.

You answer another late-night call.\
You send another payment.

## S02 — 0:45–1:45

[WARM] Let’s be clear from the beginning.

This is not about refusing kindness.

## S03 — 1:45–3:10

### The person who turns correction into a weapon

[EMPHASIZE] The first warning sign is not a bad reaction.

Proverbs 9 contrasts two responses to rebuke.

[NORMAL] You can say, “I care about you.”

## S04 — 3:10–4:40

### The person who refuses responsibility

But there is another pattern that often looks like compassion at first.

## S05 — 4:40–6:05

### The person who keeps turning people against each other

Titus 3 gives a careful process for a divisive person.

## S06 — 6:05–7:30

### The teacher asking you to support what is false

Second John speaks about travelling teachers.

## S07 — 7:30–9:05

### The person who uses holiness to avoid accountability

[SOFT] This one can be deeply painful.

The warning is not against imperfect people.

## S08 — 9:05–10:15

### Four questions before you step in

Before you offer help, pause long enough to ask four questions.

## S09 — 10:15–11:30

### What a godly boundary can sound like

A boundary does not need to be dramatic to be real.

## S10 — 11:30–12:45

### Prayer for wise love

[SOFT] Father, give us hearts that are both tender and wise.

In Jesus’ name, amen.

## S11 — 12:45–13:25

### Closure

[WARM] You do not have to become hard to become wise.

A healthy boundary is not the end of love.
""".strip()


def test_parse_script_into_sections_beats_and_chunks():
    manifest = parse_project_script(
        SCRIPT,
        max_chunk_words=12,
        max_chunk_chars=120,
    )

    assert manifest.title.startswith("5 People You Should Stop Enabling")
    assert len(manifest.sections) == 11
    assert [section.id for section in manifest.sections] == [
        f"S{i:02d}" for i in range(1, 12)
    ]

    s01 = manifest.sections[0]
    assert s01.start_seconds == 0
    assert s01.end_seconds == 45
    assert s01.default_style == "WARM"
    assert s01.beats[0].style == "WARM"

    s03 = manifest.sections[2]
    assert s03.title == "The person who turns correction into a weapon"
    assert s03.default_style == "EMPHASIZE"
    assert [beat.style for beat in s03.beats] == ["EMPHASIZE", "DEFAULT"]
    assert len(s03.beats[0].chunks) >= 1

    assert manifest.sections[6].default_style == "SOFT"
    assert manifest.sections[9].default_style == "SOFT"
    assert manifest.sections[10].default_style == "WARM"


def test_directives_headings_and_markdown_linebreaks_are_not_spoken():
    manifest = parse_project_script(SCRIPT)
    all_spoken = "\n".join(
        section.spoken_text for section in manifest.sections
    )

    assert "[WARM]" not in all_spoken
    assert "[SOFT]" not in all_spoken
    assert "[EMPHASIZE]" not in all_spoken
    assert "[NORMAL]" not in all_spoken
    assert "### The person" not in all_spoken
    assert "\\\n" not in all_spoken
    assert "You answer another late-night call." in all_spoken
    assert "You send another payment." in all_spoken


def test_generic_emotion_styles_do_not_become_native_instruct():
    resolver = OmniVoiceStyleResolver()

    assert resolver.resolve("WARM").native_instruct is None
    assert resolver.resolve("SOFT").native_instruct is None
    assert resolver.resolve("EMPHASIZE").native_instruct is None

    assert resolver.resolve("WHISPER").native_instruct == "whisper"
    assert resolver.resolve("LOW_PITCH").native_instruct == "low pitch"


def test_custom_style_profile_can_override_delivery_without_changing_parser():
    custom = StyleProfile(
        name="WARM",
        speed=0.9,
        pause_multiplier=1.25,
    )
    resolver = OmniVoiceStyleResolver({"WARM": custom})
    assert resolver.resolve("WARM") == custom


def test_project_create_and_load_roundtrip(tmp_path):
    root = tmp_path / "project"
    project = OmniVoiceProject.create(
        SCRIPT,
        root,
        max_chunk_words=12,
        max_chunk_chars=120,
    )

    assert (root / "project.json").exists()
    assert (root / "script.md").exists()
    assert (root / "sections" / "S01" / "text.txt").exists()
    assert (root / "sections" / "S01" / "metadata.json").exists()

    loaded = OmniVoiceProject.load(root)
    assert loaded.manifest.title == project.manifest.title
    assert len(loaded.manifest.sections) == 11
    assert loaded.get_section("S10").default_style == "SOFT"


class FakeModel:
    sampling_rate = 8000

    def __init__(self):
        self.calls = []

    def generate(self, text, generation_config=None, **kwargs):
        self.calls.append(
            {
                "text": text,
                "generation_config": generation_config,
                "kwargs": dict(kwargs),
            }
        )
        samples = max(800, len(text) * 20)
        return [np.full(samples, 0.01, dtype=np.float32)]


SHORT_SCRIPT = r"""
# Demo Project

## S01 — 0:00–0:20

[WARM] This is the first sentence. This is the second sentence with more words.

## S02 — 0:20–0:40

[SOFT] This is a softer section. It also has another sentence.
""".strip()


def test_generation_checkpoints_each_chunk_and_resume_skips_verified(tmp_path):
    project = OmniVoiceProject.create(
        SHORT_SCRIPT,
        tmp_path / "demo",
        max_chunk_words=7,
        max_chunk_chars=80,
    )
    model = FakeModel()
    robust = RobustLongFormConfig(
        verify_with_asr=False,
        max_chunk_words=7,
        max_chunk_chars=80,
    )

    project.generate(model, robust_config=robust)
    first_call_count = len(model.calls)
    expected_chunks = sum(
        len(beat.chunks)
        for section in project.manifest.sections
        for beat in section.beats
    )
    assert first_call_count == expected_chunks
    assert project.manifest.all_verified

    for section in project.manifest.sections:
        assert (project.root / section.audio_file).exists()
        for beat in section.beats:
            assert (project.root / beat.audio_file).exists()
            for chunk in beat.chunks:
                assert chunk.status == "verified"
                assert (project.root / chunk.audio_file).exists()
                report = json.loads(
                    (project.root / chunk.report_file).read_text(encoding="utf-8")
                )
                assert report["source_text"] == chunk.text

    project.generate(model, robust_config=robust, resume=True)
    assert len(model.calls) == first_call_count


def test_mark_one_chunk_and_regenerate_only_that_chunk(tmp_path):
    project = OmniVoiceProject.create(
        SHORT_SCRIPT,
        tmp_path / "demo",
        max_chunk_words=7,
        max_chunk_chars=80,
    )
    model = FakeModel()
    robust = RobustLongFormConfig(
        verify_with_asr=False,
        max_chunk_words=7,
        max_chunk_chars=80,
    )
    project.generate(model, robust_config=robust)
    before = len(model.calls)

    target = project.manifest.sections[0].beats[0].chunks[0]
    project.mark_chunk_for_regeneration("S01", target.id)
    project.generate(
        model,
        robust_config=robust,
        section_ids=["S01"],
        resume=True,
    )

    assert len(model.calls) == before + 1
    assert project.get_chunk("S01", target.id).status == "verified"


def test_warm_style_changes_speed_but_is_not_sent_as_instruct(tmp_path):
    project = OmniVoiceProject.create(
        SHORT_SCRIPT,
        tmp_path / "demo",
        max_chunk_words=30,
        max_chunk_chars=200,
    )
    model = FakeModel()
    robust = RobustLongFormConfig(
        verify_with_asr=False,
        max_chunk_words=30,
        max_chunk_chars=200,
    )

    project.generate(
        model,
        robust_config=robust,
        section_ids=["S01"],
    )

    assert model.calls
    first_kwargs = model.calls[0]["kwargs"]
    assert first_kwargs["speed"] == 0.97
    assert "instruct" not in first_kwargs


def test_merge_writes_full_audio_and_timeline(tmp_path):
    project = OmniVoiceProject.create(
        SHORT_SCRIPT,
        tmp_path / "demo",
        max_chunk_words=30,
        max_chunk_chars=200,
    )
    model = FakeModel()
    robust = RobustLongFormConfig(
        verify_with_asr=False,
        max_chunk_words=30,
        max_chunk_chars=200,
    )
    project.generate(model, robust_config=robust)

    output = project.merge(section_pause_ms=100)
    assert output.exists()

    timeline_path = project.root / "output" / "timeline.json"
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    assert [entry["section"] for entry in timeline] == ["S01", "S02"]
    assert timeline[0]["planned_start"] == "0:00"
    assert timeline[1]["planned_end"] == "0:40"
