---
type: moc
title: KnowledgeOS MOC
description: Map of Content for KnowledgeOS MOC.
schema: knowledgeos-v0.2
status: active
tags: [moc, knowledgeos, systems, second-brain]
created: 2026-06-18
updated: 2026-06-18
timestamp: 2026-06-18T00:00:00Z
---
# KnowledgeOS MOC

System hub for the AI brain itself.

## System Philosophy
- [KnowledgeOS README](../README.md)
- [How KnowledgeOS Works](_MOC_How_KnowledgeOS_Works.md)
- [Execution System MOC](_MOC_Execution_System.md)
- [Role Boundaries Decision](../Decisions/obsidian-notion-hermes-role-boundaries.md)
- [KnowledgeOS Portable Schema](../Research/knowledgeos-portable-schema.md)
- [OKF-Inspired Portable Knowledge Schema](../Decisions/okf-inspired-portable-knowledge-schema.md)
- Obsidian = thinking
- Notion = execution
- Hermes = orchestration

## Operating Loop
```text
Capture → Clarify → Connect → Commit → Execute → Review → Synthesize
```

## Core Layers
- Capture: [Inbox](../Inbox/_Index.md)
- Concepts: [Concepts Index](../Concepts/_Index.md)
- Research: [Research Index](../Research/_Index.md)
- Projects: [Projects Index](../Projects/_Index.md)
- Decisions: [Decisions Index](../Decisions/_Index.md)
- People: [People Index](../People/_Index.md)
- Templates: [Template Index](../Templates/_Index.md)
- Syntheses: [Weekly Syntheses](../Research/Synthesis/example-synthesis.md)

## Dashboards
- Active: [Active Work MOC](_MOC_Active.md)
- Experiments: [Experiments Dashboard](_MOC_Experiments.md)
- Startup: [Startup MOC](_MOC_Startup.md)
- Learning: [Learning MOC](_MOC_Learning.md)
- Ecosystem: [Ecosystem MOC](_MOC_Ecosystem.md)

## Automation
A data-only vault runs no scripts. The toolkit (binary or package) does the work:

| Command | Purpose |
|---|---|
| `twinaatma doctor` | Environment and vault diagnostics |
| `twinaatma validate` | Validate metadata/provenance/link health |
| `twinaatma breathe` | Autopilot tick: refresh index, load context |
| `twinaatma memory memory_search --query "<terms>"` | Search notes/tags/projects/body |
| `twinaatma ids assign [--write]` | Stable `kos:` entity ids |
| `twinaatma setup-host --host cursor --write` | Write the MCP host config |

Repository maintainers additionally have `scripts/` for reports, MOC generation and the
optional Notion bridge. Those never ship into a vault.

## Maintenance Rules
- Every non-index note should link to at least one MOC, project, concept, or decision.
- Project notes should contain explicit next actions.
- Decisions should be logged when they change direction, scope, priority, or resource allocation.
- Weekly synthesis should identify stale projects, missing links, and next domains to populate.
