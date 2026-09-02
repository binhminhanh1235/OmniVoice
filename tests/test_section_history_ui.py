from omnivoice.cli.project_studio_resume import SectionResumeProjectStudioController
from omnivoice.cli.section_history_ui import build_section_history_demo


class FakeModel:
    sampling_rate = 8000


def test_section_history_demo_builds(tmp_path):
    demo = build_section_history_demo(
        FakeModel(),
        tmp_path / "workspace",
        controller_cls=SectionResumeProjectStudioController,
    )
    assert demo is not None
