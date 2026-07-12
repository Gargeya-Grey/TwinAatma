---
type: decision
title: Demo — Close decision outcomes into Self lessons
description: P4 exit-gate demo decision proving expected → actual → lesson → Self proposal.
id: kos:decision:demo-close-outcomes-into-self
schema: knowledgeos-v0.3
status: active
created: 2026-07-12
updated: 2026-07-12
timestamp: 2026-07-12T00:00:00Z
tags: [demo, knowledgeos, outcomes, self]
project: KnowledgeOS
expected_outcome: Agents can close a decision loop and promote lessons to Self via proposals only.
actual_outcome: Demo path exercised on 2026-07-12 — proposal created; Self only mutates on explicit accept.
outcome_status: confirmed
lesson: Never silently rewrite Self.md; always proposal → human accept/reject.
review_after: 2026-07-01
confidence: 0.9
last_reviewed: 2026-07-12
---

# Demo — Close decision outcomes into Self lessons

## Context

Phase 4 requires a closed loop from decisions to Self evolution.

## Alternatives Considered

1. Auto-write lessons into Self — rejected (trust destruction).
2. Manual copy-paste only — rejected (agents can't help).
3. Proposal files + accept/reject tools — chosen.

## Decision

Use `People/Self-Proposals/` + `memory_propose_from_lesson` / `propose_self_update.py` / MCP tools. Self mutates only on explicit accept.

## Reasoning

Digital-self compounding requires write-back, but Ego Node integrity requires human confirmation.

## Expected Outcome

Agents can close a decision loop and promote lessons to Self via proposals only.

## Actual Outcome

Demo path exercised on 2026-07-12 — proposal created; Self only mutates on explicit accept.

## Lesson

Never silently rewrite Self.md; always proposal → human accept/reject.

## Related

- [Strategic Implementation Plan v1](strategic-implementation-plan-v1.md)
- [Heuristic Promotion Rules](../Concepts/heuristic-promotion-rules.md)
- [Self](../People/Self.md)
- [Outcomes Dashboard](../MOCs/_MOC_Outcomes.md)
