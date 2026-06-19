---
type: research
title: KnowledgeOS Portable Schema
description: The portable frontmatter and linking contract that makes KnowledgeOS human-readable and agent-readable.
status: active
schema: knowledgeos-v0.2
created: 2026-06-18
updated: 2026-06-18
timestamp: 2026-06-18T00:00:00Z
resource:
tags: [knowledgeos, schema, okf, metadata, interoperability]
project: KnowledgeOS
---
# KnowledgeOS Portable Schema

KnowledgeOS uses markdown files plus YAML frontmatter as the durable source of truth. Obsidian, Hermes, SQLite, Notion, and exports are consumers of this format — they are not the canonical store.

## Design Goal
Make every important note:
- readable by a human in any markdown editor
- parseable by Hermes or another agent
- searchable through the SQLite index
- portable as a folder/repo/archive
- understandable without Obsidian-specific UI

## Required Frontmatter
Every non-template content note should include:

```yaml
type: project | research | concept | decision | experiment | synthesis | meeting | person | moc | index
title: Human-readable title
description: One-sentence summary of the note
status: draft | active | refined | archived
schema: knowledgeos-v0.2
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [domain, topic]
```

## Recommended Frontmatter
Use these when relevant:

```yaml
project: "Example Project"
resource: https://example.com/source-or-canonical-resource
timestamp: 2026-06-18T00:00:00Z
source_type: article | book | paper | video | conversation | website | dataset
publish_to_notion: false
```

## Field Meaning
| Field | Meaning |
|---|---|
| `type` | What kind of note this is. This is the core interoperability field. |
| `title` | Stable display title, independent of filename. |
| `description` | One-line explanation for search results, exports, and agents. |
| `status` | Lifecycle state. |
| `schema` | KnowledgeOS schema version used by the note. |
| `created` / `updated` | Note lifecycle dates. |
| `timestamp` | Source/capture/event timestamp when applicable. |
| `resource` | Canonical external URL/file/resource when the note is source-backed. |
| `tags` | Topic/domain facets. |
| `project` | Project/domain this note supports. |

## Linking Contract
- Use Obsidian wikilinks for internal relationships: `[[../Projects/example-project|Example Project]]`.
- Every non-index content note should link to at least one project, MOC, decision, concept, source, or experiment.
- MOCs are curated navigation; links are the graph; SQLite is a derived index.

## Portability Rule
A note should still make sense if exported outside Obsidian. Avoid relying only on visual graph position, plugin state, or app-specific metadata.

## Validation
Run:

```bash
python scripts/validate_schema.py
```

This reports missing required/recommended metadata and zero-link notes.

## Export
Run:

```bash
python scripts/export_bundle.py --project "Example Project" --out exports/example-bundle
```

This creates a portable markdown bundle plus `manifest.json`.

## Related Notes
- [[open-knowledge-format-google-cloud|Open Knowledge Format — Google Cloud Blog]]
- [[../Decisions/okf-inspired-portable-knowledge-schema|OKF-Inspired Portable Knowledge Schema]]
- [[../MOCs/_MOC_KnowledgeOS|KnowledgeOS MOC]]
