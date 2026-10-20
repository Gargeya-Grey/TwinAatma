---
type: moc
title: Execution System MOC
description: Map of Content for Execution System MOC.
schema: knowledgeos-v0.2
status: active
created: 2026-06-18
updated: 2026-06-18
tags: [moc, execution-system, obsidian, notion, hermes]
timestamp: 2026-06-18T00:00:00Z
---
# Execution System MOC

This note defines how KnowledgeOS becomes a real second brain + execution system.

## Role Boundaries

### Obsidian = Thinking / Knowledge Graph
Use Obsidian for:
- raw capture and private thinking
- research notes, concepts, source notes, book/paper notes
- project context and strategy
- decision logs
- experiment hypotheses/results
- weekly/monthly synthesis
- startup/product narrative evolution

Obsidian should answer: **What do I know, why do I believe it, and how does it connect?**

### Notion = Execution / Operational Database
Use Notion for:
- tasks with owners/dates/status
- execution dashboards
- refined project operating docs
- SOPs and repeatable processes
- external/shareable polished notes when useful

Notion should answer: **What must happen next, who owns it, by when, and what is the state?**

### Hermes = Orchestrator / AI Operator
Use Hermes for:
- searching and synthesizing KnowledgeOS
- creating notes from templates
- rebuilding indexes
- generating dashboards and weekly drafts
- processing Inbox material
- preparing Notion publishing candidates
- maintaining MOCs and links

Hermes should answer: **How do I transform messy knowledge into structured insight and action?**

### Tasks / Projects
- Project context lives in Obsidian.
- Atomic execution tasks should live in Notion or the chosen task manager.
- Hermes can extract suggested tasks from Obsidian notes, but Obsidian should not become the primary task database.

## Operating Cadence

### Daily
1. Capture raw ideas into Inbox — or just tell the agent and it captures for you.
2. Process urgent captures into typed notes.
3. The index refreshes itself before the next search.

### Weekly
1. Ask the agent for a week summary; it loads the timeline and drift signals.
2. Review the single drift proposal it drafted (yes/no).
3. Review active projects and experiments.
4. Decide what moves to Notion or becomes an action.

### Monthly
1. Use [Monthly Review Template](../Templates/t-monthly-review.md).
2. Archive stale projects.
3. Update startup/product thesis.
4. Review learning roadmap.

## Knowledge → Action Flow

```text
Inbox / Research / Conversations
→ typed Obsidian notes
→ linked project/decision/experiment
→ weekly synthesis
→ Notion tasks or refined docs
→ execution evidence
→ back into Obsidian synthesis
```

## Publishing Policy
- Rough thinking stays in Obsidian.
- Refined operational notes may publish to Notion.
- Only publish notes that meet [Refinement Bar for Notion Publishing](../Decisions/refinement-bar-for-notion-publishing.md).

## Dashboards
- [Master MOC](_MOC_Master.md)
- [Active Work MOC](_MOC_Active.md)
- [Startup MOC](_MOC_Startup.md)
- [KnowledgeOS MOC](_MOC_KnowledgeOS.md)
- [Experiments Dashboard](_MOC_Experiments.md)

## Open Design Questions
- Which task manager/database should be the canonical task layer?
- What Notion database properties should mirror Obsidian project/decision states?
- Which weekly synthesis outputs should be automatically published?
