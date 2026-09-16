# Native OmniVoice project import API

`POST /api/v1/projects/import` creates a Studio project directly from the native OmniVoice Markdown narration format. It is a synchronous metadata/filesystem operation: it parses and persists the project, but it does **not** enqueue GPU work or generate audio.

## Discover the capability

Clients should call:

```http
GET /api/v1/capabilities
```

and verify:

```json
{
  "features": {
    "project_import": true
  },
  "endpoints": {
    "project_import": "/api/v1/projects/import"
  }
}
```

Do not infer the endpoint from the API version string.

## Native script format

The request accepts the same narration grammar used by OmniVoice Project Studio:

```markdown
# Video title

## S01 — 0:00–0:20

### Optional section title

[WARM] First narration paragraph.

More narration.

## S02 — 0:20–0:45

[SOFT] Second section.
```

Style directives such as `[WARM]` are metadata and are not spoken. `###` headings remain metadata unless `speak_section_titles` is enabled. Visual metadata such as Pexels queries does not belong in this script and is not part of the OmniVoice grammar.

## Import a project

```bash
curl -X POST "$OMNIVOICE_STUDIO_URL/api/v1/projects/import" \
  -H "Authorization: Bearer $OMNIVOICE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "demo-video",
    "script": "# Demo\n\n## S01 — 0:00–0:20\n\n[WARM] Hello world.",
    "speak_section_titles": false
  }'
```

Optional chunk controls use the current canonical defaults when omitted:

```json
{
  "max_chunk_words": 24,
  "max_chunk_chars": 220
}
```

Project import does not accept voice, provider, API token, language-generation, quality-preset, or GPU configuration. Those belong to generation runtime calls.

## Response and idempotency

A new project returns `201 Created`:

```json
{
  "project_id": "demo-video",
  "title": "Demo",
  "created": true,
  "source_hash": "...",
  "status": "PENDING",
  "sections": [
    {
      "id": "S01",
      "start_time": "0:00",
      "end_time": "0:20",
      "title": null
    }
  ],
  "links": {
    "self": "/api/v1/projects/demo-video",
    "generate": "/api/v1/projects/demo-video/generate"
  }
}
```

Retrying the same `project_id`, canonical source, and chunk options returns the existing project with `200 OK` and `created: false`. Existing generated artifacts are not rewritten or deleted.

If the same project ID already exists with a different source or chunk options, the API returns `409 Conflict` and preserves the existing project:

```json
{
  "detail": "Project already exists with different source"
}
```

There is intentionally no `overwrite=true` mode in v1.

## Safety and atomicity

`project_id` is trimmed and must be one safe path component. Values containing `/`, `\\`, `.`, `..`, or traversal are rejected. Clients cannot provide a filesystem path.

Imports are built in a hidden staging directory outside `<workspace>/projects` and are published by rename only after the canonical narration project has been persisted successfully. Invalid scripts and storage failures therefore do not publish a valid-looking project under the Studio projects directory.

The original UTF-8 narration script is preserved in:

```text
<workspace>/projects/<project_id>/script.md
```

## Generate after import

After a successful import, use the existing asynchronous generation API:

```bash
curl -X POST \
  "$OMNIVOICE_STUDIO_URL/api/v1/projects/demo-video/generate" \
  -H "Authorization: Bearer $OMNIVOICE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "voice_name": "Narrator",
    "voice_variant": "AUTO",
    "language": "en",
    "quality_preset": "BALANCED",
    "resume": true
  }'
```

Generation keeps its existing durable Job Manager / SSE lifecycle. Project import itself never creates a fake GPU job.

## Authentication

`POST /api/v1/projects/import` uses the existing machine bearer boundary and requires the same `omnivoice:generate` scope used by generation write operations. Tokens and full request bodies should not be written to production logs.
