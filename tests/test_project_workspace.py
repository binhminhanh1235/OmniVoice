import inspect
from types import SimpleNamespace

from omnivoice.cli.project_studio import _LANGUAGE_CHOICES
from omnivoice.cli.project_workspace import (
    _chunk_target,
    _labels_for_ids,
    _project_summary,
    _section_ids,
    _section_labels,
    build_project_workspace_demo,
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


def test_unified_workspace_language_is_dropdown_with_english_first():
    assert _LANGUAGE_CHOICES[0] == ("English", "en")
    source = inspect.getsource(build_project_workspace_demo)
    assert "language = gr.Dropdown(" in source
    assert "choices=_LANGUAGE_CHOICES" in source
    assert "language = gr.Textbox(" not in source


def test_render_keeps_sections_and_status_visible_while_streaming():
    source = inspect.getsource(build_project_workspace_demo)
    render_binding = source.split("render_button.click(", 1)[1].split(
        "refresh_generated.click(", 1
    )[0]
    assert 'show_progress="hidden"' in render_binding
    assert "status_table" in render_binding
    assert "section_selection" in render_binding


def test_project_workspace_has_native_zip_download_and_delete_controls():
    source = inspect.getsource(build_project_workspace_demo)
    assert "download_project = gr.DownloadButton(" in source
    assert '"Download audio ZIP"' in source
    assert 'gr.Button("Delete project", variant="stop"' in source
    assert "create_project_audio_archive(project)" in source
    assert "shutil.rmtree(project_root)" in source
    assert "export_section_mp3s" not in source


def test_project_delete_requires_confirmation_and_stays_inside_projects_root():
    source = inspect.getsource(build_project_workspace_demo)
    assert "if not confirmed:" in source
    assert 'raise gr.Error("Confirm project deletion first.")' in source
    assert "project_root.relative_to(projects_root)" in source
    assert 'not (project_root / "project.json").exists()' in source


def test_primary_launcher_imports_after_navigation_consolidation():
    from omnivoice.cli import project_studio_voice_doctor as launcher

    assert callable(launcher.build_demo)
