from pathlib import Path


def test_live_status_doc_mentions_streaming_states():
    text = Path("docs/live-section-status.md").read_text(encoding="utf-8")
    for marker in ("QUEUED", "GENERATING", "VERIFIED", "FAILED", "SKIPPED"):
        assert marker in text
