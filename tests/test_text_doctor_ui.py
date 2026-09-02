from pathlib import Path

import pytest

from omnivoice.cli.project_studio_text import build_demo
from omnivoice.cli.text_doctor_ui import build_text_doctor_demo


class FakeModel:
    sampling_rate = 24000


def test_text_doctor_panel_builds():
    pytest.importorskip("gradio")
    demo = build_text_doctor_demo()
    assert demo is not None


def test_text_doctor_project_studio_wrapper_builds(tmp_path: Path):
    pytest.importorskip("gradio")
    demo = build_demo(FakeModel(), tmp_path / "studio")
    assert demo is not None
