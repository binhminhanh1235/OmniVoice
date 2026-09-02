#!/usr/bin/env python3
# Copyright 2026 OmniVoice contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Non-destructive script cleanup and review hints for Project Studio.

Text Doctor separates two classes of changes:

* **safe fixes** are formatting/encoding artifacts that should never be spoken,
  such as HTML space entities, NBSP/zero-width characters, tabs, Markdown hard
  line-break backslashes, and stray trailing whitespace;
* **review hints** flag text whose spoken form may be ambiguous (numbers,
  abbreviations, unknown directives) without silently rewriting it.

The result always includes a visible change list and unified diff so the user
can inspect what will be sent to the project parser.
"""

from __future__ import annotations

import difflib
import html
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Iterable

_ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
_SECTION_RE = re.compile(r"^\s*##\s+S\d+\b", re.IGNORECASE)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
_DIRECTIVE_RE = re.compile(r"^\s*\[([^\]]+)\](?:\s+|$)")
_NUMBER_RE = re.compile(r"(?<![A-Za-z])\d[\d,.:/\-]*")
_ABBREVIATION_RE = re.compile(r"\b(?:[A-Z][a-z]{0,3}\.|[A-Z]{2,6})\b")

# Generic Project Studio intents plus documented native-ish controls already
# understood by the style layer. Unknown tags are left untouched but flagged.
_KNOWN_DIRECTIVES = {
    "DEFAULT",
    "NORMAL",
    "WARM",
    "SOFT",
    "EMPHASIZE",
    "PRAYER",
    "WHISPER",
    "LOW_PITCH",
    "LOW PITCH",
    "HIGH_PITCH",
    "HIGH PITCH",
}


@dataclass(frozen=True)
class TextDoctorChange:
    line: int
    severity: str
    kind: str
    before: str
    after: str
    note: str


@dataclass
class TextDoctorResult:
    original: str
    cleaned: str
    changes: list[TextDoctorChange] = field(default_factory=list)

    @property
    def safe_change_count(self) -> int:
        return sum(item.severity == "fixed" for item in self.changes)

    @property
    def review_count(self) -> int:
        return sum(item.severity == "review" for item in self.changes)

    @property
    def diff(self) -> str:
        if self.original == self.cleaned:
            return ""
        return "\n".join(
            difflib.unified_diff(
                self.original.splitlines(),
                self.cleaned.splitlines(),
                fromfile="original",
                tofile="cleaned",
                lineterm="",
            )
        )

    def to_dict(self) -> dict:
        return {
            "safe_change_count": self.safe_change_count,
            "review_count": self.review_count,
            "changes": [asdict(item) for item in self.changes],
            "diff": self.diff,
        }


def _directive_name(line: str) -> str | None:
    match = _DIRECTIVE_RE.match(line)
    if not match:
        return None
    return match.group(1).strip().upper()


def _is_metadata_line(line: str) -> bool:
    return bool(_HEADING_RE.match(line))


def _safe_clean_line(line: str) -> tuple[str, list[tuple[str, str]]]:
    """Return a cleaned line plus `(kind, note)` descriptions."""

    current = line
    notes: list[tuple[str, str]] = []

    unescaped = html.unescape(current)
    if unescaped != current:
        current = unescaped
        notes.append(("html_entity", "Decoded HTML entity before TTS."))

    normalized = unicodedata.normalize("NFKC", current)
    if normalized != current:
        current = normalized
        notes.append(("unicode", "Normalized compatibility Unicode characters."))

    without_zero_width = _ZERO_WIDTH_RE.sub("", current)
    if without_zero_width != current:
        current = without_zero_width
        notes.append(("zero_width", "Removed invisible zero-width character."))

    replaced_nbsp = current.replace("\u00a0", " ")
    if replaced_nbsp != current:
        current = replaced_nbsp
        notes.append(("nbsp", "Replaced non-breaking space with normal space."))

    replaced_tabs = current.replace("\t", " ")
    if replaced_tabs != current:
        current = replaced_tabs
        notes.append(("tabs", "Replaced tab with normal space."))

    # Backslash at the end of a narration line is a Markdown hard line break,
    # not something the TTS should attempt to pronounce/tokenize.
    no_markdown_break = re.sub(r"\\\s*$", "", current)
    if no_markdown_break != current:
        current = no_markdown_break
        notes.append(("markdown_break", "Removed Markdown line-break backslash."))

    collapsed = re.sub(r"[ ]{2,}", " ", current).rstrip()
    if collapsed != current:
        current = collapsed
        notes.append(("whitespace", "Collapsed repeated/trailing horizontal whitespace."))

    return current, notes


def inspect_script(script: str) -> TextDoctorResult:
    """Safely clean a full Project Studio Markdown script.

    Headings and section markers are retained as metadata. Directive tags are
    retained for the project parser, but unknown directives are flagged.
    Numbers and abbreviations in narration are review hints only.
    """

    if not isinstance(script, str):
        raise TypeError("script must be a string")

    # Normalize line endings before per-line inspection. split('\n') preserves
    # intentional blank lines and the final-line structure better than splitlines().
    original = script.replace("\r\n", "\n").replace("\r", "\n")
    output_lines: list[str] = []
    changes: list[TextDoctorChange] = []

    for line_number, line in enumerate(original.split("\n"), start=1):
        cleaned, safe_notes = _safe_clean_line(line)
        for kind, note in safe_notes:
            changes.append(
                TextDoctorChange(
                    line=line_number,
                    severity="fixed",
                    kind=kind,
                    before=line,
                    after=cleaned,
                    note=note,
                )
            )

        output_lines.append(cleaned)

        directive = _directive_name(cleaned)
        if directive is not None:
            canonical = directive.replace("-", "_")
            if canonical not in _KNOWN_DIRECTIVES:
                changes.append(
                    TextDoctorChange(
                        line=line_number,
                        severity="review",
                        kind="unknown_directive",
                        before=cleaned,
                        after=cleaned,
                        note=(
                            f"Directive [{directive}] is not in the known style map; "
                            "it will not be sent blindly as OmniVoice instruct text."
                        ),
                    )
                )

        if not cleaned.strip() or _is_metadata_line(cleaned):
            continue

        # Strip the leading directive only for review scanning. The actual output
        # line remains unchanged because the project parser needs the tag.
        narration = _DIRECTIVE_RE.sub("", cleaned, count=1).strip()
        if not narration:
            continue

        numbers = _NUMBER_RE.findall(narration)
        if numbers:
            changes.append(
                TextDoctorChange(
                    line=line_number,
                    severity="review",
                    kind="number",
                    before=cleaned,
                    after=cleaned,
                    note=(
                        "Check spoken form for number(s): " + ", ".join(numbers) + ". "
                        "Text Doctor does not rewrite numbers automatically."
                    ),
                )
            )

        abbreviations = sorted(set(_ABBREVIATION_RE.findall(narration)))
        if abbreviations:
            changes.append(
                TextDoctorChange(
                    line=line_number,
                    severity="review",
                    kind="abbreviation",
                    before=cleaned,
                    after=cleaned,
                    note=(
                        "Check pronunciation for abbreviation(s): "
                        + ", ".join(abbreviations)
                        + "."
                    ),
                )
            )

    cleaned_script = "\n".join(output_lines)
    return TextDoctorResult(
        original=original,
        cleaned=cleaned_script,
        changes=changes,
    )


def changes_as_rows(changes: Iterable[TextDoctorChange]) -> list[list[str | int]]:
    """Convert changes to a Gradio/DataFrame-friendly table."""

    return [
        [
            item.line,
            item.severity,
            item.kind,
            item.before,
            item.after,
            item.note,
        ]
        for item in changes
    ]
