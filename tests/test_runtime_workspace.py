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


def test_kaggle_env_uses_local_working_ssd():
    info = detect_runtime_workspace(
        environ={"KAGGLE_KERNEL_RUN_TYPE": "Interactive"},
        path_exists=fake_exists("/kaggle/working", "/kaggle/input"),
        cwd=Path("/tmp/local"),
    )

    assert info.environment == "kaggle"
    assert info.root == Path("/kaggle/working/OmniVoiceStudio")
    assert info.input_root == Path("/kaggle/input")
    assert info.ephemeral is True
    assert info.persistence_backend == "none"


def test_kaggle_path_detection_works_without_env_vars():
    environment = detect_runtime_environment(
        environ={},
        path_exists=fake_exists("/kaggle/working"),
    )
    assert environment == "kaggle"


def test_explicit_workspace_override_wins_on_kaggle():
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
        persistence_backend="none",
    )
    ensured = ensure_runtime_workspace(info)
    assert ensured is info
    assert info.root.is_dir()
    assert (info.root / "projects").is_dir()
    assert (info.root / "voices").is_dir()
