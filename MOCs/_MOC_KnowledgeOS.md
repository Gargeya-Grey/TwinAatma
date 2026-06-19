---
type: moc
title: KnowledgeOS MOC
description: Map of Content for KnowledgeOS MOC.
schema: knowledgeos-v0.2
status: active
tags: [moc, knowledgeos, systems, second-brain]
created: 2026-06-18
updated: 2026-06-18
timestamp: 2026-06-18T00:00:00Z
---
# KnowledgeOS MOC

System hub for the AI brain itself.

## System Philosophy
- [[../README|KnowledgeOS README]]
- [[_MOC_How_KnowledgeOS_Works|How KnowledgeOS Works]]
- [[_MOC_Execution_System|Execution System MOC]]
- [[../Decisions/obsidian-notion-hermes-role-boundaries|Role Boundaries Decision]]
- [[../Research/knowledgeos-portable-schema|KnowledgeOS Portable Schema]]
- [[../Decisions/okf-inspired-portable-knowledge-schema|OKF-Inspired Portable Knowledge Schema]]
- Obsidian = thinking
- Notion = execution
- Hermes = orchestration

## Operating Loop
```text
Capture → Clarify → Connect → Commit → Execute → Review → Synthesize
```

## Core Layers
- Capture: [[../Inbox/_Index|Inbox]]
- Concepts: [[../Concepts/_Index|Concepts Index]]
- Research: [[../Research/_Index|Research Index]]
- Projects: [[../Projects/_Index|Projects Index]]
- Decisions: [[../Decisions/_Index|Decisions Index]]
- People: [[../People/_Index|People Index]]
- Templates: [[../Templates/_Index|Template Index]]
- Syntheses: [[../Research/Synthesis/2026-06-18-weekly-draft|Weekly Syntheses]]

## Dashboards
- Active: [[_MOC_Active|Active Work MOC]]
- Experiments: [[_MOC_Experiments|Experiments Dashboard]]
- Startup: [[_MOC_Startup|Startup MOC]]
- Learning: [[_MOC_Learning|Learning MOC]]
- Ecosystem: [[_MOC_Ecosystem|Ecosystem MOC]]

## Automation
| Script | Purpose |
|---|---|
| `python scripts/rebuild_index.py` | Refresh SQLite index |
| `python scripts/search.py <query>` | Search notes/tags/projects/links |
| `python scripts/weekly_data.py` | JSON weekly summary |
| `python scripts/daily_capture_report.py` | Inspect inbox |
| `python scripts/refinement_report.py` | Find refinement candidates |
| `python scripts/experiment_dashboard.py` | Generate `_MOC_Experiments.md` |
| `python scripts/update_mocs.py` | Refresh all generated dashboards |
| `python scripts/draft_weekly_synthesis.py` | Draft weekly synthesis note |
| `python scripts/validate_schema.py` | Validate metadata/provenance/link health |
| `python scripts/export_bundle.py --project "Example Project" --out exports/example-bundle` | Export portable markdown bundle |
| `python scripts/publish_to_notion.py --dry-run <note>` | Dry-run/publish to Notion |

## Maintenance Rules
- Every non-index note should link to at least one MOC, project, concept, or decision.
- Project notes should contain explicit next actions.
- Decisions should be logged when they change direction, scope, priority, or resource allocation.
- Weekly synthesis should identify stale projects, missing links, and next domains to populate.
