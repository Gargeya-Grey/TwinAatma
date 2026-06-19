---
type: decision
title: Connect Notion as the Execution Layer for KnowledgeOS
description: Decision log for Connect Notion as the Execution Layer for KnowledgeOS.
schema: knowledgeos-v0.2
status: active
created: 2026-06-05
updated: 2026-06-05
tags: [notion, integration, knowledgeos, ops]
project: KnowledgeOS
timestamp: 2026-06-18T00:00:00Z
---

# Connect Notion as the Execution Layer for KnowledgeOS

## Context

The [[README|KnowledgeOS]] was built with three layers: Obsidian (thinking), Notion (execution), and Hermes (orchestrator). Notion was the missing piece — the refined knowledge had no destination. The existing [[../_MOC_Master|"Idea Vault & Execution Engine"]] database in Notion already contained the user's strategic goals, projects, and action items. The gap was bridging Obsidian notes → Notion pages automatically.

## Alternatives Considered

- **Notion MCP Server** — Could connect via MCP protocol. More complex setup, adds a dependency on Node.js/npx at runtime. Overkill for a simple create-page workflow.
- **Manual copy-paste** — No integration at all. Would fail within a week.
- **Make.com / Zapier** — Adds a paid third-party service. Slower, less control, no direct Obsidian link preservation.
- **Direct Notion API via curl/Python** — Chosen. Simple, no extra dependencies, full control over property mapping, preserves Obsidian source links.

## Decision

Connect Notion to KnowledgeOS using the Notion API (REST) via a Python bridge script at `scripts/publish_to_notion.py`. The integration uses the existing "Idea Vault & Execution Engine" database, extended with two new properties: "Obsidian Link" (URL) and "Note Type" (select).

## Reasoning

- The Notion API is mature, well-documented, and free.
- Python has no external dependencies (uses only urllib) — runs anywhere.
- Property mapping from Obsidian frontmatter to Notion columns is straightforward.
- The publish gate (`status: refined, publish_to_notion: true`) prevents raw or draft content from leaking into Notion.
- Category mapping from tags gives automatic organization without manual sorting.
- The Obsidian Link property preserves provenance — you can always go back to the source note.

## Expected Outcome

- Refined KnowledgeOS notes automatically flow into the "Idea Vault & Execution Engine" for execution.
- Category mapping keeps Notion organized without manual tagging.
- The publish gate prevents noise — only notes with `status: refined` and `publish_to_notion: true` get published.
- The weekly synthesis can flag notes ready for publishing.

## Actual Outcome

The integration is fully operational as of 2026-06-18:

- **API Key**: Stored in Hermes `.env` at `~/.hermes/.env` as `NOTION_API_KEY`
- **Database**: "🧠 Idea Vault & Execution Engine" (ID: `42e1f487-0860-4366-b795-7a19c7b3bc8f`) — fully accessible via API
- **19 entries** with columns: Idea, Category, Status, Priority, Next Action, Deadline, Date Captured, Note Type, Context, Obsidian Link
- **Properties added**: `Obsidian Link` (URL) and `Note Type` (select) — both present in the database

### Scripts
| Script | Purpose |
|---|---|
| `scripts/_notion_env.py` | Shared helper — auto-loads `NOTION_API_KEY` from Hermes `.env` |
| `scripts/notion_test.py` | Quick connectivity test — lists accessible pages |
| `scripts/notion_inspect.py` | Inspect database schema + sample entries |
| `scripts/notion_bridge.py` | Setup DB properties + publish single note to Notion |
| `scripts/publish_to_notion.py` | Full pipeline: parse Obsidian frontmatter → publish to Notion if `status: refined` and `publish_to_notion: true` |

### Key Design Notes
- All scripts auto-load the env var from Hermes' `.env` file via `_notion_env.py` — no manual `export` needed
- The publish gate (`status: refined, publish_to_notion: true`) prevents drafts from leaking
- Category mapping is tag-based (e.g. `ai` → `AI/Agents`, `gtm` → `GTM`, `product` → `Platform`)
- Obsidian Link is preserved so each Notion entry points back to its source note

### Next Steps
- Add a `--all` cron job to auto-publish refined notes weekly
- Consider Notion → Obsidian sync for status updates (Notion as execution, Obsidian as source of truth)