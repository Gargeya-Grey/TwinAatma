---
type: moc
title: How KnowledgeOS Works
description: Beginner-friendly explanation of why KnowledgeOS is useful, how it works, and how to use it day to day.
schema: knowledgeos-v0.2
status: active
tags: [knowledgeos, onboarding, guide, second-brain]
created: 2026-06-18
updated: 2026-06-18
timestamp: 2026-06-18T00:00:00Z
project: KnowledgeOS
---
# How KnowledgeOS Works

This note explains KnowledgeOS as if you are seeing it for the first time.

## One-Line Summary
KnowledgeOS is a personal operating system for your thinking: it captures ideas, organizes them into typed notes, connects them through links, turns them into decisions/projects/experiments, and uses Hermes automation to keep the system searchable and alive.

## Why It Is Good

### 1. It turns scattered thoughts into a usable brain
Instead of keeping ideas in memory, browser tabs, chats, random docs, or vague plans, KnowledgeOS gives each piece of thinking a place:

| Kind of thought | Where it goes |
|---|---|
| Raw idea | [[../Inbox/_Index|Inbox]] |
| Reusable idea or mental model | [[../Concepts/_Index|Concepts]] |
| Startup/product work | [[../Projects/_Index|Projects]] and [[_MOC_Startup|Startup MOC]] |
| Research or article notes | [[../Research/_Index|Research]] |
| Important choice | [[../Decisions/_Index|Decisions]] |
| Hypothesis to test | [[_MOC_Experiments|Experiments Dashboard]] |
| Weekly reflection | [[../Research/Synthesis/2026-06-18-weekly-draft|Weekly Synthesis]] |

### 2. It is not locked into one app
The durable source of truth is plain markdown files with YAML frontmatter. Obsidian is the editor, but the knowledge itself is portable.

This is why the system follows the [[../Research/knowledgeos-portable-schema|KnowledgeOS Portable Schema]].

### 3. It supports both human navigation and AI use
Humans use MOCs and links. Hermes uses frontmatter, search, SQLite indexing, validation scripts, and export scripts.

That means the same notes can be:
- read naturally by you
- searched by scripts
- summarized by Hermes
- exported as bundles
- published to Notion when refined

### 4. It connects knowledge to execution
The system does not stop at note-taking. It has a path from thinking to action:

```text
Idea → Note → Link → Decision → Project/Experiment → Execution → Review → Synthesis
```

### 5. It is especially useful for Venture Building
For any project or startup, KnowledgeOS supports:
- product thesis
- customer discovery
- assumption mapping
- experiments
- website positioning
- pilot planning
- decisions
- research synthesis

## The Core Idea

Most note systems become dumping grounds. KnowledgeOS is designed to become an operating loop:

```text
Capture → Clarify → Connect → Commit → Execute → Review → Synthesize
```

| Stage | Meaning | Example |
|---|---|---|
| Capture | Get the raw thought out of your head | Put an idea into Inbox |
| Clarify | Turn raw input into a typed note | Convert it into a project/research/concept note |
| Connect | Link it to relevant projects/MOCs/decisions | Link a startup research note to Startup MOC |
| Commit | Decide what matters | Create a decision note or next action |
| Execute | Run the work outside the vault | Use Notion/tasks/customer calls/building |
| Review | Check what changed | Weekly review and experiment dashboard |
| Synthesize | Extract patterns and decisions | Weekly synthesis note |

## The Main Parts

### 1. MOCs — Maps of Content
MOC means **Map of Content**.

A MOC is a curated navigation hub. It is not just a folder index; it explains how notes relate to each other.

Important MOCs:

| MOC | Purpose |
|---|---|
| [[_MOC_Master|Master MOC]] | Root navigation for the whole vault |
| [[_MOC_Active|Active Work MOC]] | What matters right now |
| [[_MOC_Startup|Startup MOC]] | Startup/product/venture strategy |
| [[_MOC_KnowledgeOS|KnowledgeOS MOC]] | How the system itself works |
| [[_MOC_Execution_System|Execution System MOC]] | Obsidian/Notion/Hermes role boundaries |
| [[_MOC_Experiments|Experiments Dashboard]] | Active experiments and their state |
| [[_MOC_Learning|Learning MOC]] | Learning paths, books, papers, practice |
| [[_MOC_Ecosystem|Ecosystem MOC]] | Cross-domain connections |

How to use them: start from [[_MOC_Master|Master MOC]], then follow the relevant domain MOC.

### 2. Typed Notes
Each note has a type. This prevents the vault from becoming a pile of generic notes.

Common types:

| Type | Use |
|---|---|
| `project` | Active work with outcomes and next actions |
| `research` | Investigation, source notes, findings |
| `decision` | Significant choice and why it was made |
| `experiment` | Hypothesis, method, metric, result |
| `concept` | Reusable idea or mental model |
| `synthesis` | Patterns across notes/time |
| `moc` | Navigation hub |
| `index` | Folder-level overview |

### 3. Frontmatter Schema
Every important note has YAML metadata at the top:

```yaml
type: project
title: Example Project
description: Project hub for Example Project.
status: active
schema: knowledgeos-v0.2
created: 2026-06-19
updated: 2026-06-19
tags: [startup, example]
project: Example Project
```

This metadata helps both you and Hermes understand what the note is.

### 4. Links and Graph
Obsidian wikilinks connect notes:

```text
[[../Projects/example-project|Example Project]]
[[../Decisions/okf-inspired-portable-knowledge-schema|OKF-Inspired Portable Knowledge Schema]]
```

The graph is real, not just decorative. But the recommended navigation style is:

```text
MOC first → relevant note → backlinks/graph/search for discovery
```

So the graph view is useful for exploration, while MOCs remain the primary navigation spine.

### 5. Automation Scripts
Scripts keep the vault operational:

| Script | Use |
|---|---|
| `rebuild_index.py` | Rebuilds the SQLite search/graph index |
| `search.py` | Searches titles, tags, projects, and linked notes |
| `weekly_data.py` | Produces weekly metrics |
| `daily_capture_report.py` | Checks Inbox items |
| `refinement_report.py` | Finds notes needing cleanup/refinement |
| `experiment_dashboard.py` | Generates experiment dashboard |
| `update_mocs.py` | Refreshes generated dashboards |
| `draft_weekly_synthesis.py` | Drafts a weekly synthesis |
| `validate_schema.py` | Checks metadata/link health |
| `export_bundle.py` | Exports portable markdown bundles |
| `publish_to_notion.py` | Publishes refined notes to Notion after dry-run |

## How to Use It Day to Day

### Daily Use — 5 to 15 minutes
1. Put raw thoughts into [[../Inbox/_Index|Inbox]].
2. Run or ask Hermes to run:
   ```bash
   python scripts/daily_capture_report.py
   ```
3. Convert important raw items into typed notes.
4. Link each note to a MOC, project, decision, concept, or experiment.
5. Rebuild the index:
   ```bash
   python scripts/rebuild_index.py
   ```

### Weekly Use — 30 to 60 minutes
1. Refresh dashboards:
   ```bash
   python scripts/rebuild_index.py && python scripts/update_mocs.py
   ```
2. Draft synthesis:
   ```bash
   python scripts/draft_weekly_synthesis.py
   ```
3. Review refinement candidates:
   ```bash
   python scripts/refinement_report.py
   ```
4. Validate schema:
   ```bash
   python scripts/validate_schema.py
   ```
5. Update active projects/experiments.

### Monthly Use — 60 to 120 minutes
1. Use [[../Templates/t-monthly-review|Monthly Review Template]].
2. Archive stale projects.
3. Revisit project thesis and assumptions.
4. Update learning roadmap.
5. Decide what should be refined or published.

## How Knowledge Moves Through the System

Example: you read an article about AI assessment.

1. Create a source note in Research.
2. Add metadata: `resource`, `source_type`, `timestamp`, tags, project.
3. Summarize claims and evidence.
4. Link it to [[_MOC_Startup|Startup MOC]] and [[../Projects/example-project|Example Project]].
5. If it changes strategy, create a decision note.
6. If it creates a testable assumption, create an experiment.
7. In weekly synthesis, decide what action follows.

That is how information becomes execution.

## Obsidian, Notion, Hermes, and Tasks

| Tool | Role | What belongs there |
|---|---|---|
| Obsidian | Thinking and knowledge graph | Notes, research, decisions, synthesis, MOCs |
| Notion | Execution and database layer | Tasks, pipelines, statuses, operational tracking |
| Hermes | AI operator/orchestrator | Search, summarize, validate, generate, maintain |
| Task system | Atomic execution | What needs doing by when |

Rule: do not make every tool do everything. Each layer has a job.

## When a Note Is Ready for Notion

A note can be published to Notion only when it is refined:

```yaml
status: refined
publish_to_notion: true
```

It should have:
- clear purpose
- substantive content
- useful links
- stable wording
- next actions, implications, or decisions where relevant

Always dry-run first:

```bash
python scripts/publish_to_notion.py --dry-run path/to/note.md
```

## What We Have Built So Far

KnowledgeOS now includes:

- structured vault architecture
- MOCs and folder indexes
- startup/project layer templates
- product thesis and assumption mapping examples
- customer discovery templates
- active experiments dashboard
- 26+ templates
- portable OKF-inspired schema
- schema validation
- exportable bundles
- SQLite graph/search index
- Notion publishing bridge
- weekly/daily review scripts
- execution-system role boundaries

## The Most Important Rule

Do not just store information. Make it move.

A good KnowledgeOS note should eventually connect to at least one of:
- a project
- a decision
- an experiment
- a concept
- a synthesis
- a source
- a next action

That is what turns the vault from a passive archive into an active thinking system.

## Related Notes
- [[../README|KnowledgeOS README]]
- [[_MOC_Master|Master MOC]]
- [[_MOC_KnowledgeOS|KnowledgeOS MOC]]
- [[_MOC_Execution_System|Execution System MOC]]
- [[../Research/knowledgeos-portable-schema|KnowledgeOS Portable Schema]]
- [[../Decisions/okf-inspired-portable-knowledge-schema|OKF-Inspired Portable Knowledge Schema]]
