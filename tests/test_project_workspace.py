from types import SimpleNamespace

from omnivoice.cli.project_workspace import (
    _chunk_target,
    _labels_for_ids,
    _project_summary,
    _section_ids,
    _section_labels,
)


def _project():
    chunk_ok = SimpleNamespace(status="verified")
    chunk_bad = SimpleNamespace(status="unverified")
    beat = SimpleNamespace(chunks=[chunk_ok, chunk_bad])
    section = SimpleNamespace(
        id="S03",
        title="The person who turns correction into a weapon",
        status="unverified",
        beats=[beat],
    )
    manifest = SimpleNamespace(title="Demo", sections=[section])
    return SimpleNamespace(manifest=manifest)


def test_section_labels_are_human_readable_and_keep_id_prefix():
    labels = _section_labels(_project())
    assert labels == [
        "S03 · The person who turns correction into a weapon · 1/2 verified · UNVERIFIED"
    ]
    assert _section_ids(labels) == ["S03"]


def test_section_ids_deduplicate_and_empty_is_none():
    values = ["S03 · First", "S03 · Duplicate", "S04 · Second"]
    assert _section_ids(values) == ["S03", "S04"]
    assert _section_ids([]) is None


def test_refreshed_section_labels_keep_selected_ids_after_status_changes():
    labels = [
        "S01 · Opening · 3/3 verified · VERIFIED",
        "S03 · Correction · 8/9 verified · UNVERIFIED",
    ]
    assert _labels_for_ids(labels, ["S03"]) == [labels[1]]


def test_chunk_target_ignores_human_readable_suffix():
    assert _chunk_target("S03/B01-C07 · UNVERIFIED · Or do they rewrite...") == (
        "S03",
        "B01-C07",
    )


def test_project_summary_surfaces_saved_narration_setting():
    summary = _project_summary(
        _project(),
        {
            "voice_name": "Warm narrator",
            "voice_variant": "AUTO",
            "quality_preset": "BALANCED",
            "speak_section_titles": True,
        },
    )
    assert "1/2 chunks verified" in summary
    assert "Warm narrator/AUTO" in summary
    assert "Read titles **on**" in summary


def test_primary_launcher_imports_after_navigation_consolidation():
    from omnivoice.cli import project_studio_voice_doctor as launcher

    assert callable(launcher.build_demo)
