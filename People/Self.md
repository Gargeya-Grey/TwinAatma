---
type: person
title: Self
description: The core ego node representing you, your operating heuristics, values, and cognitive drift over time.
id: kos:person:self
schema: knowledgeos-v0.3
status: active
created: 2026-06-19
updated: 2026-07-12
tags: [ego-node, core, systems]
timestamp: 2026-06-19T00:00:00Z
last_reviewed: 2026-07-12
---

# Self

This note represents you—the owner of this KnowledgeOS. It is the Identity layer of long-term memory. Agents should load it before advising; agents must **propose** edits (never silently rewrite).

Canonical sections below are machine-parseable via `python -m knowledgeos self summary`.

## Operating Heuristics & Rules of Thumb
<!-- kos:section=heuristics -->
*Define the rules you live and work by. These guide your agent when suggesting decisions or actions.*
* **Prefer durability over cleverness** — markdown + frontmatter remain source of truth.
* **Always write a decision note before shifting core project scope.**
* **Close loops** — Capture → Decide → Outcome → Lesson → Self update.
* **Prefer MCP Memory API over ad-hoc vault grepping** when an agent needs long-term context.

## Values Hierarchy
<!-- kos:section=values -->
*A ranked list of your core values/drivers. Updates when your priorities shift.*
1. **Rigor** — In-depth analysis and solid logic.
2. **Autonomy** — Self-directed execution and learning.
3. **Execution** — Getting things done over theoretical planning.

## Mental Models
<!-- kos:section=mental_models -->
*Favorite cognitive frameworks currently in use for analyzing concepts and decisions.*
* **First Principles Thinking**: Deconstructing problems to their most fundamental truths.
* **Inversion**: Looking at problems backwards to avoid bad outcomes.
* **Harness > Model**: Invest in systems around the model, not only the model.

## Anti-Goals
<!-- kos:section=anti_goals -->
*Things you actively want to avoid becoming, doing, or prioritizing.*
* Building complex systems before validating the core premise.
* Allowing the Inbox folder to exceed 20 raw notes.
* Inventing a proprietary memory format that competes with OKF.

## Active Bets
<!-- kos:section=active_bets -->
*Current strategic bets / commitments the agent should treat as live context.*
* KnowledgeOS becomes plug-and-play portable Self-memory via SDK + MCP.
* Memory evolution (outcomes → Self) beats retrieval-only second brains.

## Drift Log
<!-- kos:section=drift_log -->
*Append-only record of how thinking changed. Prefer proposals → accepted patches.*

| Topic | Shift Observed | Date Flagged | Evidence |
|---|---|---|---|
| AI Architecture | From model-centric logic to harness-first systems design. | 2026-06-19 | Concepts/agent-harness-architecture.md |
| KnowledgeOS positioning | From Obsidian PKM vault to portable cognitive infrastructure / Self-memory. | 2026-07-12 | Decisions/strategic-implementation-plan-v1.md |

## Related
- [Strategic Implementation Plan v1](../Decisions/strategic-implementation-plan-v1.md)
- [How KnowledgeOS Works](../MOCs/_MOC_How_KnowledgeOS_Works.md)
