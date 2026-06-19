---
type: research
title: Open Knowledge Format — Google Cloud Blog
description: Source note on Google's OKF proposal and implications for KnowledgeOS portability.
status: active
schema: knowledgeos-v0.2
created: 2026-06-18
updated: 2026-06-18
timestamp: 2026-06-18T00:00:00Z
resource: https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing
tags: [okf, knowledge-format, agentic-knowledge, google-cloud, source]
source_type: article
project: KnowledgeOS
---
# Open Knowledge Format — Google Cloud Blog

## Source
- URL: https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing
- Publisher: Google Cloud Blog
- Published: 2026-06-13
- Authors: Sam McVeety, Amir Hormati

## Core Idea
The Open Knowledge Format (OKF) proposes that AI-operable knowledge should be represented as a portable directory of markdown files with YAML frontmatter and ordinary markdown links.

The important shift is from **knowledge as a platform** to **knowledge as a format**.

## Key Principles
- **Just markdown** — readable anywhere, renderable on GitHub, searchable by ordinary tools.
- **Just files** — shippable as folders, repos, or archives.
- **Just YAML frontmatter** — enough metadata for agents and tools to query.
- **Producer/consumer independence** — humans, agents, scripts, or exports can produce knowledge; other agents/tools can consume it.
- **Format, not platform** — no required cloud, SDK, database, or proprietary service.

## Implications for KnowledgeOS
KnowledgeOS already follows much of this pattern:
- Markdown notes are the source of truth.
- YAML frontmatter defines note type, status, tags, project, and dates.
- Wikilinks form the graph.
- MOCs provide curated navigation.
- SQLite is a derived index, not the canonical store.

The improvement is to formalize a small portable schema and add validation/export tooling.

## Adopted KnowledgeOS Changes
- Add a KnowledgeOS schema note documenting the portable frontmatter contract.
- Add optional OKF-inspired fields: `title`, `description`, `resource`, `timestamp`, and `schema`.
- Add schema validation so Hermes can catch missing metadata.
- Add bundle export so domains/projects can be shared as portable markdown bundles.

## Related Notes
- [[../MOCs/_MOC_KnowledgeOS|KnowledgeOS MOC]]
- [[../MOCs/_MOC_Execution_System|Execution System MOC]]
- [[../Decisions/okf-inspired-portable-knowledge-schema|OKF-Inspired Portable Knowledge Schema]]
- [[knowledgeos-portable-schema|KnowledgeOS Portable Schema]]
