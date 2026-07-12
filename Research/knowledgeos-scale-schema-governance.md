---
type: research
title: KnowledgeOS Scale & Schema Governance
description: Performance budgets and schema versioning policy for KnowledgeOS.
schema: knowledgeos-v0.3
status: active
created: 2026-07-12
updated: 2026-07-12
timestamp: 2026-07-12T00:00:00Z
tags: [knowledgeos, scale, schema, governance]
project: KnowledgeOS
id: kos:research:scale-schema-governance
---

# KnowledgeOS Scale & Schema Governance

## Scale budgets

| Scale | Expectation |
|---|---|
| ≤1k notes | Instant CLI/MCP search |
| ≤10k notes | `rebuild_index.py` < ~60s on a modest laptop |
| ≤50k notes | Still markdown-canonical; consider incremental FTS strategies / exclude Archive from hot rebuilds |

Graph centrality (PageRank, etc.) is explicitly deferred until retrieval quality stalls.

## Schema versioning

- **Additive minors** (`v0.2` → `v0.3`): new optional fields/types; old notes remain valid.
- **Breaking majors** (`v1.0`): only with migration notes + validator support window.
- `knowledgeos-v0.2` remains accepted indefinitely while v0.3 fields are optional.
- Validators **warn** on unknown types/versions; **error** on missing required fields / bad ids / bad outcome_status.

## OKF stance

KnowledgeOS stays OKF-inspired/compatible: markdown + YAML + links + git. Cognitive extensions (`decision` outcomes, `belief`, `heuristic`, Self sections) live above the format layer — not as a competing standard.

## Related

- [Portable Schema](knowledgeos-portable-schema.md)
- [Strategic Implementation Plan v1](../Decisions/strategic-implementation-plan-v1.md)
