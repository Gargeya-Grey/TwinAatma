---
type: project
title: KnowledgeOS
description: Project hub for KnowledgeOS.
schema: knowledgeos-v0.2
status: active
created: 2026-06-18
tags: [knowledgeos, systems, obsidian, hermes]
project: KnowledgeOS
updated: 2026-06-18
timestamp: 2026-06-18T00:00:00Z
---
# KnowledgeOS

## Objective
Turn the current Obsidian/Hermes vault from a scaffold into a living personal operating system for learning, startup planning, research, and productive work.

## Success Criteria
- Daily capture is easy.
- Weekly synthesis produces useful decisions/actions.
- Active projects are visible from one dashboard.
- Notes reliably connect to domains and projects.
- Scripts work without environment-specific CLI dependencies.
- Role boundaries between Obsidian/Notion/Hermes are documented.
- Template library covers startup, learning, execution, and research.

## Current State
The KnowledgeOS has been upgraded through a complete 5-step strategic build:
- Step 1 (Audit) — Found scaffold issues, placeholder indexes, sqlite3 dependency, hardcoded token, missing project layer.
- Step 2 (Design) — Added domain MOCs, operating loop, active projects, README overhaul.
- Step 3 (Templates) — 26 templates across startup, learning, research, execution.
- Step 4 (Automation) — 9 scripts covering index, search, weekly data, capture, refinement, experiments dashboard, drafting, MOC updates.
- Step 5 (Execution System) — Role boundaries document, execution MOC, operating cadence, decision log.

## Related Knowledge
- [[../MOCs/_MOC_KnowledgeOS|KnowledgeOS MOC]]
- [[../MOCs/_MOC_Execution_System|Execution System MOC]]
- [[../README|KnowledgeOS README]]
- [[../MOCs/_MOC_Active|Active Work MOC]]
- [[../Templates/_Index|Template Index]]
- [[../Decisions/obsidian-notion-hermes-role-boundaries|Role Boundaries Decision]]
- [[../Decisions/refinement-bar-for-notion-publishing|Refinement Bar Decision]]

## Next Actions
- Run `python scripts/rebuild_index.py` to index the vault.
- Review [[../MOCs/_MOC_Experiments|Experiments Dashboard]].
- Explore templates in [[../Templates/_Index|Templates Index]] to start creating notes.
