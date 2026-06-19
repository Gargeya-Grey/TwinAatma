# 🧠 KnowledgeOS
> Your personal knowledge operating system — an AI-operable Obsidian vault for thinking, learning, startup building, research, decisions, and execution.

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Obsidian](https://img.shields.io/badge/Obsidian-compatible-purple.svg)](https://obsidian.md/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![AI-Ready](https://img.shields.io/badge/AI-Ready-orange.svg)](#-agent-automation-setup-guide)

Designed to work alongside **Notion** (as the execution layer) and **Hermes** (as the AI orchestrator), KnowledgeOS turns a folder of markdown files into a structured, queryable knowledge graph.

---

## 🤖 Agent Automation: Setup Guide
If you are an AI agent (e.g. Claude Code, Cursor, Windsurf, Antigravity) instructed to **"setup <link>"** or initialize this repository, execute the following commands in the workspace root:

```bash
# Step 1: Initialize the SQLite index database
python scripts/rebuild_index.py

# Step 2: Refresh the auto-generated dashboards
python scripts/update_mocs.py

# Step 3: Validate the vault schema health
python scripts/validate_schema.py
```

*Note: No external package installation (pip) is needed. KnowledgeOS runs purely on Python standard libraries.*

---

## 🚀 Quick Start for Humans

| If you want to... | Reference |
|---|---|
| Learn the system from scratch | [[MOCs/_MOC_How_KnowledgeOS_Works\|How KnowledgeOS Works]] |
| See what's active now | [[MOCs/_MOC_Active\|Active Work MOC]] |
| Navigate the master graph | [[MOCs/_MOC_Master\|Master MOC]] |
| Explore note templates | [[Templates/_Index\|Template Index]] |
| View active experiments | [[MOCs/_MOC_Experiments\|Experiments Dashboard]] |

---

## 📐 The Architecture & Layers

```text
  [ Obsidian (Thinking) ] <---> [ Notion (Execution) ]
            ^                           ^
            |                           |
            +-----[ Hermes / AI ]-------+
```

| Layer | System | Role | Primary Query |
|---|---|---|---|
| **Thinking** | Obsidian | Knowledge Graph, Notes, Decisions | *What do I know? How does it connect?* |
| **Execution** | Notion | Relational Databases, Tasks, Pipelines | *What needs to be done, by whom, and when?* |
| **Orchestrator** | Hermes / AI | Automation, Search, Cross-publishing | *How do I automate, retrieve, and scale?* |

---

## 📂 Vault Structure

```text
KnowledgeOS/
├── Inbox/          — Raw captures (unprocessed inputs)
├── Concepts/       — Ideas, principles, mental models
├── Projects/       — Active work streams with concrete outcomes
├── Experiments/    — Hypothesis testing (hypotheses → results)
├── Research/       — Long-form investigations, papers, syntheses
├── Decisions/      — Decision logs (first-class citizens of strategy)
├── People/         — Network database (relationships & roles)
├── MOCs/           — Maps of Content (dynamic navigation hubs)
├── Templates/      — Note blueprints for structured metadata
├── Assets/         — Media, PDFs, and embedded attachments
└── scripts/        — Zero-dependency python scripts
```

---

## ⚙️ Automation Scripts
All scripts are written in standard Python (no `pip install` required) and can be executed via terminal commands:

| Command | Purpose |
|---|---|
| `python scripts/rebuild_index.py` | Scan the vault and rebuild the SQLite index (`knowledge_index.db`). |
| `python scripts/search.py "<query>"` | Graph-aware search (evaluates titles, tags, projects, and links). |
| `python scripts/update_mocs.py` | Rebuild and refresh all dynamic dashboards (e.g. experiments). |
| `python scripts/daily_capture_report.py` | Inspect Inbox folder and suggest next organization steps. |
| `python scripts/refinement_report.py` | Generate a report on notes missing links, tags, or metadata. |
| `python scripts/validate_schema.py` | Validate portable metadata structures, provenance, and link health. |
| `python scripts/draft_weekly_synthesis.py` | Aggregate weekly vault changes and draft a review note. |
| `python scripts/export_bundle.py` | Bundle markdown files and assets for a project. |
| `python scripts/publish_to_notion.py` | Sync and publish refined notes to the Notion wiki. |

---

## 🔄 Operating Cadence

### 📅 Daily Capture & Clarify
1. Capture raw thoughts and inputs into `/Inbox`.
2. Run `python scripts/daily_capture_report.py` to triage.
3. Turn raw ideas into typed notes, establish links, and run `python scripts/rebuild_index.py`.

### 🔁 Weekly Review & Commit
1. Run `python scripts/rebuild_index.py` followed by `python scripts/update_mocs.py`.
2. Draft and complete the weekly synthesis: `python scripts/draft_weekly_synthesis.py`.
3. Check vault health: `python scripts/validate_schema.py`.

### 🗓️ Monthly Review & Archive
1. Instantiate the monthly review template (`Templates/t-monthly-review`).
2. Move completed/stale projects to `Archive/`.
3. Update strategic roadmaps and learning trajectories.

---

## 📬 Notion Publishing Bridge
Only **refined** notes should cross the bridge. A note qualifies as refined when it has a clear purpose, is well-structured, contains backlinks, and has:
```yaml
status: refined
publish_to_notion: true
```
To test publishing:
```bash
python scripts/publish_to_notion.py --dry-run path/to/note.md
```

---

## 📜 Rules of the Road
* **No orphans**: Every note must link to at least one other page (MOC, Project, Decision).
* **Decisions are sacred**: Any major shift in architecture, pivot, or strategy must be documented in `Decisions/`.
* **Projects require actions**: An active project without next actions is dead.
* **Keep it portable**: Stick to the OKF (Open Knowledge Format) YAML frontmatter. Avoid lock-in to proprietary apps.