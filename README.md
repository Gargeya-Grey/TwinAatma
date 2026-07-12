<p align="center">
  <img src="docs/brand/twinaatma-header.gif" alt="TwinAatma — pixel art brain among galaxies, your cognitive twin" width="720" />
</p>

<h1 align="center">TwinAatma</h1>

<p align="center">
  <strong>The twin of your Self</strong> — private cognitive memory any AI can load, that stays current as you live.
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.9%2B-blue.svg" alt="Python 3.9+" /></a>
  <a href="https://obsidian.md/"><img src="https://img.shields.io/badge/Obsidian-compatible-purple.svg" alt="Obsidian compatible" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License" /></a>
  <a href="#-one-time-setup-wire-mcp"><img src="https://img.shields.io/badge/AI-Ready-orange.svg" alt="AI Ready" /></a>
</p>

**Public name:** TwinAatma *(Twin-AAT-maa — twin + aatma, self/soul)*  
**Technical toolkit:** `knowledgeos` (package, CLI, schema ids — unchanged for now)

**Your job:** wire the MCP Memory server once.  
**The agent's job:** load your Self, search memory, capture what matters, propose twin updates, and ask only for high-leverage yes/no. See [AGENTS.md](AGENTS.md).

Not another PKM theme pack. TwinAatma is **local-first cognitive memory**: OKF-aligned markdown you own, an MCP Memory API any agent can call, and a Self-model updated through decision outcomes (never silent rewrites).

Obsidian is recommended for humans. Notion and Hermes are optional. Brand decision: [Public brand is TwinAatma](Decisions/public-brand-twinaatma.md). Roadmap: [Strategic Implementation Plan v1](Decisions/strategic-implementation-plan-v1.md).

> **Name notes:**  
> - **TwinAatma** is this repo’s public brand (personal cognitive twin). Not affiliated with other Atma/ATMA products.  
> - **KnowledgeOS** may still appear in paths, CLI (`python -m knowledgeos`), and schema ids — legacy technical name.

---

## 🔌 One-time setup: wire MCP

```bash
python -m knowledgeos mcp
```

Cursor example: [`mcp.cursor.example.json`](mcp.cursor.example.json)

```json
{
  "mcpServers": {
    "knowledgeos": {
      "command": "python",
      "args": ["-m", "knowledgeos", "mcp"],
      "cwd": "W:/AI-Projects/TwinAatma",
      "env": { "KNOWLEDGEOS_VAULT": "W:/AI-Projects/TwinAatma" }
    }
  }
}
```

After that, **just chat**. Autopilot keeps the twin fresh:

| Ritual | What happens |
|---|---|
| Chat starts (Cursor hook + agent) | Index refreshed if stale; Self + relevant memory loaded |
| During chat | Captures + search without you managing folders |
| Preference change | Soft “Want me to remember that?” → yes/no |
| Chat ends usefully | Session summary saved; index freshened |
| ~Weekly | Drift proposal drafted for your yes/no |

Agents follow `AGENTS.md` / `.cursor/rules` / MCP `instructions`. You should not manage indexes, scripts, or cadences after setup.

---

## 🤖 Agent Automation: Setup Guide
If you are an AI agent (e.g. Claude Code, Cursor, Windsurf) instructed to **"setup <link>"** or initialize this repository, execute the following commands in the workspace root:

```bash
python scripts/doctor.py
python scripts/rebuild_index.py
python scripts/update_mocs.py
python scripts/validate_schema.py
python scripts/setup_git_hooks.py
```

*Note: Core KnowledgeOS uses Python 3.9+ standard library only (no pip). Notion is optional.*

CLI fallback (same tools, no MCP host needed — for debugging only):

```bash
python -m knowledgeos memory list
python -m knowledgeos memory memory_session_start --task-hint "ship MCP"
python -m knowledgeos memory memory_ops_status
```

Self writes are **proposal-only** until you say yes in chat (or via accept tool):

```bash
python -m knowledgeos memory memory_propose_self_update --summary "..." --section heuristics --proposed-markdown "..."
python -m knowledgeos memory memory_accept_self_update --path People/Self-Proposals/...
```

### Outcome → Self loop (agent-owned)

Agents use MCP (`memory_propose_from_lesson`, `memory_propose_from_drift`, accept/reject). Power users can still call scripts; normal operation should not require it.

```bash
python scripts/check_alignment.py
python scripts/update_mocs.py
python scripts/propose_self_update.py from-lesson Decisions/your-decision.md
```

```bash
python -m knowledgeos init ./my-brain --name "Your Name" --non-interactive
cd ./my-brain
python scripts/rebuild_index.py
python scripts/validate_schema.py
python -m knowledgeos self summary
```

Assign stable entity IDs (dry-run by default):

```bash
python -m knowledgeos ids assign
python -m knowledgeos ids assign --write
```

---

## ⚙️ Installation & Manual Setup Guide

1. **Obsidian Vault Setup** (recommended, not required for agents):
   - Install [Obsidian](https://obsidian.md/) and open this directory as a vault.
2. **Initialize Search Database**:
   - Ensure **Python 3.9+** is installed.
   - Run:
     ```bash
     python scripts/rebuild_index.py
     ```
3. **Configure Your Ego Node (Self-Model)**:
   ```bash
   python scripts/onboarding.py
   ```
   Generates [People/Self.md](People/Self.md).
4. **Optional Notion Sync & Git Hooks**:
   - Copy `knowledgeos.config.example.json` → `knowledgeos.config.json` and fill Notion fields, **or** set:
     ```env
     NOTION_API_KEY=your_secret_api_key_here
     NOTION_DATABASE_ID=your_database_or_data_source_id_here
     ```
   - Hermes `~/.hermes/.env` is also supported if you use Hermes.
   - Set up the pre-commit validation hook:
     ```bash
     python scripts/setup_git_hooks.py
     ```
5. **Run System Checks**:
   - `python scripts/doctor.py`
   - `python scripts/check_alignment.py`
   - `python scripts/semantic_drift.py` *(requires git history)*

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
All core scripts use the Python standard library (no `pip install` required):

| Command | Purpose |
|---|---|
| `python scripts/doctor.py` | Environment and vault health diagnostics. |
| `python scripts/onboarding.py` | Interactive Ego Node wizard → `People/Self.md`. |
| `python scripts/rebuild_index.py` | Rebuild SQLite index (`knowledge_index.db`). |
| `python scripts/search.py "<query>"` | Blended metadata + FTS5 body search (ranked). |
| `python scripts/intelligence_brief.py` | Weekly intelligence brief (decisions, drift, gaps, tensions). |
| `python scripts/learning_trajectory.py` | “How my thinking changed” trajectory report. |
| `python scripts/update_mocs.py` | Refresh generated dashboards (experiments, outcomes, orphans, themes, …). |
| `python scripts/experiment_dashboard.py` | Regenerate Experiments MOC. |
| `python scripts/daily_capture_report.py` | Inbox triage report. |
| `python scripts/refinement_report.py` | Notes needing cleanup / publish readiness. |
| `python scripts/validate_schema.py` | Validate frontmatter + link health. |
| `python scripts/check_alignment.py` | Orphan decisions / stale project checks. |
| `python scripts/semantic_drift.py` | Git-based focus drift report (30 days). |
| `python scripts/weekly_data.py` | Weekly vault metrics (JSON). |
| `python scripts/setup_git_hooks.py` | Install pre-commit schema validation hook. |
| `python scripts/refactor_links.py` | Fix broken paths; migrate wikilinks → markdown links. |
| `python scripts/draft_weekly_synthesis.py` | Draft weekly synthesis note. |
| `python scripts/export_bundle.py` | Export portable markdown bundle + manifest. |
| `python scripts/smoke_test.py` | Quick smoke test for parser, Self sections, index columns. |
| `python -m knowledgeos init <path>` | Create a clean starter vault. |
| `python -m knowledgeos ids assign` | Dry-run assign `kos:<type>:<slug>` IDs. |
| `python -m knowledgeos self summary` | Parse Ego Node sections as JSON. |
| `python scripts/publish_to_notion.py` | Publish refined notes to Notion (optional). |
| `python scripts/notion_test.py` | Test Notion API connectivity. |
| `python scripts/notion_inspect.py` | Inspect Notion data source schema. |
| `python scripts/notion_bridge.py` | Notion DB property setup / single-note bridge helpers. |

## 📬 Notion Publishing Bridge
Only **refined** notes should cross the bridge:
```yaml
status: refined
publish_to_notion: true
```
Configure via `knowledgeos.config.json` (see `knowledgeos.config.example.json`) or environment variables. There is **no hardcoded database ID** in the repo.

```bash
python scripts/publish_to_notion.py --dry-run path/to/note.md
python scripts/publish_to_notion.py --dry-run --all
```

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

## 📜 Rules of the Road
* **No orphans**: Every note must link to at least one other page (MOC, Project, Decision).
* **Decisions are sacred**: Any major shift in architecture, pivot, or strategy must be documented in `Decisions/`.
* **Projects require actions**: An active project without next actions is dead.
* **Keep it portable**: Stick to the OKF (Open Knowledge Format) YAML frontmatter. Avoid lock-in to proprietary apps.