---
type: synthesis
title: Weekly Synthesis Draft — 2026-07-12
description: Auto-drafted weekly synthesis covering 2026-07-05 to 2026-07-12.
schema: knowledgeos-v0.3
status: draft
created: 2026-07-12
updated: 2026-07-12
timestamp: 2026-07-12T00:00:00Z
tags: [weekly, synthesis, auto-draft]
project: KnowledgeOS
---
# Weekly Synthesis Draft — 2026-07-12

Period: 2026-07-05 → 2026-07-12

## Operating Loop Checklist

Canonical loop: **Capture → Clarify → Connect → Decide → Execute → Record Outcome → Review → Update Self**

- [ ] Capture: Inbox triaged (`python scripts/daily_capture_report.py`)
- [ ] Clarify: raw notes typed + linked
- [ ] Connect: orphans resolved (`python scripts/validate_schema.py`)
- [ ] Decide: important choices logged in `Decisions/`
- [ ] Execute: next actions moved outside vault if needed
- [ ] Record Outcome: fill `actual_outcome` / `outcome_status` / `lesson`
- [ ] Review: alignment + drift (`python scripts/check_alignment.py`)
- [ ] Update Self: accept/reject proposals under `People/Self-Proposals/`

## New / Updated Notes

- [Heuristic Promotion Rules](../../Concepts/heuristic-promotion-rules.md) — concept / active
- [Connect Notion as the Execution Layer for KnowledgeOS](../../Decisions/connect-notion-execution-layer.md) — decision / active
- [Demo — Close decision outcomes into Self lessons](../../Decisions/demo-close-outcomes-into-self.md) — decision / active
- [KnowledgeOS MCP Memory Server](../../Decisions/knowledgeos-mcp-memory-server.md) — decision / active
- [KnowledgeOS Absolute-Best Strategic Implementation Plan (v1)](../../Decisions/strategic-implementation-plan-v1.md) — decision / active
- [Decisions Index](../../Decisions/_Index.md) — index / active
- [MCP smoke capture](../../Inbox/2026-07-12-MCP-smoke-capture.md) — research / draft
- [Active Work MOC](../../MOCs/_MOC_Active.md) — moc / active
- [Experiments Dashboard](../../MOCs/_MOC_Experiments.md) — moc / active
- [How KnowledgeOS Works](../../MOCs/_MOC_How_KnowledgeOS_Works.md) — moc / active
- [Self](../../People/Self.md) — person / active
- [KnowledgeOS](../../Projects/knowledgeos.md) — project / active
- [Self proposal — heuristics](../../People/Self-Proposals/20260712-191951-heuristics.md) — research / refined

## Decisions this week

- [Connect Notion as the Execution Layer for KnowledgeOS](../../Decisions/connect-notion-execution-layer.md)
- [Demo — Close decision outcomes into Self lessons](../../Decisions/demo-close-outcomes-into-self.md)
- [KnowledgeOS MCP Memory Server](../../Decisions/knowledgeos-mcp-memory-server.md)
- [KnowledgeOS Absolute-Best Strategic Implementation Plan (v1)](../../Decisions/strategic-implementation-plan-v1.md)

## Decisions due for outcome review

- [Connect Notion as the Execution Layer for KnowledgeOS](../../Decisions/connect-notion-execution-layer.md) — awaiting; review_after=—; outcome_status=pending
- [KnowledgeOS MCP Memory Server](../../Decisions/knowledgeos-mcp-memory-server.md) — awaiting; review_after=—; outcome_status=pending
- [KnowledgeOS Absolute-Best Strategic Implementation Plan (v1)](../../Decisions/strategic-implementation-plan-v1.md) — awaiting; review_after=—; outcome_status=pending
- [Obsidian, Notion, Hermes Role Boundaries](../../Decisions/obsidian-notion-hermes-role-boundaries.md) — awaiting; review_after=—; outcome_status=pending
- [OKF-Inspired Portable Knowledge Schema](../../Decisions/okf-inspired-portable-knowledge-schema.md) — awaiting; review_after=—; outcome_status=pending
- [Refinement Bar for Notion Publishing](../../Decisions/refinement-bar-for-notion-publishing.md) — awaiting; review_after=—; outcome_status=pending

After closing an outcome with a lesson:
```bash
python -m knowledgeos memory memory_propose_from_lesson --path-or-id Decisions/your-decision.md
```

## Active Projects

- [KnowledgeOS](../../Projects/knowledgeos.md) — active
- [Example Project Thesis](../../Projects/example-project-thesis.md) — active
- [Example Project](../../Projects/example-project.md) — active

## Self proposals

```bash
python -m knowledgeos memory memory_list_self_proposals
python -m knowledgeos memory memory_propose_from_drift
```

## Patterns / Synthesis

_Fill with human/AI synthesis._

## Next Week Focus

- 
