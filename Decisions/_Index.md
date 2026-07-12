---
type: index
title: Decisions Index
description: Index and operating rules for Decisions Index.
schema: knowledgeos-v0.2
status: active
tags: [decisions, index]
created: 2026-06-05
updated: 2026-07-12
timestamp: 2026-07-12T00:00:00Z
---
# Decisions Index

Decisions are first-class citizens. Log choices that affect strategy, architecture, scope, priority, money, or time.

## Existing Decisions
- [Public brand is TwinAatma](public-brand-twinaatma.md) — **human-facing name; internals stay knowledgeos**
- [KnowledgeOS Absolute-Best Strategic Implementation Plan (v1)](strategic-implementation-plan-v1.md) — **active roadmap; execute by phase gates**
- [Guaranteed Autopilot](guaranteed-autopilot.md)
- [Invisible Twin Autopilot](invisible-twin-autopilot.md)
- [KnowledgeOS MCP Memory Server](knowledgeos-mcp-memory-server.md) — **P3 shipped**
- [Connect Notion as Execution Layer](connect-notion-execution-layer.md)
- [Refinement Bar for Notion Publishing](refinement-bar-for-notion-publishing.md)
- [Obsidian, Notion, Hermes Role Boundaries](obsidian-notion-hermes-role-boundaries.md)
- [OKF-Inspired Portable Knowledge Schema](okf-inspired-portable-knowledge-schema.md)

## Decisions to Make
- What pilot result is strong enough to become a case study.
- Which task manager/database is canonical for atomic execution tasks.
- Whether/when to version-migrate package rename from `knowledgeos` → `twinaatma`.

## Recently Decided
- MCP runtime: stdlib JSON-RPC stdio (see KnowledgeOS MCP Memory Server).
- Starter path: `python -m knowledgeos init` generates clean vault (examples split optional).

## Decision Quality Bar
A good decision note includes:
- context
- alternatives
- chosen decision
- reasoning
- expected outcome
- revisit date or actual outcome
