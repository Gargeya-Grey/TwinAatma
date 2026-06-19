---
type: moc
title: Master Map of Content
description: Map of Content for Master Map of Content.
schema: knowledgeos-v0.2
status: active
tags: [moc, master, navigation]
created: 2026-06-05
updated: 2026-06-18
timestamp: 2026-06-18T00:00:00Z
---
# Master Map of Content

This is the root hub. Every note should be reachable from one of these maps.

## Start Here
- [[../README|System Overview]]
- [[_MOC_How_KnowledgeOS_Works|How KnowledgeOS Works]] — beginner-friendly guide to why it is useful and how to use it
- [[_MOC_Active|Active Work]] — what is happening now
- [[_MOC_KnowledgeOS|KnowledgeOS System]] — how the AI brain operates
- [[_MOC_Execution_System|Execution System]] — Obsidian/Notion/Hermes boundaries & operating cadence

## Domain Hubs
- [[_MOC_Startup|Startup Hub]]
- [[_MOC_Learning|Learning]]
- [[_MOC_Ecosystem|Ecosystem / Cross-Domain Links]]
- [[_MOC_Experiments|Experiments Dashboard]]

## By Type
- Concepts: [[../Concepts/_Index|Concepts Index]]
- Projects: [[../Projects/_Index|Projects Index]]
- Research: [[../Research/_Index|Research Index]]
- Decisions: [[../Decisions/_Index|Decisions Index]]
- People: [[../People/_Index|People Index]]
- Inbox & Meetings: [[../Inbox/_Index|Inbox & Meetings]]
- Templates: [[../Templates/_Index|Template Index]]

## Operating Loop
```text
Capture → Clarify → Connect → Commit → Execute → Review → Synthesize
```

## Automation Commands
| Command | Purpose |
|---|---|
| `python scripts/rebuild_index.py` | Rebuild SQLite index |
| `python scripts/search.py "query"` | Search vault |
| `python scripts/weekly_data.py` | Weekly metrics |
| `python scripts/daily_capture_report.py` | Inbox processing report |
| `python scripts/refinement_report.py` | Refinement candidates |
| `python scripts/update_mocs.py` | Refresh generated dashboards |
| `python scripts/draft_weekly_synthesis.py` | Draft weekly synthesis |

## Quick Links
- Latest Decisions: [[../Decisions/_Index|Decisions Index]]
- Active Projects: [[../Projects/_Index|Projects Index]]
- Open Questions: [[../Research/_Index|Research Index]]
- Weekly Review: [[../Templates/t-weekly-review|Weekly Review Template]]
