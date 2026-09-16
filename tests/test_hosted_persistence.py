import json
from pathlib import Path

from omnivoice.hosted_persistence import (
    HostedWorkspacePersistence,
    prepare_hosted_workspace_persistence,
)
from omnivoice.runtime_workspace import RuntimeWorkspace


def _runtime(environment: str, root: Path, *, ephemeral: bool = True) -> RuntimeWorkspace:
    return RuntimeWorkspace(
        environment=environment,
        root=root,
        ephemeral=ephemeral,
    )


def test_colab_full_workspace_restore_and_sync_covers_voice_project_and_runtime_state(tmp_path):
    local = tmp_path / "local"
    persistent = tmp_path / "drive" / "OmniVoiceStudio"

    durable_files = {
        "voices/david/voice.json": "voice",
        "voices/david/prompts/default.pt": "prompt",
        "projects/video-a/project.json": "project",
        "projects/video-a/studio.json": "project-settings",
        "project-queue.json": "queue",
        "jobs.json": "jobs",
        "hardware-quality.json": "quality",
        "advanced-settings.json": "advanced",
        "artifacts/audio/quick.wav": "audio",
    }
    for relative, content in durable_files.items():
        path = persistent / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    excluded = persistent / ".startup-cache" / "cache.bin"
    excluded.parent.mkdir(parents=True, exist_ok=True)
    excluded.write_text("cache", encoding="utf-8")
    (persistent / "startup-cache-evidence.json").write_text("{}", encoding="utf-8")

    session = HostedWorkspacePersistence(
        runtime=_runtime("colab", local),
        workspace=local,
        backend="colab-drive",
        persistent_root=persistent,
        interval_seconds=3600,
    )
    session.restore()

    for relative, content in durable_files.items():
        assert (local / relative).read_text(encoding="utf-8") == content
    assert not (local / ".startup-cache").exists()
    assert not (local / "startup-cache-evidence.json").exists()

    (local / "projects" / "video-a" / "project.json").unlink()
    (local / "projects" / "video-a" / "studio.json").unlink()
    (local / "projects" / "video-a").rmdir()
    (local / "voices" / "david" / "voice.json").write_text("voice-new", encoding="utf-8")
    session.sync_now()

    assert not (persistent / "projects" / "video-a").exists()
    assert (persistent / "voices" / "david" / "voice.json").read_text(encoding="utf-8") == "voice-new"
    assert excluded.read_text(encoding="utf-8") == "cache"


def test_restore_rebases_queue_and_job_paths_between_hosted_roots(tmp_path):
    local = tmp_path / "restored" / "OmniVoiceStudio"
    persistent = tmp_path / "drive" / "OmniVoiceStudio"
    persistent.mkdir(parents=True)

    (persistent / "project-queue.json").write_text(
        json.dumps(
            {
                "version": 1,
                "items": [
                    {
                        "id": "queue-one",
                        "project_path": "/content/OmniVoiceStudio/projects/video-a",
                        "project_title": "Video A",
                        "voice_name": "David",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (persistent / "jobs.json").write_text(
        json.dumps(
            {
                "version": 1,
                "jobs": [
                    {
                        "id": "job-one",
                        "kind": "generate_project",
                        "payload": {
                            "project_path": "/content/OmniVoiceStudio/projects/video-a",
                        },
                        "result": {
                            "audio": "/content/OmniVoiceStudio/projects/video-a/output/final.wav",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    session = HostedWorkspacePersistence(
        runtime=_runtime("colab", local),
        workspace=local,
        backend="colab-drive",
        persistent_root=persistent,
        interval_seconds=3600,
    )
    session.restore()

    queue = json.loads((local / "project-queue.json").read_text(encoding="utf-8"))
    jobs = json.loads((local / "jobs.json").read_text(encoding="utf-8"))
    project_path = str((local / "projects" / "video-a").resolve())
    output_path = str((local / "projects" / "video-a" / "output" / "final.wav").resolve())

    assert queue["items"][0]["project_path"] == project_path
    assert jobs["jobs"][0]["payload"]["project_path"] == project_path
    assert jobs["jobs"][0]["result"]["audio"] == output_path
    assert "Rebased 3 restored queue/job path value(s)" in session.message


def test_kaggle_uses_files_only_workspace_without_external_mirror(tmp_path, monkeypatch):
    workspace = tmp_path / "studio"
    monkeypatch.setattr(
        "omnivoice.hosted_persistence._under_kaggle_working",
        lambda path: True,
    )

    session = prepare_hosted_workspace_persistence(
        _runtime("kaggle", workspace),
        workspace,
        environ={},
    )

    assert session.backend == "kaggle-files"
    assert session.available is False
    assert session._thread is None
    assert workspace.is_dir()
    assert "Files only" in session.message
    assert "/tmp" in session.message
    assert "Automatic Google Drive mirroring is disabled" in session.message
    assert "OMNIVOICE_GDRIVE" not in session.message
    session.close()


def test_kaggle_custom_workspace_outside_working_warns_about_files_only_boundary(tmp_path):
    workspace = tmp_path / "outside-working"

    session = prepare_hosted_workspace_persistence(
        _runtime("kaggle", workspace),
        workspace,
        environ={},
    )

    assert session.backend == "kaggle-files"
    assert session.available is False
    assert "outside /kaggle/working" in session.message
    assert "OMNIVOICE_STUDIO_HOME" in session.message
    session.close()
