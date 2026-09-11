import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_notebook(name: str) -> dict:
    path = ROOT / "notebooks" / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["nbformat"] == 4
    assert isinstance(payload.get("cells"), list)
    return payload


def _cell_source(cell: dict) -> str:
    source = cell.get("source", [])
    if isinstance(source, list):
        return "".join(source)
    return str(source)


def _find_acceptance_cell(notebook: dict) -> str:
    matches = [
        _cell_source(cell)
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
        and "ACCEPTANCE_SAMPLE" in _cell_source(cell)
    ]
    assert len(matches) == 1, "expected exactly one production acceptance code cell"
    return matches[0]


@pytest.mark.parametrize(
    "name",
    [
        "OmniVoice_Project_Studio_Colab.ipynb",
        "OmniVoice_Project_Studio_Kaggle.ipynb",
    ],
)
def test_production_acceptance_cell_is_python_and_exact_revision_bound(name):
    notebook = _load_notebook(name)
    source = _find_acceptance_cell(notebook)

    compile(source, f"{name}:production-acceptance", "exec")

    assert "PACKAGE_REF" in source
    assert "startup-cache-evidence" not in source or "STARTUP_CACHE_EVIDENCE" in source
    assert "STARTUP_CACHE_EVIDENCE" in source
    assert "should_defer_asr_startup" in source
    assert "hosted_cache_acceptance.py" in source
    assert '"cold"' in source
    assert '"warm"' in source
    assert "cold_path" in source
    assert "warm_path" in source
    assert "subprocess.run" in source
    assert "check=True" in source


def test_colab_acceptance_keeps_cpu_asr_lazy_and_drive_evidence_persistent():
    notebook = _load_notebook("OmniVoice_Project_Studio_Colab.ipynb")
    acceptance = _find_acceptance_cell(notebook)
    all_source = "\n".join(_cell_source(cell) for cell in notebook["cells"])

    assert 'ASR_DEVICE = "cpu"' in acceptance
    assert "lazy CPU" in acceptance
    assert 'evidence_archive / "acceptance" / PACKAGE_REF' in acceptance
    assert "/content/hosted_cache_acceptance.py" in acceptance
    assert "--asr-device cpu" in all_source
    assert "/content/OmniVoiceStudio" in all_source


def test_kaggle_acceptance_carries_cold_evidence_across_dataset_boundary():
    notebook = _load_notebook("OmniVoice_Project_Studio_Kaggle.ipynb")
    acceptance = _find_acceptance_cell(notebook)
    all_source = "\n".join(_cell_source(cell) for cell in notebook["cells"])

    assert "CACHE_SOURCE_BASE" in acceptance
    assert "CACHE_EXPORT_BASE" in acceptance
    assert "source_acceptance" in acceptance
    assert "shutil.copytree" in acceptance
    assert "/kaggle/working/hosted_cache_acceptance.py" in acceptance
    assert "--asr-device {ASR_DEVICE}" in all_source
    assert "/kaggle/working/OmniVoiceStudio" in all_source
    assert "/kaggle/input/omnivoice-startup-cache" in all_source
