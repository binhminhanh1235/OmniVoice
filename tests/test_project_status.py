import json
from pathlib import Path

from omnivoice.project_status import (
    DEFAULT_QUEUE_PROJECT_STATUSES,
    filter_project_statuses,
    scan_project_statuses,
    summarize_project,
)


def _project(root: Path, name: str, statuses, complete=None):
    project_root = root / "projects" / name.lower()
    project_root.mkdir(parents=True)
    ids = [f"S{index:02d}" for index in range(1, len(statuses) + 1)]
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "title": name,
                "updated_at": "2026-09-01T12:00:00+00:00",
                "sections": [
                    {"id": section_id, "status": status, "audio_file": None}
                    for section_id, status in zip(ids, statuses)
                ],
            }
        ),
        encoding="utf-8",
    )
    complete_flags = complete if complete is not None else [status == "verified" for status in statuses]
    (project_root / "section-status.json").write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": "2026-09-01T12:01:00+00:00",
                "sections": {
                    section_id: {
                        "status": status,
                        "complete": bool(done),
                        "audio_file": f"sections/{section_id}/{section_id}.wav" if done else None,
                    }
                    for section_id, status, done in zip(ids, statuses, complete_flags)
                },
            }
        ),
        encoding="utf-8",
    )
    return project_root


def test_project_status_derives_done_generating_review_failed_and_pending(tmp_path):
    done = _project(tmp_path, "Done", ["verified", "verified"])
    generating = _project(tmp_path, "Generating", ["verified", "generating"])
    review = _project(tmp_path, "Review", ["verified", "unverified"])
    failed = _project(tmp_path, "Failed", ["verified", "failed"])
    pending = _project(tmp_path, "Pending", ["verified", "pending"])

    assert summarize_project(done).status == "DONE"
    assert summarize_project(generating).status == "GENERATING"
    assert summarize_project(review).status == "NEEDS_REVIEW"
    assert summarize_project(failed).status == "FAILED"
    assert summarize_project(pending).status == "PENDING"


def test_default_queue_filter_only_shows_pending_and_generating(tmp_path):
    _project(tmp_path, "Done", ["verified"])
    pending = _project(tmp_path, "Pending", ["pending"])
    generating = _project(tmp_path, "Generating", ["generating"])
    _project(tmp_path, "Review", ["unverified"])

    summaries = scan_project_statuses(tmp_path / "projects")
    filtered = filter_project_statuses(summaries)

    assert tuple(DEFAULT_QUEUE_PROJECT_STATUSES) == ("PENDING", "GENERATING")
    assert {item.title for item in filtered} == {"Pending", "Generating"}
    assert str(pending) in {item.path for item in filtered}
    assert str(generating) in {item.path for item in filtered}


def test_filter_can_include_done_and_exclude_already_queued_project(tmp_path):
    done = _project(tmp_path, "Done", ["verified"])
    pending = _project(tmp_path, "Pending", ["pending"])

    summaries = scan_project_statuses(tmp_path / "projects")
    filtered = filter_project_statuses(
        summaries,
        ["PENDING", "DONE"],
        exclude_paths=[pending],
    )

    assert [item.title for item in filtered] == ["Done"]
    assert filtered[0].path == str(done)


def test_dropdown_label_contains_status_progress_and_title(tmp_path):
    project = _project(tmp_path, "My Video", ["verified", "pending"])
    summary = summarize_project(project)
    assert summary.dropdown_label == "[PENDING 1/2] My Video"
