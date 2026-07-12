---
type: concept
title: Heuristic Promotion Rules
description: When a Self.md bullet should graduate into a Concepts/ heuristic note.
schema: knowledgeos-v0.3
status: active
created: 2026-07-12
updated: 2026-07-12
timestamp: 2026-07-12T00:00:00Z
tags: [heuristic, self-model, knowledgeos]
project: KnowledgeOS
id: kos:concept:heuristic-promotion-rules
---

# Heuristic Promotion Rules

Keep most rules inside [Self](../People/Self.md) for ergonomics. Promote to `Concepts/` with `type: heuristic` when **2+** of these are true:

1. Used across **multiple projects** or decisions
2. Has been **stable for 30+ days** (survived drift reviews)
3. Needs **evidence / counterexamples** longer than a bullet
4. Agents keep re-deriving it from vault search instead of Self

## Process

1. Keep the short form in Self heuristics
2. Create note from `Templates/t-heuristic.md`
3. Link Self bullet → heuristic note
4. Agents: read Self first, then follow links

## Anti-pattern

Do not promote every lesson immediately. Prefer: Decision lesson → Self proposal → accept → promote later if it compounds.
