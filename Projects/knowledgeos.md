---
type: project
title: TwinAatma (KnowledgeOS toolkit)
description: Project hub for TwinAatma — public brand for the personal cognitive twin; technical toolkit remains knowledgeos.
schema: knowledgeos-v0.3
status: active
created: 2026-06-18
tags: [twinaatma, knowledgeos, systems, obsidian, hermes, mcp, roadmap]
project: KnowledgeOS
updated: 2026-07-12
timestamp: 2026-07-12T00:00:00Z
---
# TwinAatma

Public brand for this vault’s cognitive twin *(Twin-AAT-maa)*. Technical CLI/package: `knowledgeos`. See [Public brand is TwinAatma](../Decisions/public-brand-twinaatma.md).

## Objective
Become a plug-and-play subconscious / long-term memory system: OKF-aligned portable knowledge that any AI can load and update, with a Self-model that compounds into the closest digital representation of the user over time.

## Success Criteria
- Init + onboarding stands up a clean vault in ≤10 minutes.
- MCP Memory API works across AI clients (Self, search, capture, propose updates).
- Decision→outcome→lesson→Self proposal loop is operational.
- Markdown remains canonical; indexes/Notion/MCP are derived.
- Shared SDK/parser; schema validated; no founder secrets in toolkit.
- Role boundaries: Obsidian thinking, optional Notion execution, agents via MCP/CLI.

## Current State
- **Public brand:** TwinAatma (2026-07-12). Internals still `knowledgeos`.
- **Roadmap P0–P8: closed (2026-07-12).** After setup, autopilot (`breathe` / session hooks) keeps the twin fresh. Optional polish: screenshots, GitHub Actions CI, bulk `ids assign --write`.
- Living ops: MCP Memory autopilot (`memory_session_start` freshen + soft prompts), outcome→Self proposals, FTS search, intelligence briefs.

## Next Actions
- Point Cursor at `mcp.cursor.example.json` and use the vault daily.
- Weekly: Outcomes Dashboard + soft Self proposals (agent-owned).
- Optional: `python -m knowledgeos ids assign --write`
