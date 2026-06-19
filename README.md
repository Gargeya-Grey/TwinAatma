---
type: index
title: KnowledgeOS
description: Index and operating rules for KnowledgeOS.
schema: knowledgeos-v0.2
status: active
tags: [knowledgeos, readme, system]
created: 2026-06-05
updated: 2026-06-18
timestamp: 2026-06-18T00:00:00Z
---
# KnowledgeOS

Your personal knowledge operating system — an AI-operable Obsidian vault for
thinking, learning, startup building, research, decisions, and execution.
Designed to work alongside **Notion** (execution layer) and **Hermes** (AI
orchestrator).

## What This Is

A living second brain organized around an operating loop:

```text
Capture → Clarify → Connect → Commit → Execute → Review → Synthesize
```

Every note has a **type** (concept, project, decision, experiment, synthesis, …)
and lives in a purpose-built folder. Maps of Content (MOCs) provide navigation
instead of folders alone. Automation scripts keep the graph searchable and the
cadence alive.

If you are new to the system, start with [[MOCs/_MOC_How_KnowledgeOS_Works|How KnowledgeOS Works]]. It explains the system in plain language: why it is useful, how information moves through it, and how to use it daily/weekly/monthly.

## Setup & Installation

KnowledgeOS is designed to run with minimal external dependencies. 

1. **Obsidian Setup**:
   - Open this directory as a vault in Obsidian.
2. **Python Environment**:
   - Ensure Python 3.x is installed. No external packages are required (only standard libraries are used).
3. **Database Initialization**:
   - Run `python scripts/rebuild_index.py` from the root of the vault. This creates `knowledge_index.db` and indexes all existing notes, frontmatter, and wiki links.
4. **Notion Integration (Optional)**:
   - To publish refined notes to Notion, set the following environment variables or place them in a `.env` file at `~/.hermes/.env` or your OS local appdata folder (e.g. `%LOCALAPPDATA%/hermes/.env`):
     - `NOTION_API_KEY`: Your Notion integration API key.
     - `NOTION_DATA_SOURCE_ID` or `NOTION_DATABASE_ID`: The ID of your Notion wiki or database.

---

## AI Agent Guide (How to Operate This Vault)

If you are an AI assistant (like Claude Code, Cursor, Windsurf, or Antigravity) pair programming in this vault, please follow these operating principles:

1. **Understand the Structure**: Start by reading the Master MOC in [[MOCs/_MOC_Master|MOCs/_MOC_Master.md]] and [[MOCs/_MOC_How_KnowledgeOS_Works|How KnowledgeOS Works]] to navigate.
2. **Use SQL Search**: The vault is indexed in a SQLite database (`knowledge_index.db`). You can run `python scripts/search.py "<query>"` to perform a search that respects links, tags, and note relationships.
3. **Maintain the Index**: Whenever you create, modify, or delete a markdown note, run `python scripts/rebuild_index.py` to refresh the SQLite database.
4. **Enforce Note Schemas**: Every content note must start with a YAML frontmatter block conforming to the schema in `README.md` (type, title, description, status, schema, created, updated, timestamp, tags).
5. **Use Templates**: When creating a new note, read and clone the corresponding template from `Templates/` (e.g., `Templates/t-project.md` for new projects).
6. **Enforce Backlinks**: Do not create orphan notes. Ensure every new note links to at least one MOC, project, concept, or parent note.

---

## Quick Start

| If you want to… | Go here |
|---|---|
| Learn the system from scratch | [[MOCs/_MOC_How_KnowledgeOS_Works\|How KnowledgeOS Works]] |
| See what I'm working on now | [[MOCs/_MOC_Active\|Active Work MOC]] |
| Understand the full navigation map | [[MOCs/_MOC_Master\|Master MOC]] |
| Browse startup product thinking | [[MOCs/_MOC_Startup\|Startup MOC]] |
| Explore the template library | [[Templates/_Index\|Template Index]] |
| See active experiments | [[MOCs/_MOC_Experiments\|Experiments Dashboard]] |
| Read an example weekly synthesis | [[Research/Synthesis/example-synthesis\|Example Synthesis]] |
| Learn about tool boundaries | [[MOCs/_MOC_Execution_System\|Execution System MOC]] |
| Understand the portable schema | [[Research/knowledgeos-portable-schema\|KnowledgeOS Portable Schema]] |

## The Layers

| Layer | Role | Answers |
|---|---|---|
| **Obsidian** | Thinking & knowledge graph | *What do I know? What connects to what?* |
| **Notion** | Execution & operational database | *Who does what, by when, in what state?* |
| **Hermes** | AI orchestrator | *How do I find, connect, and transform?* |
| **Tasks** | Notion or dedicated task system | *What gets done?* |

Full boundary definitions: [[MOCs/_MOC_Execution_System|Execution System MOC]].

## Vault Structure

```text
KnowledgeOS/
├── Inbox/          — Raw captures (unprocessed)
├── Concepts/       — Ideas, principles, mental models
├── Projects/       — Active work streams  → [[Projects/_Index]]
├── Experiments/    — Active experiments (hypothesis → results)
├── Research/       — Investigations, syntheses
├── Decisions/      — Decision logs (first-class citizens)  → [[Decisions/_Index]]
├── People/         — People notes
├── MOCs/           — Maps of Content (navigation hubs)  → [[MOCs/_MOC_Master]]
├── Templates/      — Note templates  → [[Templates/_Index]]
├── Assets/         — PDFs, images, files
├── Archive/        — Inactive or completed work
└── scripts/        — Automation scripts
```

## Note Types

| Type | Use Case |
|---|---|
| **concept** | Ideas, principles, mental models |
| **project** | Active work with outcomes and next actions |
| **research** | Questions, investigations, findings |
| **decision** | Significant choices with context and reasoning |
| **experiment** | Hypotheses, methods, results |
| **synthesis** | Pattern discovery, weekly reviews |
| **meeting** | Notes, decisions, action items |
| **person** | People, roles, relationships |
| **moc** | Navigation hub (Map of Content) |
| **index** | Folder-level listing and rules |

## Automation Scripts

All scripts live in `scripts/`. Prefer `.py` versions (no external CLI
dependencies beyond Python stdlib).

| Command | Purpose |
|---|---|
| `python scripts/rebuild_index.py` | Refresh SQLite index after adding/changing notes |
| `python scripts/search.py "query"` | Graph-aware search (titles → tags → projects → linked notes) |
| `python scripts/weekly_data.py` | JSON summary for weekly review |
| `python scripts/daily_capture_report.py` | Inspect Inbox and suggest processing |
| `python scripts/refinement_report.py` | Find notes needing links, placeholders, or refinement |
| `python scripts/experiment_dashboard.py` | Generate `MOCs/_MOC_Experiments.md` |
| `python scripts/update_mocs.py` | Refresh all auto-generated dashboards |
| `python scripts/draft_weekly_synthesis.py` | Draft a weekly synthesis from recent activity |
| `python scripts/validate_schema.py` | Validate portable metadata, provenance, and link health |
| `python scripts/export_bundle.py --project "Example Project" --out exports/example-bundle` | Export a portable markdown bundle plus manifest |
| `python scripts/publish_to_notion.py` | Dry-run or publish a refined note to Notion |

Rebuild and search at the command line:

```bash
python scripts/rebuild_index.py
python scripts/search.py "knowledgeos"
```

## Operating Cadence

### Daily
1. Capture raw ideas into the Inbox.
2. `python scripts/daily_capture_report.py`
3. Process urgent captures into typed, linked notes.
4. `python scripts/rebuild_index.py` if notes changed.

### Weekly
1. `python scripts/rebuild_index.py && python scripts/update_mocs.py`
2. `python scripts/draft_weekly_synthesis.py` — then complete the draft.
3. `python scripts/refinement_report.py` — decide what to publish or refine.
4. `python scripts/validate_schema.py` — catch missing metadata/provenance before exporting or publishing.
5. Review active projects and experiments; update next actions.

### Monthly
1. [[Templates/t-monthly-review|Monthly Review]]
2. Archive stale projects.
3. Update the startup/product thesis.
4. Review the learning roadmap.

## Publishing to Notion

Only refined notes should cross the bridge. A note qualifies as `refined` when
it has:

- a clear purpose or question
- substantive content (not a skeleton)
- at least one link to a project, MOC, concept, decision, or source
- explicit implications, next actions, or decisions (when applicable)
- wording stable enough to be useful beyond the moment

```yaml
status: refined
publish_to_notion: true
```

Always dry-run first:

```bash
python scripts/publish_to_notion.py --dry-run path/to/note.md
```

## Rules of the Road

- **MOCs are primary navigation.** Start from `MOCs/_MOC_Master.md`.
- **Backlinks are mandatory.** Every non-index note must link to at least one
  existing note, MOC, project, decision, or experiment.
- **Decisions are first-class.** Log choices that shift strategy, architecture,
  priority, scope, money, or time.
- **Projects need next actions.** A project without a next action is dead in
  the water.
- **Startup claims need evidence.** Positioning, customer assumptions, and
  pilot claims must link to source notes, conversations, experiments, or public
  artifacts.
- **Synthesize weekly.** This keeps the system alive and stops knowledge from
  going cold.
- **No vector database by default.** This system uses graph-first retrieval via
  SQLite + search scripts.

## Portable Metadata Schema

KnowledgeOS follows an OKF-inspired convention: the durable system is the folder of markdown files, not any one app or database. New content notes should include:

```yaml
type: research
title: Human-readable title
description: One-sentence summary
status: active
schema: knowledgeos-v0.2
created: YYYY-MM-DD
updated: YYYY-MM-DD
timestamp: YYYY-MM-DDT00:00:00Z
resource: https://canonical-source-if-any
tags: [domain, topic]
project: Optional Project
```

See [[Research/knowledgeos-portable-schema|KnowledgeOS Portable Schema]] and [[Decisions/okf-inspired-portable-knowledge-schema|OKF-Inspired Portable Knowledge Schema]].

## Database

A SQLite index (`knowledge_index.db`) powers search and weekly reports.

```sql
notes    — title, path, type, tags, project, status, dates
links    — source → destination (+ raw wikilink target)
metadata — system metadata
```

## Git

The vault is version-controlled. Commit after:

- weekly synthesis
- structural changes
- template updates
- major content additions

---

**This is an active operating system, not a static archive.**
It evolves as you learn, build, ship, and reflect.