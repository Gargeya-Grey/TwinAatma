# Product direction

13 November 2026. This page says what TwinAatma is for, how progress is measured,
and what is built next. It replaces the proof count as the steering measure.
[Verification status](verification-status.md) keeps the proof record.

## The promise

One memory and one self-model that belong to the person, work in every AI tool they
use, stay current without chores, and that no agent can rewrite without the person's
yes.

## Why the direction changed

From 19 October to 28 October the work was steered by one number: verified outcomes
of a fixed 54-outcome rubric. The number moved 37, 41, 15, 34. It moved mostly because
each product edit made earlier proof stale, not because the product changed for a
user. In that period:

- No user-facing capability was added.
- Startup at 10,000 notes went from 19 seconds to 27 seconds (formal baseline of
  25 October against the medians of 28 October), because each repair added checks to
  every request.
- 31 of the 54 outcomes cover integrity, privacy and data safety. About 5 cover
  whether the help is useful.

A count of proofs rewards proof. It does not reward a product that someone installs
and keeps.

## What a new user meets today

Measured on 13 November on a fresh vault, source revision `5acd4c5` plus the
uncommitted repairs:

| Step | Result |
|---|---|
| Profile after setup | Five sections that say "Unknown". They stay that way until an agent drafts a change and the person approves each one in a terminal. There is no import and no first-run interview. |
| `memory_search` with a plain question | 5 of 7 questions returned nothing, for example "what database did we pick for billing" against a note that says "use Postgres ... for the billing service". |
| `memory_capture` without a title | Refused: "memory_capture requires title". |
| First startup context | The starter vault's own help pages are returned as relevant memory. |
| Starter `AGENTS.md` | Contains an internal "resume paused project work" section. |
| Where memory works | For Cursor, Codex and VS Code, setup writes project files inside the vault, so memory loads only in chats opened there. For Claude Desktop and Windsurf it prints a config to paste by hand. |
| Hosts | Cursor, Codex, VS Code, Claude Desktop, Windsurf. Not Claude Code. |
| Speed at 1,000 notes | Within the owner-approved limits (p95 startup 2.0 s, recall 0.9 s; formal baseline, 25 October). |
| Speed at 10,000 notes | Startup 27 s, recall 15 s, capture 13 s (medians, 28 October). The limits are 5 s and 2 s. |
| Install | Source checkout or a locally built binary. No package index, no one-line install. |

## The market, November 2026

Reported by a research worker on 13 November from public sources; not re-checked
line by line.

- Every large assistant now has built-in memory. Claude and Gemini import memory from
  rivals. None exports memory in a form another vendor reads.
- Cursor removed its memory feature. Windsurf's default agent keeps none. Limitless
  closed after an acquisition. People lost memories each time.
- The plain "markdown + SQLite + MCP + Obsidian" slot is taken by basic-memory
  (about 4,600 GitHub stars, semantic search, a paid cloud). Hosted vector and graph
  memory is a funded, crowded field (Mem0, Zep, Supermemory, Cognee, Letta).
- Memory poisoning is documented and unsolved. Microsoft reported 31 companies
  planting memory instructions in "Summarize with AI" buttons (February 2026).
- A folder of markdown files with YAML frontmatter is becoming the portable format
  (Google's Open Knowledge Format, June 2026; AGENTS.md under the Linux Foundation).
- Tools that spread have a one-command install inside the agent host and show value
  in the first session.

## Position

TwinAatma is **the memory you own and carry between assistants, that an agent cannot
quietly rewrite**.

Three things no competitor found in the research combines:

1. **Carry.** Bring memory in from any assistant, use it in every host, write it back
   out as the files other tools read.
2. **Identity under your signature.** Values, rules and anti-goals live in one file.
   Agents propose; only the person approves, outside the chat.
3. **Tamper resistance.** Signed approval records outside the vault, notes treated as
   evidence and never as instructions.

Not worth competing on: hosted vector memory, benchmark leaderboards, and memory for
one coding repository (the hosts ship that themselves).

The core stays: markdown the person owns, a local MCP server with no dependencies,
the terminal approval boundary, and the integrity tests.

## How progress is measured

The gate is real use, not an internal count. A release is ready when a person who did
not build it can install it, connect one host, and get a remembered fact back in a
later chat without help.

| # | User outcome | Check | Target | 13 Nov |
|---|---|---|---|---|
| 0 | Real people use it and return | People outside the project who complete the first journey, and how many use it again within a week | 3 complete; 2 return | 0 |
| 1 | A real host chat works end to end | A genuine chat in a supported host starts memory, captures a fact, and a second chat recalls it | pass in 2 hosts | Codex CLI passed on 19 October bytes; not rechecked |
| 2 | Useful on day one | After setup plus one import, the first startup context holds imported memories, and one profile draft waits for review | pass | fail |
| 3 | Plain questions find the note | Share of plain-question cases where `memory_search` offers the expected note in its first 5 rows. A note that holds every word is in `ranked`. A note that holds only some words is in the separate `possibly_related` list, so a partial match is never presented as the answer. | 90% or more | 2 of 7 |
| 4 | Works wherever the person chats | User-level setup, so memory loads in every project | Claude Code and Codex | 0 |
| 5 | Clean first contact | Fresh vault: no starter page returned as relevant memory; no internal text in starter files | pass | fail |
| 6 | Safety holds | Full regression suite and mutation check | green | see status page |

Row 6 is a gate. A change that breaks it does not ship. The 54-outcome rubric stays
as a release checklist, run once against a release candidate, not after every edit.

Rows 1 to 6 can all pass with no user. Row 0 cannot, and it decides what is built
after 0.5.

## Speed at 10,000 notes is deferred, on purpose

Every request reads and hashes every note and recomputes a digest of the whole index.
That is why 10,000 notes take 27 seconds. It is also what makes these promises true:
an edit is seen at once, even at the same size with the same modified time; a note
that gains a credential or forgotten text is withheld at once; a rewritten index row
is found and repaired.

A cheaper check (size and modified time against a signed record) would miss real
cases: a sync or backup tool that keeps timestamps, a coarse filesystem clock, and a
changed index file. An independent review on 13 November judged that trade unsafe as
a default, and it is right.

New users have tens or hundreds of notes, where the product is already inside its
limits. So 0.5 leaves freshness as it is. The speed work returns after people use
the product, with one constraint: every returned row is still read from the note,
and a weaker check is an explicit setting with its limits stated, never a silent
default.

## Roadmap

**0.5 One journey that works** (install, connect, remember, recall)

1. First-contact repairs: plain-question search, starter noise, leaked internal text,
   capture without a title.
2. Reach: Claude Code as a host, and user-level setup for Claude Code and Codex.
3. Import: bring in memory from another assistant or from agent files. Each imported
   memory records where it came from. Rule-like lines become one profile draft; the
   toolkit has no model, so it does not infer identity beyond that.
4. One terminal session reviews every waiting profile draft, one decision each.
5. First-run prompt: with an empty profile, the agent offers once to set it up.
6. A genuine host chat proves the journey, and the README leads with it.

**0.6 Carry and trust** (order set by what users of 0.5 report)

7. Write memory out as `CLAUDE.md` and `AGENTS.md`.
8. Quarantine for memories from untrusted sources; expiry and conflict review.
9. One-line install from the package index.
10. Speed at 10,000 notes, under the constraint above.

**Later, only on demand**: Open Knowledge Format export, a Claude Code plugin,
optional semantic recall.

## Decisions that stay with the owner

- Inviting the first three to five outside testers (scorecard row 0).
- Publishing to a package index (it claims the name for good).
- Announcing the project.
- Separating the founder's own notes from the toolkit repository.
