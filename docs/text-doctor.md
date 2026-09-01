# Text Doctor

Text Doctor is the first safety step before a Markdown narration script becomes an OmniVoice project.

It is deliberately **non-destructive**. Formatting artifacts that have no intended spoken meaning are safe to fix automatically. Anything that could change pronunciation or meaning is surfaced for human review instead.

## Safe automatic fixes

- Decode HTML entities such as `&#x20;` and `&nbsp;`.
- Normalize compatibility Unicode with NFKC.
- Remove zero-width / BOM characters.
- Replace non-breaking spaces and tabs with normal spaces.
- Remove Markdown hard-line-break backslashes at the end of narration lines.
- Collapse repeated horizontal whitespace and trailing spaces.

Project metadata remains intact:

```markdown
# Video title
## S01 — 0:00–0:45
### Section heading
[WARM] Narration starts here.
```

The `#` headings and `[WARM]` tag still exist after Text Doctor so the project parser can use them. They are later removed from the spoken text by the parser.

## Review-only hints

Text Doctor does **not** silently rewrite:

- numbers and Bible references such as `2 Thessalonians 3`;
- acronyms / abbreviations such as `NASA`;
- unknown directive tags.

These appear in the review table because their correct spoken form depends on context.

Example:

```text
Line 42 | review | number
Check spoken form for number(s): 2, 3.
```

The source remains:

```text
Paul addresses it in 2 Thessalonians 3.
```

## UI workflow

1. Paste the complete Markdown script into **1. Text Doctor**.
2. Click **Analyze & clean safe issues**.
3. Review:
   - summary counts;
   - cleaned script;
   - change/review table;
   - unified diff.
4. Copy the cleaned script into **2. Project Studio → Project Setup**.
5. Parse/create the project and continue to Preview / Generate.

## Why Text Doctor does not auto-expand numbers

Text normalization can improve TTS, but automatic number expansion can also change intent. A timestamp, Bible reference, year, amount, phone number, chapter/verse, decimal, or ordinal should not all follow the same spoken rule.

A future extension can offer explicit user-approved transforms, but the default workflow keeps semantic changes visible and reversible.