import json
from pathlib import Path

from omnivoice.hardware_quality import HardwareCapabilities
from omnivoice.services import studio_service as service_module
from omnivoice.services.studio_service import StudioService


def write_project(root: Path, title: str, statuses: dict[str, tuple[str, bool]]):
    root.mkdir(parents=True, exist_ok=True)
    sections = []
    sidecar_sections = {}
    for section_id, (status, complete) in statuses.items():
        sections.append(
            {
                "id": section_id,
                "status": status,
                "audio_file": f"sections/{section_id}/{section_id}.wav" if complete else None,
            }
        )
        sidecar_sections[section_id] = {
            "status": status,
            "complete": complete,
        }
    (root / "project.json").write_text(
        json.dumps({"title": title, "sections": sections}),
        encoding="utf-8",
    )
    (root / "section-status.json").write_text(
        json.dumps({"sections": sidecar_sections}),
        encoding="utf-8",
    )


def test_service_lists_and_filters_projects(tmp_path):
    workspace = tmp_path / "studio"
    write_project(
        workspace / "projects" / "pending-project",
        "Pending Project",
        {"S01": ("pending", False), "S02": ("verified", True)},
    )
    write_project(
        workspace / "projects" / "done-project",
        "Done Project",
        {"S01": ("verified", True)},
    )

    service = StudioService(None, workspace)
    all_projects = service.list_projects()
    assert {item["id"] for item in all_projects} == {"pending-project", "done-project"}

    pending = service.list_projects(["PENDING"])
    assert [item["id"] for item in pending] == ["pending-project"]
    assert pending[0]["progress"] == "1/2"


def test_service_rejects_unknown_status_and_path_traversal(tmp_path):
    service = StudioService(None, tmp_path / "studio")

    try:
        service.list_projects(["NOPE"])
        raise AssertionError("Expected invalid status to fail")
    except ValueError:
        pass

    try:
        service.get_project("../secret")
        raise AssertionError("Expected invalid project id to fail")
    except ValueError:
        pass


def test_capabilities_and_health_expose_stable_ai_native_contract(tmp_path):
    service = StudioService(None, tmp_path / "studio")
    health = service.health()
    capabilities = service.capabilities()

    assert health["service"] == "omnivoice-studio"
    assert health["model_loaded"] is False
    assert capabilities["features"]["web_ui"] is True
    assert capabilities["features"]["rest_api"] is True
    assert capabilities["features"]["mcp"] is False
    assert capabilities["endpoints"]["ui"] == "/ui"
    assert capabilities["endpoints"]["api"] == "/api/v1"


def test_hardware_payload_is_json_friendly(tmp_path, monkeypatch):
    monkeypatch.setattr(
        service_module,
        "detect_hardware",
        lambda: HardwareCapabilities(
            cuda_available=True,
            device_count=1,
            device_index=0,
            device_name="Tesla T4",
            total_vram_gb=16.0,
            compute_capability=(7, 5),
            recommended_asr_device="cpu",
            recommended_preset="BALANCED",
        ),
    )
    service = StudioService(None, tmp_path / "studio")
    payload = service.hardware()
    assert payload["device_name"] == "Tesla T4"
    assert payload["compute_capability_text"] == "7.5"
    assert "recommended preset=BALANCED" in payload["summary"]
