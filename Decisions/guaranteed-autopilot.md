---
type: decision
title: Guaranteed Autopilot — post-setup twin stays fresh without user ops
description: After first successful setup, autopilot (session breathe + hooks + MCP instructions) keeps the twin up to date, relevant, and evolving; user only answers soft remember-this prompts.
schema: knowledgeos-v0.3
status: active
created: 2026-07-12
updated: 2026-07-12
timestamp: 2026-07-12T00:00:00Z
tags: [decision, knowledgeos, autopilot, mcp, digital-twin]
project: KnowledgeOS
outcome_status: pending
entity_id: kos:decision:guaranteed-autopilot
---

# Guaranteed Autopilot — post-setup twin stays fresh without user ops

## Context

Success metric refined: after one successful setup, the user never thinks about operating KnowledgeOS — they only enjoy an up-to-date, relevant, self-evolving cognitive twin.

P7 added agent contracts and session tools, but freshness (index rebuild), weekly evolution, and host-level enforcement were still hope-based.

## Decision

Ship **P8 Guaranteed Autopilot**:

1. `knowledgeos/autopilot.py` — durable state under `.knowledgeos/`, `ensure_index_fresh`, weekly drift proposal, soft prompts, `breathe`.
2. `memory_session_start` becomes a full breathe (not just context load).
3. MCP `initialize.instructions` embeds the compact agent contract for any host that surfaces it.
4. Cursor `sessionStart` / `sessionEnd` hooks pre-warm breathe and detect orphan sessions.
5. Soft UX: “Want me to remember that?” — never chore lists or script names.

Self.md remains proposal + human confirm (trust).

## Expected outcome

In a wired workspace, every meaningful chat starts with a freshened index and loaded Self; captures and proposals happen without user ops; rare soft yes/no is the only interruption.

## Review after

After real multi-day use: measure how often agents skip `memory_session_start` despite hooks/rules; tighten if needed.
