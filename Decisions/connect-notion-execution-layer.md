---
type: decision
title: Connect Notion as the Execution Layer for KnowledgeOS
description: Decision log for Connect Notion as the Execution Layer for KnowledgeOS.
schema: knowledgeos-v0.2
status: active
created: 2026-06-05
updated: 2026-07-12
tags: [notion, integration, knowledgeos, ops]
project: KnowledgeOS
timestamp: 2026-06-18T00:00:00Z
---

# Connect Notion as the Execution Layer for KnowledgeOS

## Context

The [KnowledgeOS](../README.md) was built with three layers: Obsidian (thinking), Notion (execution), and Hermes (orchestrator). Notion was the missing piece — the refined knowledge had no destination. The existing ["Idea Vault & Execution Engine"](../MOCs/_MOC_Master.md) database in Notion already contained the user's strategic goals, projects, and action items. The gap was bridging Obsidian notes → Notion pages automatically.

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

The integration is operational. Credentials are **not stored in the repository**.

- **API Key**: Environment `NOTION_API_KEY`, optional Hermes `~/.hermes/.env`, or `knowledgeos.config.json`
- **Database / data source ID**: Environment `NOTION_DATABASE_ID` / `NOTION_DATA_SOURCE_ID` or `knowledgeos.config.json` (see `knowledgeos.config.example.json`). **No hardcoded DB ID in code.**
- **Properties**: Idea, Category, Status, Priority, Next Action, Deadline, Date Captured, Note Type, Context, Obsidian Link (names configurable via config)

### Scripts
| Script | Purpose |
|---|---|
| `scripts/_notion_env.py` | Load Notion key + DB id from env / config / optional Hermes `.env` |
| `scripts/notion_test.py` | Quick connectivity test — lists accessible pages |
| `scripts/notion_inspect.py` | Inspect database schema + sample entries |
| `scripts/notion_bridge.py` | Setup DB properties + publish single note to Notion |
| `scripts/publish_to_notion.py` | Full pipeline: parse Obsidian frontmatter → publish if `status: refined` and `publish_to_notion: true` |

### Key Design Notes
- Publish gate (`status: refined`, `publish_to_notion: true`) prevents drafts from leaking
- Category / property maps live in `knowledgeos.config.json` (optional overrides)
- Obsidian Link is preserved so each Notion entry points back to its source note
- **Addendum 2026-07-12:** KnowledgeOS MCP (Phase 3) is **in-scope** as the agent memory interface — see [KnowledgeOS MCP Memory Server](knowledgeos-mcp-memory-server.md). Notion MCP remains optional/out-of-scope for execution publishing.

### Next Steps
- Keep Notion fully config-driven (done in P0)
- Consider Notion → Obsidian sync for status updates later
- KnowledgeOS Memory MCP arrives in Phase 3 of the strategic plan