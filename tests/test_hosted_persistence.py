from pathlib import Path

from omnivoice.hosted_persistence import (
    HostedWorkspacePersistence,
    configure_kaggle_drive_connection,
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

    # The local execution workspace is authoritative after restore. Deletions
    # must propagate so an intentionally deleted project is not resurrected on
    # the next hosted session.
    (local / "projects" / "video-a" / "project.json").unlink()
    (local / "projects" / "video-a" / "studio.json").unlink()
    (local / "projects" / "video-a").rmdir()
    (local / "voices" / "david" / "voice.json").write_text("voice-new", encoding="utf-8")
    session.sync_now()

    assert not (persistent / "projects" / "video-a").exists()
    assert (persistent / "voices" / "david" / "voice.json").read_text(encoding="utf-8") == "voice-new"
    assert excluded.read_text(encoding="utf-8") == "cache"


def test_rclone_restore_precedes_local_to_remote_sync_and_excludes_cache(tmp_path, monkeypatch):
    workspace = tmp_path / "studio"
    calls = []

    def fake_run(workspace_arg, args, **kwargs):
        calls.append((Path(workspace_arg), list(args)))

    monkeypatch.setattr("omnivoice.hosted_persistence._run_rclone", fake_run)
    session = HostedWorkspacePersistence(
        runtime=_runtime("kaggle", workspace),
        workspace=workspace,
        backend="google-drive-rclone",
        destination="Backups/Studio",
        interval_seconds=3600,
    )

    session.restore()
    session.sync_now()

    assert calls[0][1] == ["mkdir", "omnivoice_drive:Backups/Studio"]
    restore = calls[1][1]
    assert restore[0] == "copy"
    assert restore[1] == "omnivoice_drive:Backups/Studio"
    assert restore[2] == str(workspace)
    backup = calls[2][1]
    assert backup[0] == "sync"
    assert backup[1] == str(workspace)
    assert backup[2] == "omnivoice_drive:Backups/Studio"
    joined = " ".join(backup)
    assert ".startup-cache/**" in joined
    assert "startup-cache-evidence.json" in joined


def test_kaggle_drive_connection_can_be_loaded_from_one_time_secrets(tmp_path, monkeypatch):
    workspace = tmp_path / "studio"
    captured = {}

    monkeypatch.setattr("omnivoice.hosted_persistence.drive_connected", lambda workspace_arg: False)

    def fake_save(workspace_arg, **kwargs):
        captured.update(kwargs)
        return tmp_path / "runtime-secret.json"

    monkeypatch.setattr("omnivoice.hosted_persistence.save_drive_connection", fake_save)
    connected, message = configure_kaggle_drive_connection(
        workspace,
        environ={
            "OMNIVOICE_GDRIVE_CLIENT_ID": "client-id",
            "OMNIVOICE_GDRIVE_CLIENT_SECRET": "client-secret",
            "OMNIVOICE_GDRIVE_TOKEN_JSON": '{"refresh_token":"refresh"}',
        },
    )

    assert connected is True
    assert "Kaggle Secrets" in message
    assert captured == {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "token_json": '{"refresh_token":"refresh"}',
    }


def test_kaggle_without_persistent_credentials_fails_open_with_actionable_warning(tmp_path, monkeypatch):
    workspace = tmp_path / "studio"
    monkeypatch.setattr("omnivoice.hosted_persistence.drive_connected", lambda workspace_arg: False)
    monkeypatch.setattr("omnivoice.hosted_persistence._read_kaggle_secret", lambda name: None)

    session = prepare_hosted_workspace_persistence(
        _runtime("kaggle", workspace),
        workspace,
        environ={},
    )

    assert session.available is False
    assert session.backend == "none"
    assert "ephemeral" in session.message
    assert "OMNIVOICE_GDRIVE_TOKEN_JSON" in session.message
