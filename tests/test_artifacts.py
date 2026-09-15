import json

import numpy as np
import soundfile as sf

from omnivoice.artifacts import ArtifactCatalog


def _wav(path, seconds=0.1, sample_rate=24000):
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.zeros(int(seconds * sample_rate), dtype=np.float32), sample_rate)


def test_artifact_catalog_discovers_current_standalone_and_project_audio(tmp_path):
    workspace = tmp_path / "studio"
    project = workspace / "projects" / "video-a"
    project.mkdir(parents=True)
    (project / "project.json").write_text(json.dumps({"title": "Video A"}), encoding="utf-8")

    _wav(workspace / "artifacts" / "audio" / "job_1.wav")
    _wav(workspace / "artifacts" / "previews" / "job_2.wav")
    _wav(project / "sections" / "S01" / "chunks" / "B01-C01.wav")
    _wav(project / "sections" / "S01" / "beats" / "B01.wav")
    _wav(project / "sections" / "S01" / "S01.wav")
    _wav(project / "output" / "full.wav")
    _wav(project / "sections" / "S01" / "history" / "v0001" / "chunks" / "B01-C01.wav")
    _wav(project / "sections" / "S01" / "history" / "v0001" / "S01.wav")

    catalog = ArtifactCatalog(workspace)
    items = catalog.list()
    kinds = {item["kind"] for item in items}

    assert {
        "generated_audio",
        "preview_audio",
        "chunk_audio",
        "beat_audio",
        "section_audio",
        "project_audio",
    }.issubset(kinds)
    assert all(item["id"].startswith("art_") for item in items)
    assert all(item["sample_rate"] == 24000 for item in items)
    assert all(item["size_bytes"] > 0 for item in items)
    assert all("/history/" not in item["relative_path"] for item in items)

    project_items = catalog.list(project_id="video-a")
    assert project_items
    assert {item["project_id"] for item in project_items} == {"video-a"}
    chunks = catalog.list(project_id="video-a", kinds=["chunk_audio"])
    assert len(chunks) == 1
    assert chunks[0]["section_id"] == "S01"
    assert chunks[0]["chunk_id"] == "B01-C01"


def test_artifact_catalog_rejects_project_traversal(tmp_path):
    catalog = ArtifactCatalog(tmp_path / "studio")
    try:
        catalog.list(project_id="../secret")
    except ValueError as exc:
        assert "Invalid project id" in str(exc)
    else:
        raise AssertionError("Traversal project id must be rejected")
