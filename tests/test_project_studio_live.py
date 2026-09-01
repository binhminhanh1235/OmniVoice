from pathlib import Path

import pytest

from omnivoice.cli.project_studio_live import (
    _decorate_status_rows,
    _split_sections,
    build_live_generate_demo,
)


class FakeModel:
    sampling_rate = 24000


def test_live_generate_panel_builds(tmp_path: Path):
    pytest.importorskip("gradio")
    demo = build_live_generate_demo(FakeModel(), tmp_path / "studio")
    assert demo is not None


def test_live_status_decorates_each_section_without_dropping_rows():
    rows = [
        ["S01", "Opening", "WARM", "0:00–0:45", 1, 3, 0, 0, "pending"],
        ["S02", "Context", "WARM", "0:45–1:45", 1, 4, 4, 0, "verified"],
        ["S03", "Warning", "EMPHASIZE", "1:45–3:10", 2, 7, 2, 0, "pending"],
    ]

    decorated = _decorate_status_rows(
        rows,
        ["S01", "S02"],
        {"S01": "GENERATING… · section 1/2"},
    )

    assert len(decorated) == 3
    assert decorated[0][0] == "S01"
    assert "GENERATING" in decorated[0][-1]
    assert decorated[1][-1] == "VERIFIED ✓"
    assert "not selected" in decorated[2][-1]


def test_section_filter_parser_accepts_comma_and_semicolon():
    assert _split_sections("S03,S07; S10") == ["S03", "S07", "S10"]
    assert _split_sections("  ") is None
