from pathlib import Path

from omnivoice.runtime_workspace import (
    RuntimeWorkspace,
    detect_runtime_environment,
    detect_runtime_workspace,
    ensure_runtime_workspace,
)


def fake_exists(*existing: str):
    resolved = {str(Path(item)) for item in existing}
    return lambda path: str(Path(path)) in resolved


def test_kaggle_env_uses_files_persistable_working_workspace():
    info = detect_runtime_workspace(
        environ={"KAGGLE_KERNEL_RUN_TYPE": "Interactive"},
        path_exists=fake_exists("/kaggle/working", "/kaggle/input"),
        cwd=Path("/tmp/local"),
    )

    assert info.environment == "kaggle"
    assert info.root == Path("/kaggle/working/OmniVoiceStudio")
    assert info.input_root == Path("/kaggle/input")
    # OmniVoice cannot inspect the notebook's Session Persistence toggle, so
    # the runtime remains conservatively marked ephemeral while exposing the
    # Files-only opt-in contract explicitly.
    assert info.ephemeral is True
    assert info.persistence_backend == "kaggle-files-opt-in"
    assert any("Files only" in note for note in info.notes)
    assert any("Heavy startup/model caches" in note for note in info.notes)


def test_kaggle_path_detection_works_without_env_vars():
    environment = detect_runtime_environment(
        environ={},
        path_exists=fake_exists("/kaggle/working"),
    )
    assert environment == "kaggle"


def test_explicit_workspace_override_under_working_keeps_files_persistence_contract():
    info = detect_runtime_workspace(
        environ={
            "KAGGLE_KERNEL_RUN_TYPE": "Interactive",
            "OMNIVOICE_STUDIO_HOME": "/kaggle/working/custom-studio",
        },
        path_exists=fake_exists("/kaggle/working"),
    )
    assert info.environment == "kaggle"
    assert info.root == Path("/kaggle/working/custom-studio")
    assert info.ephemeral is True
    assert info.persistence_backend == "kaggle-files-opt-in"


def test_explicit_workspace_override_outside_working_is_not_files_persistable():
    info = detect_runtime_workspace(
        environ={
            "KAGGLE_KERNEL_RUN_TYPE": "Interactive",
            "OMNIVOICE_STUDIO_HOME": "/tmp/custom-studio",
        },
        path_exists=fake_exists("/kaggle/working"),
    )
    assert info.environment == "kaggle"
    assert info.root == Path("/tmp/custom-studio")
    assert info.persistence_backend == "none"


def test_colab_keeps_existing_mounted_drive_behavior():
    info = detect_runtime_workspace(
        environ={"COLAB_RELEASE_TAG": "release"},
        path_exists=fake_exists("/content", "/content/drive/MyDrive"),
    )
    assert info.environment == "colab"
    assert info.root == Path("/content/drive/MyDrive/OmniVoiceStudio")
    assert info.ephemeral is False
    assert info.persistence_backend == "google-drive-mounted"


def test_local_runtime_uses_cwd():
    info = detect_runtime_workspace(
        environ={},
        path_exists=fake_exists(),
        cwd=Path("/srv/omnivoice"),
    )
    assert info.environment == "local"
    assert info.root == Path("/srv/omnivoice/OmniVoiceStudio")
    assert info.ephemeral is False


def test_ensure_runtime_workspace_creates_only_local_execution_tree(tmp_path):
    info = RuntimeWorkspace(
        environment="kaggle",
        root=tmp_path / "OmniVoiceStudio",
        ephemeral=True,
        input_root=Path("/kaggle/input"),
        persistence_backend="kaggle-files-opt-in",
    )
    ensured = ensure_runtime_workspace(info)
    assert ensured is info
    assert info.root.is_dir()
    assert (info.root / "projects").is_dir()
    assert (info.root / "voices").is_dir()


def test_project_studio_cli_uses_detected_execution_workspace(monkeypatch):
    from omnivoice.cli import project_studio_voice_doctor as launcher

    detected = RuntimeWorkspace(
        environment="kaggle",
        root=Path("/kaggle/working/OmniVoiceStudio"),
        ephemeral=True,
        input_root=Path("/kaggle/input"),
        persistence_backend="kaggle-files-opt-in",
    )
    monkeypatch.setattr(launcher, "detect_runtime_workspace", lambda: detected)

    args = launcher.build_parser().parse_args([])
    assert args.workspace == "/kaggle/working/OmniVoiceStudio"
    assert args.asr_device == "cpu"
