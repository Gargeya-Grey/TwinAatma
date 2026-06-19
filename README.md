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

## ⚙️ Installation & Manual Setup Guide

To get KnowledgeOS running, perform the following manual steps:

1. **Obsidian Vault Setup**:
   - Download and install [Obsidian](https://obsidian.md/).
   - Open this directory as a new vault in Obsidian.
2. **Initialize Search Database**:
   - Ensure Python 3.8+ is installed.
   - Run the index builder command in your terminal to initialize your local search database (`knowledge_index.db`):
     ```bash
     python scripts/rebuild_index.py
     ```
3. **Configure Your Ego Node (Self-Model)**:
   - Run the cognitive onboarding wizard in your terminal:
     ```bash
     python scripts/onboarding.py
     ```
   - This interactive CLI wizard will capture your heuristics, core values, and anti-goals to automatically generate your baseline profile at [People/Self.md](People/Self.md). You can also edit this file manually.
4. **Environment Configuration (Optional Notion Sync)**:
   - If you want to use the Notion publishing bridge, create a `.env` file at `~/.hermes/.env` (on Unix/macOS) or in your `%LOCALAPPDATA%/hermes/.env` folder (on Windows) and add your integration details:
     ```env
     NOTION_API_KEY=your_secret_api_key_here
     NOTION_DATABASE_ID=your_database_or_wiki_id_here
     ```
5. **Run System Checks**:
   - Run the alignment diagnostic tool: `python scripts/check_alignment.py`
   - Run the focus analyzer: `python scripts/semantic_drift.py` *(requires at least one Git commit in the vault).*

---

## 🚀 Quick Start for Humans

| If you want to... | Reference |
|---|---|
| Learn the system from scratch | [How KnowledgeOS Works](MOCs/_MOC_How_KnowledgeOS_Works.md) |
| See what's active now | [Active Work MOC](MOCs/_MOC_Active.md) |
| Navigate the master graph | [Master MOC](MOCs/_MOC_Master.md) |
| Explore note templates | [Template Index](Templates/_Index.md) |
| View active experiments | [Experiments Dashboard](MOCs/_MOC_Experiments.md) |

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