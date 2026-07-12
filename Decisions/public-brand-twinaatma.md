---
type: decision
title: Public brand is TwinAatma — internals stay knowledgeos
description: Adopt TwinAatma as the human-facing product name (twin of the Self/soul); keep package paths, kos: IDs, schema versions, and MCP module ids stable until a later versioned migration.
schema: knowledgeos-v0.3
status: active
created: 2026-07-12
updated: 2026-07-12
timestamp: 2026-07-12T00:00:00Z
tags: [decision, branding, twinaatma, knowledgeos]
project: KnowledgeOS
outcome_status: pending
entity_id: kos:decision:public-brand-twinaatma
---

# Public brand is TwinAatma — internals stay knowledgeos

## Context

“KnowledgeOS” undersells the product and collides with other products. After name brainstorming (CogniTwin, Yaad, SelfDojo, Aatma), **TwinAatma** won: English *twin* + Hindi/Sanskrit *aatma* (self/soul).

## Decision

1. **Public brand:** TwinAatma (prefer this spelling; avoid collapsing to bare “Atma” in public copy).  
2. **Pronunciation:** Twin-AAT-maa.  
3. **Tagline:** TwinAatma — the twin of your Self. Private cognitive memory any AI can load, that stays current as you live.  
4. **Internals unchanged for now:** `knowledgeos` package, `python -m knowledgeos`, `kos:` entity IDs, `knowledgeos-v0.x` schema, MCP server / `KNOWLEDGEOS_VAULT`.  
5. **Docs:** README and user-facing copy lead with TwinAatma; KnowledgeOS only as legacy/technical name where needed.  
6. **Later (optional):** versioned package rename when brand has stuck.

## Alternatives considered

- Yaad — beautiful; fatal collision with MCP memory projects + yaad.one PKM.  
- CogniTwin / Aatma alone — meaning good; crowded neighboring brands.  
- SelfDojo — freer name; wrong metaphor (gym vs twin).  
- TwinAatma — chosen.

## Name notes

Unaffiliated with Atma.ai wellness apps, ATMA AI agencies, or other Atma/ATMA products. Always brand as **TwinAatma**.

## Expected outcome

New users hear TwinAatma. Agents/devs still use `knowledgeos` tools without a breaking migration.
