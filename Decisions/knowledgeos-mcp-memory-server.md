---
type: decision
title: KnowledgeOS MCP Memory Server
description: Adopt a stdlib MCP Memory API so any AI client can load and update portable Self-memory.
schema: knowledgeos-v0.3
status: active
created: 2026-07-12
updated: 2026-07-12
timestamp: 2026-07-12T00:00:00Z
tags: [decision, knowledgeos, mcp, memory]
project: KnowledgeOS
id: kos:decision:knowledgeos-mcp-memory-server
outcome_status: confirmed
actual_outcome: Stdlib MCP Memory server shipped 2026-07-12 with CLI fallback and proposal-only Self writes.
lesson: Prefer stdlib MCP over adding pip deps for the hottest path; keep CLI parity for non-MCP agents.
last_reviewed: 2026-07-12
---

# KnowledgeOS MCP Memory Server

## Context

Phase 3 of the strategic plan requires plug-and-play memory across AI interfaces. Notion MCP was previously rejected as execution overhead; that decision does not apply to a **KnowledgeOS-owned** Memory MCP.

## Alternatives Considered

1. **Official `mcp` Python SDK / FastMCP** — Excellent DX, but adds pip dependency for the hottest path.
2. **Node bridge calling Python CLI** — Extra runtime; worse Windows story.
3. **Stdlib JSON-RPC MCP over stdio + CLI Memory API** — Chosen. Core stays dependency-free; hosts speak MCP; agents without MCP use `python -m knowledgeos memory`.

## Decision

Ship:

- `knowledgeos/memory.py` — sandboxed Memory API
- `knowledgeos/mcp_server.py` — stdio MCP (Content-Length default)
- CLI: `python -m knowledgeos mcp` and `python -m knowledgeos memory <tool>`

Write policy:

| Action | Policy |
|---|---|
| Inbox capture | Auto-write |
| Self.md | Proposal only → explicit accept |
| Note updates | Proposal only (Inbox) |
| Notion publish | Never via MCP |

## Tools (v1)

`memory_self_get`, `memory_search`, `memory_related`, `memory_get_note`, `memory_decisions`, `memory_drift`, `memory_capture`, `memory_propose_self_update`, `memory_accept_self_update`, `memory_propose_note_update`, `memory_timeline`, `memory_bootstrap_context`

## Client config

See `mcp.cursor.example.json`. Set `cwd` and `KNOWLEDGEOS_VAULT` to the vault root.

## Related Notes

- [Strategic Implementation Plan v1](strategic-implementation-plan-v1.md)
- [Connect Notion as Execution Layer](connect-notion-execution-layer.md)
- [Self](../People/Self.md)
