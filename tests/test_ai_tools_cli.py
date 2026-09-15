import json

from omnivoice.cli import ai_tools


def test_umbrella_cli_exposes_nine_priority_commands():
    parser = ai_tools.build_parser()
    subparsers = next(
        action for action in parser._actions if action.__class__.__name__ == "_SubParsersAction"
    )
    assert {
        "generate-audio",
        "generate-project",
        "get-job",
        "wait-job",
        "list-artifacts",
        "preview-audio",
        "regenerate-section",
        "regenerate-chunk",
        "cancel-job",
    }.issubset(set(subparsers.choices))


def test_cli_generate_audio_calls_async_rest_surface(monkeypatch, capsys):
    calls = []

    def fake_request(self, method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"job_id": "job_demo", "status": "queued"}

    monkeypatch.setattr(ai_tools.StudioClient, "request", fake_request)
    code = ai_tools.main(
        [
            "--url",
            "http://studio.test",
            "generate-audio",
            "Hello",
            "--voice",
            "Narrator",
            "--quality",
            "FAST",
            "--idempotency-key",
            "turn-1",
        ]
    )

    assert code == 0
    method, path, kwargs = calls[0]
    assert method == "POST"
    assert path == "/api/v1/audio/generate"
    assert kwargs["body"]["text"] == "Hello"
    assert kwargs["body"]["voice_name"] == "Narrator"
    assert kwargs["idempotency_key"] == "turn-1"
    assert json.loads(capsys.readouterr().out)["job_id"] == "job_demo"
