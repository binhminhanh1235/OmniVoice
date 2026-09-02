#!/usr/bin/env python3

from omnivoice.text_doctor import inspect_script


def test_text_doctor_cleans_safe_artifacts_without_touching_metadata():
    script = """# Title

## S01 — 0:00–0:45

[WARM] Patterns that reject truth. &#x20;\\
Patterns that avoid responsibility.\u200b
"""
    result = inspect_script(script)

    assert "## S01 — 0:00–0:45" in result.cleaned
    assert "[WARM] Patterns that reject truth." in result.cleaned
    assert "&#x20;" not in result.cleaned
    assert "\\" not in result.cleaned.splitlines()[4]
    assert "\u200b" not in result.cleaned
    assert result.safe_change_count >= 3
    assert result.diff


def test_text_doctor_keeps_directive_for_parser_but_never_invents_instruct():
    script = """## S01 — 0:00–0:30

[WARM] This should stay warm.
[MYSTERY] This tag needs review.
"""
    result = inspect_script(script)

    assert "[WARM]" in result.cleaned
    assert "[MYSTERY]" in result.cleaned
    unknown = [item for item in result.changes if item.kind == "unknown_directive"]
    assert len(unknown) == 1
    assert unknown[0].severity == "review"


def test_text_doctor_flags_numbers_without_rewriting_them():
    script = """## S04 — 3:10–4:40

Paul addresses it in 2 Thessalonians 3.
"""
    result = inspect_script(script)

    assert "2 Thessalonians 3" in result.cleaned
    number_changes = [item for item in result.changes if item.kind == "number"]
    assert len(number_changes) == 1
    assert number_changes[0].severity == "review"
    assert "2" in number_changes[0].note
    assert "3" in number_changes[0].note


def test_text_doctor_does_not_flag_section_timestamps_as_narration_numbers():
    result = inspect_script("## S10 — 11:30–12:45\n\n[SOFT] Father, give us wisdom.")
    number_changes = [item for item in result.changes if item.kind == "number"]
    assert number_changes == []


def test_text_doctor_flags_acronym_pronunciation_for_review():
    result = inspect_script("## S01 — 0:00–0:30\n\nThe NASA example is only a test.")
    abbreviation_changes = [
        item for item in result.changes if item.kind == "abbreviation"
    ]
    assert len(abbreviation_changes) == 1
    assert "NASA" in abbreviation_changes[0].note
