from omnivoice.cli.voice_doctor_ui import build_voice_doctor_demo


def test_voice_doctor_demo_builds():
    demo = build_voice_doctor_demo()
    assert demo is not None
