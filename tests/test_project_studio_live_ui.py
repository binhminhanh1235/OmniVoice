from pathlib import Path

import pytest

from omnivoice.cli.project_studio_live import (
    _decorate_status_rows,
    build_demo,
    build_live_generate_demo,
)


class FakeModel:
    sampling_rate = 24000


def test_live_status_rows_keep_every_section_visible():
    rows = [
        ["S01", "Intro", "WARM", "0:00–0:30", 1, 2, 0, 0, "pending"],
        ["S02", "Body", "DEFAULT", "0:30–1:00", 1, 3, 3, 0, "verified"],
        ["S03", "End", "SOFT", "1:00–1:30", 1, 2, 0, 1, "unverified"],
    ]

    decorated = _decorate_status_rows(
        rows,
        ["S01", "S02"],
        {
            "S01": "GENERATING… · section 1/2 · 0/2 chunks already verified",
            "S02": "SKIPPED ✓ · already verified · 3/3 chunks",
        },
    )

    assert [row[0] for row in decorated] == ["S01", "S02", "S03"]
    assert decorated[0][-1].startswith("GENERATING")
    assert decorated[1][-1].startswith("SKIPPED")
    assert decorated[2][-1] == "unverified · not selected"


def test_live_generate_panel_builds(tmp_path: Path):
    pytest.importorskip("gradio")
    demo = build_live_generate_demo(FakeModel(), tmp_path / "studio")
    assert demo is not None


def test_live_combined_project_studio_builds(tmp_path: Path):
    pytest.importorskip("gradio")
    demo = build_demo(FakeModel(), tmp_path / "studio")
    assert demo is not None
