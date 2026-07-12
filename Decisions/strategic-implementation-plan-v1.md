---
type: decision
title: KnowledgeOS Absolute-Best Strategic Implementation Plan (v1)
description: Locked roadmap to evolve KnowledgeOS into a plug-and-play subconscious / long-term memory system with a living Self-model, OKF-aligned schema, SDK, and MCP Memory API.
schema: knowledgeos-v0.2
status: active
created: 2026-07-12
updated: 2026-07-12
timestamp: 2026-07-12T00:00:00Z
tags: [decision, knowledgeos, roadmap, mcp, self-model, okf, strategy]
project: KnowledgeOS
resource:
---

# KnowledgeOS Absolute-Best Strategic Implementation Plan (v1)

## Context

KnowledgeOS is already stronger than a typical Obsidian vault: portable markdown + frontmatter, typed notes, decisions as first-class citizens, validation scripts, SQLite index, Notion bridge, and an Ego Node (`People/Self.md`).

Adversarial review (ChatGPT 5.5 Instant share + local code audit + Cursor synthesis, 2026-07-12) established:

- Architecture direction is right (durability > clever embeddings).
- Engineering debt is real (parser duplication, fragile YAML, overstated “agentic search”).
- Product framing undersells the idea (“second brain” vs portable cognitive infrastructure).
- The next moat is **memory evolution + Self write-back + MCP**, not more templates/MOCs.
- Plug-and-play requires packaging (init + starter vault), not only better internals.

This decision locks the roadmap so nothing critical slips during execution.

## Decision

Evolve KnowledgeOS into:

> **A local-first, OKF-aligned cognitive operating layer:** portable knowledge any human owns and any AI can load, update, and act through — becoming the closest digital representation of the user over time.

We will execute in **7 gated phases**. No phase starts until the previous phase’s **Exit Gate** passes, except explicitly marked parallel tracks.

## Alternatives Considered

1. **Keep building vault features (templates, MOCs, Notion polish)** — Rejected. Diminishing returns; does not create digital-self compounding.
2. **Invent a proprietary memory standard (KOMS)** — Rejected. Compete with OKF instead of implementing/extending it.
3. **Embeddings/vector-DB first memory product** — Rejected. Retrieval commoditizes; ownership and evolution do not.
4. **Full rewrite into a packaged app** — Rejected for now. Markdown vault + SDK + MCP is the correct wedge; UI can come later.
5. **This plan: foundation → packaging → MCP → Self evolution → intelligence → scale** — Chosen.

## Chosen Approach — North Star

### Product promise

After meaningful usage, any AI interface should be able to answer:

1. Who is this person (values, heuristics, anti-goals, active bets)?
2. What do they know, and how is it connected?
3. What did they decide, expect, and actually get?
4. How has their thinking changed, and why?
5. What should be retrieved *right now* before acting?

### Three memory layers (do not collapse)

| Layer | Question | Canonical home |
|---|---|---|
| **Identity (Self)** | Who am I / how do I decide? | `People/Self.md` + heuristics/mental models |
| **Semantic** | What do I believe / own? | Concepts, Decisions, Projects, Research, links |
| **Episodic** | What happened? | Syntheses, outcomes, git history, drift reports |

### Hard principles (non-negotiable)

1. **Markdown is canonical.** Indexes, Notion, embeddings, MCP views are derived.
2. **OKF-aligned, not OKF-competing.** Extend with cognitive primitives; don’t fork a parallel format war.
3. **Stdlib-first core.** Prefer zero pip deps for vault ops; optional extras only behind clear adapters (MCP runtime may be an exception, documented).
4. **Obsidian recommended, not required.** Agents must work via CLI/MCP alone.
5. **Notion optional.** Never a hard dependency for core memory.
6. **Human confirm for Self mutations.** Agents propose; user accepts (except Inbox-tier capture).
7. **Local-first privacy.** Self-model never requires cloud to function.
8. **Hybrid navigation.** Keep a few curated MOCs; generate the rest.
9. **No orphan work.** Every shipped capability has: schema impact, script/API, docs, validation, and a Definition of Done.
10. **Exit gates beat vibes.** Phases close only when measurable criteria pass.

### Explicit non-goals (v1 horizon)

- Building a full GUI / web app
- Mandatory vector database
- Replacing Obsidian or Notion
- Multi-tenant SaaS sync
- Auto-publishing private Self content anywhere
- Replacing curated MOCs entirely with generated views
- Heavy PageRank/centrality as a near-term priority

---

## Success Criteria (Absolute Best bar)

### A. Plug-and-play (new user, 10 minutes)

- [ ] `python -m knowledgeos init` (or equivalent) creates a clean starter vault
- [ ] Onboarding produces a real `People/Self.md`
- [ ] Index + validation + doctor pass with zero manual path hacking
- [ ] MCP config snippet is printed and works in at least one client (Cursor or Claude Desktop)
- [ ] No founder Notion DB IDs, Hermes-only assumptions, or personal residue required

### B. Portable memory (any AI)

- [ ] Stable Memory API: `self`, `search`, `related`, `decisions`, `drift`, `capture`, `propose_self_update`
- [ ] Same vault readable by multiple agents without conversion
- [ ] Export bundle + schema version remain human-readable

### C. Digital-self compounding (30–90 days of use)

- [ ] Decision notes support structured expected/actual/lesson fields
- [ ] Weekly loop updates episodic memory and proposes Self diffs
- [ ] Drift report writes actionable review items (not only prints tips)
- [ ] User can show: “how my thinking changed” with evidence chains

### D. Engineering integrity

- [ ] Single shared frontmatter parser
- [ ] Schema validator covers new cognitive fields
- [ ] No duplicated Notion API helpers / parsers
- [ ] Cross-platform hooks (Windows + Unix)
- [ ] LICENSE present; README claims match reality
- [ ] Template frontmatter bugs fixed (duplicate `description` keys)

---

## Current Baseline (audit snapshot 2026-07-12)

### Strengths to preserve

- Portable schema doc: `Research/knowledgeos-portable-schema.md`
- Decision-first architecture + role boundaries
- 26 templates + operating cadence docs
- Stdlib automation suite (~21 Python scripts)
- Ego Node + onboarding wizard
- Refinement bar for Notion publishing

### Critical gaps

| Gap | Evidence |
|---|---|
| No shared SDK/parser | `parse_frontmatter()` in 4+ scripts |
| No MCP server | Absent; Notion MCP previously rejected for Node overhead |
| No single init | README multi-step; `doctor.py` partial only |
| No entity IDs | Path/title identity only |
| No belief/confidence | Zero schema support |
| Decision outcomes unstructured | Body sections only; rarely filled |
| No Self write-back | Drift suggests; nothing patches Self |
| OSS blockers | Hardcoded Notion DB ID; Hermes coupling; no LICENSE; example/personal residue |
| Search overstated | SQLite `LIKE` metadata search, no body FTS |
| Docs drift | Script counts, Python 3.8 vs 3.9, missing folders |

---

## Phase Map (overview)

```text
P0  Stabilize & truth-align          (1–3 days)
P1  Core SDK + schema v0.3           (3–7 days)
P2  Plug-and-play packaging          (3–5 days)
P3  MCP Memory API                   (5–10 days)
P4  Self evolution & outcome loop    (5–10 days)
P5  Intelligence layer               (5–10 days)
P6  Hardening, OSS, adoption         (ongoing)
P7  Invisible Twin Autopilot         (agent-owned ops after MCP wire)
P8  Guaranteed Autopilot             (freshen + evolve without user ops)
```

Parallel allowed only where marked. Estimated ranges assume focused solo/agent execution, not calendar weeks with context switching.

---

## Phase 0 — Stabilize & Truth-Align

**Goal:** Make the repo honest, safe, and operable before architectural expansion.

### Workstreams

#### P0.1 Documentation truth

- [x] Align README Python version with `doctor.py` (pick **3.9+** unless 3.8 support is restored)
- [x] Complete README script table (include doctor, onboarding, drift, alignment, notion tools)
- [x] Fix “9 scripts” / stale claims in `Projects/knowledgeos.md`
- [x] Add missing structural dirs with `.gitkeep` if needed: `Experiments/`, `Assets/`, `Archive/`
- [x] Add `LICENSE` (MIT as claimed) or correct badge

#### P0.2 Security & personal residue scrub (prep for packaging)

- [x] Remove hardcoded Notion DB ID from `scripts/_notion_env.py`
- [x] Move all Notion property maps to config (env or `config.example.json`)
- [x] Document Hermes as optional orchestrator, not required runtime
- [x] Inventory founder-specific notes for later starter-vault separation (do not delete history yet; mark)

#### P0.3 Correctness hotfixes (no new features)

- [x] Fix duplicate `description:` keys in all `Templates/*.md`
- [x] Fix `draft_weekly_synthesis.py` so drafts pass `validate_schema.py`
- [x] Normalize generated links to markdown (not wikilinks) in `experiment_dashboard.py`
- [x] Fix `publish_to_notion.py --all` to respect `publish_to_notion` flag
- [x] Make `setup_git_hooks.py` Windows-compatible (or provide PowerShell hook path)

#### P0.4 Tracking spine

- [x] Keep this decision note as roadmap source of truth
- [x] Add checklist progress updates in `Projects/knowledgeos.md` Next Actions pointing here
- [x] Initialize git if not present (required for drift/hooks/history)

### Exit Gate P0

- [x] `python scripts/doctor.py` passes on clean machine assumptions
- [x] `python scripts/validate_schema.py` passes on templates + core notes (or known waiver list documented)
- [x] No secrets/hardcoded DB IDs in repo
- [x] README setup steps match actual scripts

**P0 closed: 2026-07-12.** Known waivers: `People/Self.md` and `Projects/example-project-thesis.md` warn `no_links` (non-blocking). Founder-specific narrative remains in some Decisions/Projects for history; starter split deferred to P2.
---

## Phase 1 — Core SDK + Schema v0.3

**Goal:** One parser, one schema contract, one importable library. Scripts become thin clients.

### Workstreams

#### P1.1 Package layout

Create:

```text
knowledgeos/
  __init__.py
  parser.py          # single frontmatter + body parser
  schema.py          # versioned field contracts + enums
  links.py           # link extraction / rewrite helpers
  graph.py           # notes + edges model over SQLite or in-memory
  index.py           # rebuild/query index
  vault.py           # Vault root abstraction
  self_model.py      # Self.md load/diff/propose helpers (stub OK)
  cli.py             # future: python -m knowledgeos
scripts/             # thin wrappers calling knowledgeos.*
```

Rules:

- [x] No script reimplements `parse_frontmatter` (shared `knowledgeos.parser`; publish keeps thin wrapper)
- [x] Preserve stdlib-only for core package in P1
- [x] Keep backward compatibility with `schema: knowledgeos-v0.2` notes
- [x] `graph.py` / `index.py` deferred (acceptable); `self_model.py` + `init_vault.py` shipped
- [x] `python -m knowledgeos` entry (`doctor`, `validate`, `version`, `ids`, `self`, `init`)

#### P1.2 Schema v0.3 (OKF-aligned cognitive extension)

Extend portable schema **without breaking v0.2**:

**Additive fields documented** in `Research/knowledgeos-portable-schema.md` and `knowledgeos/schema.py`.

- [x] Document optional v0.3 fields (`id`, confidence, outcomes, etc.)
- [x] Add types `belief | heuristic | mental_model` to schema module
- [x] Decision template upgraded with structured outcome frontmatter fields
- [x] Self.md machine-parseable markers defined for write-back

#### P1.3 Validation upgrade

- [x] `validate_schema.py` uses shared schema module
- [x] Warn on unknown type / schema version
- [x] Validate id format when present
- [x] Validate decision outcome_status enum
- [x] Detect duplicate `id` values
- [x] Fix boolean parsing (`publish_to_notion: true`)

#### P1.4 Index upgrade (minimal)

- [x] Store `entity_id`, `confidence`, `last_reviewed`, `outcome_status` columns when present
- [x] Keep path as unique filesystem key; `entity_id` as logical key
- [x] Migration: rebuild / hash invalidation backfills columns

#### P1.5 ID generation utility

- [x] `python -m knowledgeos ids assign` dry-run by default; `--write` to apply
- [x] Stable slug from title; collision suffix
- [x] Additive frontmatter only (does not force schema bump)

### Exit Gate P1

- [x] Core scripts import shared parser (rebuild/validate/export/publish)
- [x] v0.2 notes still validate
- [x] v0.3 fields documented in `Research/knowledgeos-portable-schema.md`
- [x] `python -c "from knowledgeos import parse_frontmatter"` / `python -m knowledgeos version` works
- [x] Smoke test: `python scripts/smoke_test.py`
- [x] Index columns + id assign utility complete

**P1 closed: 2026-07-12.**

---

## Phase 2 — Plug-and-Play Packaging

**Goal:** A stranger (or agent) can stand up a clean personal memory vault in ≤10 minutes.

### Workstreams

#### P2.1 Distribution model

- [x] Init generates clean vault (templates + scripts + package copied)
- [ ] Optional: move current founder content under `examples/` (deferred — init already produces clean vault)
- [x] Document init in README

#### P2.2 `knowledgeos init`

- [x] `python -m knowledgeos init <path> --name ... --non-interactive`
- [x] Copies Templates, scripts, knowledgeos package, LICENSE, config example
- [x] Writes Self.md, Master/Active/How MOCs, folder indexes
- [x] Auto-run rebuild/validate inside init (best-effort; results in `.knowledgeos-init.json`)
- [ ] Print MCP config snippet (deferred to P3)

#### P2.3 Starter vault contents (minimal)

- [x] Folder spine + `_Index.md` stubs
- [x] `_MOC_Master.md`, `_MOC_Active.md`, `_MOC_How_KnowledgeOS_Works.md`
- [x] `Templates/` copied from toolkit
- [x] Self.md generated with section markers
- [x] No founder Notion residue in init output
- [ ] Empty `People/Self.md` template OR generate via onboarding
- [ ] Example notes **optional** behind `--with-examples`

Exclude from starter:

- [ ] Personal Notion decisions narrative
- [ ] Hardcoded integrations
- [ ] Live Active MOC state from founder work

#### P2.4 Config contract

Add `knowledgeos.config.json` (or `.knowledgeos.yaml`) in vault root:

```json
{
  "schema": "knowledgeos-v0.3",
  "notion": { "enabled": false },
  "mcp": { "enabled": true },
  "privacy": { "local_only": true }
}
```

#### P2.5 Agent setup guide

- [ ] Rewrite README “Agent Automation” to one command
- [ ] Keep human Obsidian path as secondary

### Exit Gate P2

- [x] Fresh directory → init → doctor + validate green
- [x] No personal residue in starter
- [x] Init works on Windows PowerShell and Unix
- [x] Time-to-first-Self < 10 minutes in dry run checklist

**P2 closed: 2026-07-12** (MCP snippet printed from init in P3).

---

## Phase 3 — MCP Memory API (Plug into any AI)

**Goal:** KnowledgeOS becomes infrastructure: any MCP client can use the same memory.

### Workstreams

#### P3.1 Reverse/refine prior Notion-MCP decision

- [x] Update Notion decision with addendum + [MCP Memory decision](knowledgeos-mcp-memory-server.md)
- [x] Prefer stdlib Python MCP stdio (no pip); CLI fallback for non-MCP agents
- [x] Keep core vault ops usable without MCP

#### P3.2 Tool surface (v1 Memory API)

- [x] `memory_self_get`
- [x] `memory_search` (metadata + body scan)
- [x] `memory_related`
- [x] `memory_get_note`
- [x] `memory_decisions`
- [x] `memory_drift`
- [x] `memory_capture`
- [x] `memory_propose_self_update`
- [x] `memory_accept_self_update` (explicit accept)
- [x] `memory_propose_note_update`
- [x] `memory_timeline`
- [x] `memory_bootstrap_context`

#### P3.3 Write policy

- [x] Inbox capture auto-write
- [x] Self proposal-only + accept tool
- [x] Note proposals to Inbox (no auto-apply)
- [x] Never auto-publish to Notion via MCP

#### P3.4 Context assembly helper

- [x] `memory_bootstrap_context(task_hint)`

#### P3.5 Client docs

- [x] Cursor MCP example (`mcp.cursor.example.json`)
- [x] README MCP section
- [x] CLI fallback: `python -m knowledgeos memory ...`
- [ ] Claude Desktop example (same JSON shape — documented as compatible)

### Exit Gate P3

- [x] MCP initialize + tools/list + memory_self_get smoke passed locally
- [x] Capture writes Inbox note end-to-end
- [x] Propose Self update creates reviewable diff without mutating until accept
- [x] Path traversal blocked via vault sandbox in MemoryAPI._resolve

**P3 closed: 2026-07-12.**

---

## Phase 4 — Self Evolution & Outcome Loop

**Goal:** Usage over time produces a closer digital representation of the user.

### Workstreams

#### P4.1 Decision outcome loop

- [x] Upgrade `Templates/t-decision.md` with structured outcome fields
- [x] `check_alignment.py`: flag decisions with pending outcomes / past `review_after`
- [x] Weekly synthesis includes “decisions due for outcome review” + loop checklist
- [x] MCP: `memory_pending_outcomes` (+ Outcomes Dashboard)

#### P4.2 Self write-back protocol

- [x] `scripts/propose_self_update.py` + `knowledgeos/evolution.py`
- [x] Store proposals in `People/Self-Proposals/`
- [x] Never silently rewrite Ego Node (reject/accept explicit)

#### P4.3 Heuristic & mental model objects

- [x] Define promotion rules (`Concepts/heuristic-promotion-rules.md`)
- [x] `Templates/t-heuristic.md`

#### P4.4 Belief tracking (lightweight)

- [x] Add optional `Templates/t-belief.md`
- [x] Optional fields via schema v0.3 (`confidence`, evidence in body)
- [x] Not required for every note

#### P4.5 Closed founder/operator loop (documented cadence)

- [x] Update How-KnowledgeOS-Works MOC with outcome→Self loop
- [x] Weekly script emits stage checklist

### Exit Gate P4

- [x] Demo: decision expected→actual→lesson→Self proposal (`Decisions/demo-close-outcomes-into-self.md`)
- [x] Demo: drift → Self proposal file created (`memory_propose_from_drift`)
- [x] Zero silent Self mutations (reject demo left Self unchanged)
- [x] User can reject proposals cleanly (`propose_self_update.py reject`)

**P4 closed: 2026-07-12.**

---

## Phase 5 — Intelligence Layer

**Goal:** Answer “how has my thinking changed?” better than search.

### Workstreams

#### P5.1 Body search / FTS

- [x] Add SQLite FTS5 for note body (`notes_fts`)
- [x] Keep metadata ranking; blend with FTS (`knowledgeos/search.py`)
- [x] README: search described as metadata + FTS5 (not “agentic”)

#### P5.2 Generated views (hybrid with MOCs)

- [x] Pending decision outcomes (`_MOC_Outcomes.md`)
- [x] Stale active projects (`_MOC_Stale_Projects.md`)
- [x] Orphan notes (`_MOC_Orphans.md`)
- [x] Unreviewed beliefs (`_MOC_Belief_Reviews.md`)
- [x] Emerging themes (`_MOC_Emerging_Themes.md`)
- [x] Tensions view (`_MOC_Tensions.md`)

#### P5.3 Contradiction / tension flags (v1 heuristic)

- [x] supersedes/invalidates + contradicts mentions + invalidated-decision↔active-project links
- [x] Reported in weekly intelligence brief + Tensions MOC
- [x] No NLP dependency

#### P5.4 Weekly Intelligence Report

- [x] `scripts/intelligence_brief.py` — decisions, outcomes, drift, proposals, gaps, stale, tensions

#### P5.5 Learning trajectory view

- [x] `scripts/learning_trajectory.py` — Self Drift Log + decision timeline

### Exit Gate P5

- [x] FTS search finds body content reliably (phrase hit on demo decision)
- [x] Weekly intelligence report generates without schema violations
- [x] ≥3 generated views via `update_mocs.py` (outcomes + stale + orphans + beliefs + themes + tensions + experiments)
- [x] Trajectory report runnable

**P5 closed: 2026-07-12.**

---

## Phase 6 — Hardening, OSS Adoption, Scale

**Goal:** Make it adoptable and hard to break.

### Workstreams

#### P6.1 OSS readiness

- [x] LICENSE, CONTRIBUTING, SECURITY.md
- [x] Topic positioning + homepage one-liner in README
- [x] Name collision note vs other “KnowledgeOS” products
- [ ] Screenshots/GIFs (optional polish)

#### P6.2 Quality system

- [x] Smoke test + `tests/test_core.py` unittest suite
- [x] Init covered in unittest tempfile
- [x] Pre-commit still runs validate_schema
- [ ] Full CI workflow file (optional — local suite green)

#### P6.3 Performance & scale targets

- [x] Documented in `Research/knowledgeos-scale-schema-governance.md`
- [x] Avoid premature graph analytics (documented deferral)

#### P6.4 Optional adapters

- [x] Notion config-driven (P0)
- [x] Hermes optional (docs)
- [x] Embeddings deferred as optional derived index only

#### P6.5 Governance of schema

- [x] Versioning policy documented
- [x] v0.2 still accepted
- [x] OKF stance documented

### Exit Gate P6 (rolling)

- [x] Init + MCP docs allow external setup
- [x] `python -m unittest discover -s tests -v` green
- [x] No critical path depends on Hermes/Notion
- [x] README positioning matches north star

**P6 closed: 2026-07-12** (screenshots/CI YAML optional follow-ups).

---

## Phase 7 — Invisible Twin Autopilot (agent-owned ops)

**Goal:** User wires MCP once. After that, the agent decides when to load memory, capture, propose Self updates, and surface overdue outcomes — no human choreography.

#### P7.1 Always-on agent contract
- [x] Root `AGENTS.md` operating contract
- [x] `.cursor/rules/knowledgeos-twin.mdc` (`alwaysApply: true`)
- [x] `init` copies contract + MCP example into new vaults

#### P7.2 Session rituals (MCP)
- [x] `memory_session_start` — Self + context + ops summary
- [x] `memory_session_end` — optional capture + remaining yes/no
- [x] `memory_ops_status` — plain-language hygiene for agents

#### P7.3 Product promise
- [x] README: wire MCP once → just chat
- [x] Decision note: `Decisions/invisible-twin-autopilot.md`

### Exit Gate P7
- [x] Capable MCP-wired agent has an explicit always-on contract naming tools and cadence
- [x] Composite session tools exist so agents need not invent the ritual
- [x] Self still proposal-only (no silent rewrite)
- [x] User-facing docs do not require remembering weekly CLI for optimal twin value

**P7 closed: 2026-07-12**

---

## Phase 8 — Guaranteed Autopilot (post-setup magic)

**Goal:** After successful first-time setup, the user never operates KnowledgeOS. Every wired chat is grounded in an up-to-date, relevant, self-evolving twin.

#### P8.1 Autopilot core
- [x] `knowledgeos/autopilot.py` — state, ensure_index_fresh, weekly drift propose, soft prompts, breathe
- [x] `memory_session_start` / `memory_breathe` run full breathe
- [x] `memory_session_end` marks session + refreshes index
- [x] CLI `python -m knowledgeos breathe`

#### P8.2 Host enforcement
- [x] MCP `initialize.instructions` compact contract
- [x] Cursor `sessionStart` / `sessionEnd` hooks (pre-warm + orphan detection)
- [x] AGENTS.md + alwaysApply rule rewritten for soft UX / no user ops

#### P8.3 Packaging
- [x] init copies hooks; `.knowledgeos/` gitignored
- [x] Decision + README autopilot table

### Exit Gate P8
- [x] Session start refreshes stale index without user action
- [x] Soft prompts replace chore language
- [x] Weekly drift proposal is agent/autopilot-owned (still human-confirm to apply)
- [x] Host hooks + MCP instructions reinforce first-tool session_start

**P8 closed: 2026-07-12**

---

## Cross-Cutting Workstreams (track continuously)

### CX-1 Schema & Spec

- Living docs: `Research/knowledgeos-portable-schema.md`
- Decision logs for every schema bump
- OKF mapping table (what we inherit vs extend)

### CX-2 Security & Privacy

- Vault path sandboxing for MCP writes
- No secrets in git
- Clear warning: Self.md is highly sensitive
- Optional redact/export filters for sharing bundles

### CX-3 DX / Agent DX

- One-command agent setup
- Deterministic script JSON outputs where possible
- `doctor` explains next fix, not only failures

### CX-4 Human UX (Obsidian)

- Templates remain excellent
- MOCs remain few and meaningful
- Avoid forcing users to edit raw YAML for common actions (prefer CLI/MCP wizards)

### CX-5 Metrics (are we winning?)

Track in monthly review:

1. Time-to-init for a new vault
2. % decisions with outcomes filled within review window
3. Self proposals accepted / rejected ratio
4. Weekly active capture count
5. MCP query success in daily work
6. Orphan note rate
7. Validator error rate over time

If (2) and (3) stay near zero, the digital-self promise is failing regardless of feature count.

---

## Dependency Graph (do not violate)

```text
P0 ──► P1 ──► P2 ──► P3 ──► P4 ──► P5
              │       │
              └───────┴──► P6 (starts after P2; hardens continuously)

Blocked relationships:
- MCP (P3) blocked on SDK (P1) and preferably init/config (P2)
- Self write-back (P4) blocked on Self parse contract (P1) + propose tooling (P3 helps)
- Intelligence reports (P5) blocked on outcome fields (P4) + better index (P1/P5.1)
- OSS push hard-launch blocked on P0 residue scrub + P2 starter
```

---

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Overbuilding belief ontology → user abandonment | High | Keep confidence optional; infer first; promote later |
| MCP runtime deps break stdlib purity story | Medium | Core stays stdlib; MCP as optional extra path |
| Starter/example split fragments maintenance | Medium | Generate starter from templates; single schema source |
| Silent Self mutation destroys trust | Critical | Proposal-only writes; audited accept step |
| OKF drift / Google format changes | Medium | Track OKF; stay inspired-compatible; version our extensions |
| “Second brain” positioning → ignored on GitHub | High | Rewrite README hero around portable Self-memory |
| Windows/Unix split (hooks, paths) | High | Test init/hooks on Windows first (this machine) |
| Scope creep into app/GUI | High | Non-goals list; refuse until P4 exit |
| Founder vault and toolkit confuse contributors | High | Explicit `starter/` vs `examples/` |

---

## Anti-Slip Operating Rules

1. **No phase skip** without written waiver in this file.
2. **Every PR/change set** must name: Phase ID + checklist items closed.
3. **Schema changes** require: schema doc + template updates + validator + example note.
4. **New script** requires: README row + doctor awareness if health-related.
5. **New MCP tool** requires: write policy classification + sandbox test.
6. **Weekly** (during build): run doctor + validate + init-from-scratch smoke.
7. **Do not add templates** unless tied to P4 cognitive primitives.
8. **Do not add MOCs** unless curated spine or generated view.
9. **Embeddings** only as optional derived index after P5 FTS exists.
10. **Update this decision’s Actual Outcome** at each phase exit.

---

## Recommended Immediate Execution Order (first 10 tasks)

1. P0: Remove hardcoded Notion DB ID + add LICENSE
2. P0: Fix template duplicate `description` keys
3. P0: Align README/doctor Python version + script inventory
4. P0: Git init (if needed) + hooks Windows path
5. P1: Create `knowledgeos/` package; centralize parser
6. P1: Migrate `rebuild_index`, `validate_schema`, `export_bundle`, `publish_to_notion` to shared parser
7. P1: Draft schema v0.3 doc (additive fields + decision outcomes)
8. P2: Design `starter/` skeleton + `init` command stub
9. P2: Scrub starter from founder-specific Notion/Hermes hard requirements
10. P3: Spec MCP tool schemas in a decision note before coding server

---

## Expected Outcome

If executed as gated above, KnowledgeOS becomes:

1. **Easy to start** (init + Self onboarding)
2. **Easy to plug in** (MCP Memory API across AI clients)
3. **Hard to corrupt** (validation, proposal-based Self writes)
4. **Capable of representing the user over time** (outcomes → lessons → Self evolution)
5. **Strategically positioned** as OKF-aligned cognitive infrastructure, not another PKM theme pack

## Actual Outcome

| Phase | Exit Date | Result | Notes |
|---|---|---|---|
| P0 | 2026-07-12 | **Passed** | LICENSE; Notion ID scrub + config example; template description fixes; weekly draft schema; markdown experiment links; `--all` publish filter; Windows git hooks; README 3.9+ + full script table |
| P1 | 2026-07-12 | **Passed** | `knowledgeos/` package; shared parser; schema v0.3 fields; index entity columns; ids assign CLI; Self markers; decision outcome template; smoke_test.py |
| P2 | 2026-07-12 | **Passed** | `knowledgeos init` + auto rebuild/validate; clean starter vault |
| P3 | 2026-07-12 | **Passed** | Stdlib MCP Memory server; 12 tools; CLI fallback; Cursor config example; proposal/accept Self write policy |
| P4 | 2026-07-12 | **Passed** | Outcome reviews; evolution proposals; reject path; belief/heuristic templates; Outcomes Dashboard; loop docs |
| P5 | 2026-07-12 | **Passed** | FTS5 blended search; generated intelligence views; weekly intelligence brief; learning trajectory |
| P6 | 2026-07-12 | **Passed** | README north-star; CONTRIBUTING/SECURITY; unittest suite; scale/schema governance doc |
| P7 | 2026-07-12 | **Passed** | AGENTS.md + Cursor twin rule; session_start/end + ops_status; init copies contract; wire-once README |
| P8 | 2026-07-12 | **Passed** | Autopilot breathe; index freshen; soft prompts; Cursor hooks; MCP instructions |

## Related Notes

- [KnowledgeOS Portable Schema](../Research/knowledgeos-portable-schema.md)
- [OKF-Inspired Portable Knowledge Schema](okf-inspired-portable-knowledge-schema.md)
- [Obsidian, Notion, Hermes Role Boundaries](obsidian-notion-hermes-role-boundaries.md)
- [Connect Notion as Execution Layer](connect-notion-execution-layer.md)
- [Refinement Bar for Notion Publishing](refinement-bar-for-notion-publishing.md)
- [How KnowledgeOS Works](../MOCs/_MOC_How_KnowledgeOS_Works.md)
- [KnowledgeOS Project Hub](../Projects/knowledgeos.md)
- [Self Ego Node](../People/Self.md)
- External review source: [ChatGPT — AI Knowledge Base Review](https://chatgpt.com/share/6a53945c-b9fc-83ee-9b56-fe034d2d47de)
