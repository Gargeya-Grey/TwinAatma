---
type: decision
title: Obsidian, Notion, Hermes Role Boundaries
description: Decision log for Obsidian, Notion, Hermes Role Boundaries.
schema: knowledgeos-v0.2
status: active
created: 2026-06-18
updated: 2026-06-18
tags: [knowledgeos, execution-system, notion, obsidian, hermes]
project: KnowledgeOS
timestamp: 2026-06-18T00:00:00Z
---
# Obsidian, Notion, Hermes Role Boundaries

## Context
KnowledgeOS needs clear boundaries so the system does not become duplicated across tools.

## Decision
Use a three-layer model:

1. **Obsidian is the thinking and knowledge graph layer.**
2. **Notion is the execution and operational database layer.**
3. **Hermes is the orchestration and synthesis layer.**

## Rationale
Obsidian is strongest for linked thinking and context. Notion is strongest for dashboards, task databases, and operational execution. Hermes is strongest for transforming, searching, generating, and maintaining structure across both.

## Rules
- Do not use Obsidian as the canonical task database.
- Do not use Notion as the canonical raw thinking/archive layer.
- Do not manually duplicate everything between tools.
- Publish from Obsidian to Notion only when notes meet the refinement bar.
- Keep decisions in Obsidian even if their tasks appear in Notion.

## Expected Outcome
The system remains clear: thinking compounds in Obsidian, execution moves in Notion, and Hermes keeps the loop alive.

## Related Notes
- [[../MOCs/_MOC_Execution_System|Execution System MOC]]
- [[refinement-bar-for-notion-publishing|Refinement Bar for Notion Publishing]]
- [[connect-notion-execution-layer|Connect Notion as Execution Layer]]
