from pathlib import Path

import pytest

from omnivoice.cli.project_studio_plus import build_demo, build_preview_demo


class FakeModel:
    sampling_rate = 24000


def test_preview_panel_builds(tmp_path: Path):
    pytest.importorskip("gradio")
    demo = build_preview_demo(FakeModel(), tmp_path / "studio")
    assert demo is not None


def test_combined_project_studio_builds(tmp_path: Path):
    pytest.importorskip("gradio")
    demo = build_demo(FakeModel(), tmp_path / "studio")
    assert demo is not None
