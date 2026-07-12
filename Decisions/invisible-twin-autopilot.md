---
type: decision
title: Invisible Twin Autopilot — agent owns ops after MCP wire
description: User wires MCP once; AGENTS.md + Cursor rules + session rituals make the agent keep the digital twin current without user choreography.
schema: knowledgeos-v0.3
status: active
created: 2026-07-12
updated: 2026-07-12
timestamp: 2026-07-12T00:00:00Z
tags: [decision, knowledgeos, mcp, agents, digital-twin, friction]
project: KnowledgeOS
outcome_status: pending
entity_id: kos:decision:invisible-twin-autopilot
---

# Invisible Twin Autopilot — agent owns ops after MCP wire

## Context

P0–P6 shipped the engine (SDK, init, MCP Memory, Self evolution, FTS, hardening). Adversarial gap: users still had to remember when to load Self, capture, review outcomes, or run scripts. That violates the success metric.

User clarified: **wiring MCP once is acceptable friction**. After that, the intelligent agent must decide everything so there is no ongoing operational burden.

## Decision

Ship an **Invisible Twin Operating Contract**:

1. Root [`AGENTS.md`](../AGENTS.md) — mandatory agent protocol (when to call which tools).
2. Cursor always-on rule [`.cursor/rules/knowledgeos-twin.mdc`](../.cursor/rules/knowledgeos-twin.mdc).
3. Composite MCP tools so agents need fewer decisions:
   - `memory_session_start` — bootstrap + ops status
   - `memory_session_end` — optional capture + remaining twin questions
   - `memory_ops_status` — plain-language hygiene for the agent (not a user chore list)
4. `init` copies AGENTS.md, Cursor rules, and MCP example into new vaults.
5. README promise: wire once → just chat.

Human confirm for Self mutations remains non-negotiable (proposal → yes/no in chat).

## Alternatives considered

1. **More docs / checklists for humans** — Rejected. Creates friction; fails the success metric.
2. **Cron / scheduled scripts as primary loop** — Deferred. Useful later; agent-in-the-loop is the wedge.
3. **Silent auto-edit of Self.md** — Rejected. Trust-breaking.
4. **This contract + session rituals** — Chosen.

## Expected outcome

With MCP wired, a capable agent loads memory at session start, captures mid-chat, proposes Self updates when beliefs change, and only asks plain-language confirmations. Users do not need to remember KnowledgeOS commands for the twin to stay useful.

## Review after

After 1–2 weeks of real Cursor chats with MCP enabled: if agents still skip `memory_session_start`, tighten tool descriptions / host prompts further.
