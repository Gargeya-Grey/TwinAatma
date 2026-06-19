---
type: decision
title: OKF-Inspired Portable Knowledge Schema
description: Decision to evolve KnowledgeOS toward a portable markdown/frontmatter knowledge format inspired by OKF.
status: active
schema: knowledgeos-v0.2
created: 2026-06-18
updated: 2026-06-18
timestamp: 2026-06-18T00:00:00Z
resource: https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing
source_type: article
tags: [decision, knowledgeos, okf, schema, portability]
project: KnowledgeOS
---
# OKF-Inspired Portable Knowledge Schema

## Context
Google Cloud's Open Knowledge Format article argues that agentic knowledge systems need a simple portable format: markdown files, YAML frontmatter, ordinary links, and version control.

KnowledgeOS already uses this pattern, but its metadata contract can be made more explicit.

## Decision
Adopt an OKF-inspired KnowledgeOS schema convention:

- Markdown remains the source of truth.
- YAML frontmatter becomes the formal metadata contract.
- SQLite remains a derived index only.
- MOCs remain the curated navigation layer.
- Notes should include portable fields such as `title`, `description`, `resource`, `timestamp`, and `schema` where appropriate.
- Add schema validation and bundle export scripts.

## Alternatives Considered
1. Keep the current loose schema.
2. Convert the vault fully to OKF v0.1 conventions.
3. Adopt an OKF-inspired schema while preserving Obsidian/MOC ergonomics.

## Chosen Approach
Option 3. KnowledgeOS should borrow the portability and interoperability lessons from OKF without losing the practical value of MOCs, wikilinks, and personal operating workflows.

## Consequences
- Future templates should include portable metadata fields.
- Source/research notes should track `resource` and `timestamp` more consistently.
- Hermes can validate schema health before export or publishing.
- Project/domain bundles can be exported for sharing or migration.

## Related Notes
- [[../Research/open-knowledge-format-google-cloud|Open Knowledge Format — Google Cloud Blog]]
- [[../Research/knowledgeos-portable-schema|KnowledgeOS Portable Schema]]
- [[../MOCs/_MOC_KnowledgeOS|KnowledgeOS MOC]]
- [[../MOCs/_MOC_Execution_System|Execution System MOC]]
