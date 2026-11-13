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

### State after the 0.5 work

The column "13 Nov" above is the state before the work. This is the state after it,
on branch `product/one-journey`. Each line says how it was checked.

| # | State | How it was checked |
|---|---|---|
| 0 | 0 | No outside tester yet. This row needs the owner. |
| 1 | Not passed. Claude Code works in the builder's test chats; Codex was not rechecked. | See "What real Claude Code chats showed" below. The chats ran under the builder's account with the builder's own global rules loaded, so they are not acceptance evidence. |
| 2 | Pass in the source journey | `first_day.py`: after one import the next startup context holds the imported preference and one profile draft waits. No model call. |
| 3 | The suite's plain-question cases pass | `tests/test_first_contact.py`. The older 7-case count was not run again. Known miss: a question that shares no word and no concept cluster with the note. |
| 4 | Built, not run for real | The command lines for Claude Code and Codex are built and tested with a recorder in place of the host. A real registration is the person's own step. |
| 5 | Pass | `tests/test_first_contact.py` and `first_day.py`. |
| 6 | Full suite green on the commit that holds the sixth-review repairs | 1269 tests, 33 skipped, run alone on Windows with Python 3.13 (1249 at `a0171e0`). `tests/score.py` reported 100.0 across 71 scenarios on the same code, and `first_day.py` 37 of 37. Commit `fd1bac1` between the two was red on 15 tests: its reader refused the JSON record of an outcome. It was committed after focused tests only; the next commit repaired it. On Python 3.11 only five changed test files were run here; CI runs the whole suite on 3.11 and on Linux. |

### What real Claude Code chats showed

Claude Code has a memory of its own, and the model prefers it. With the memory
server only registered, the model called it in 0 of 3 chats in one run and in 1 of 4
in another, and both "remember this" chats saved to the host's memory, not to the
vault. So registration alone does not deliver the product in Claude Code.

`setup-host --host claude-code --global` now also sets two hooks. One shows the
approved profile and how to use the memory when a session starts. The other shows
the matching notes before each prompt. With the hooks from a clean install, the
model called the memory server in 6 of 6 chats, both "remember this" chats saved the
fact and drafted a profile change and named the terminal command, and the profile
file was unchanged in 6 of 6.

Open risks from the same chats, each seen once in a small sample:

- In 1 of 3 recall chats one model gave the person only "I'm done" and put the
  answer in the stored session summary. Two repeats answered correctly.
- In 1 of 2 "remember this" chats one model also saved the fact to the host's own
  memory, so the fact was saved twice.
- The prompt hook starts a process for each prompt. It took 1.6 seconds on a small
  vault. It is bound by the same freshness check as every memory call, so it is too
  slow for a 10,000 note vault until the speed work is done.

The cleaner long-term form of this is a Claude Code plugin, which the host installs
and removes through its own command. It stays under "Later".

### Three design decisions after three reviews

An independent reviewer read the 0.5 work three times on 13 November. Each time it
said "do not ship": 7, then 15, then 11 findings. No review found a way to change the
profile without the person's decision in a terminal. Three kinds of fault came back
in all three reviews. The cause was the same each time: the code listed what is
forbidden, and each review found one more case that was not on the list. The owner
gave the decisions to the builder on 13 November. Each rule now refuses the unknown
case.

**1. A note with a privacy key is private unless its value says it is not.** The
values that share a note are `ordinary`, `public`, `shared`, `open`, `normal`,
`none` and `low`, and a plain no: `false`, `no`, `off`, `0`, `null`, `~` or an empty
value. Any other value, and any form the reader does not know, keeps the
note private. A repeated key counts wherever it stands. `doctor` counts the marked
notes and prints the list of sharing values. The cost: a note with an unusual value
is not offered until the person changes the value.

**2. A profile draft is not a note.** No route returns a file from the draft folder
as a note: not as a search hit, a neighbour, a start for neighbours, a decision, a
timeline row or context. Decided or not. The text of a draft is reached on purpose:
the list of drafts, or a read by its own path. Three status answers name the path of
a draft that waits, because the person must be told that it waits:
`memory_ops_status`, the weekly report, and the freshness reason of a session start. `tests/test_draft_is_not_memory.py` asks every
read tool, and a new tool fails that test until it is placed in its table. A map or
index page is a starter page only under a name the toolkit writes (`_Index.md`,
`_MOC_*.md`, the vault `README.md`). A map the person wrote is memory.

**3. Import defends against an accident, and the signed record remembers what was
asked.** [The threat model](threat-model.md) states what the product defends
against. Import reads each file through one open handle and names every file it
skips. Each draft's lines are kept as digests in the signed record outside the
vault, so a rejected rule stays rejected when its draft file is edited or deleted.
This added the field `asked_lines` to that record; an older row without it is
trusted only while its draft file is unchanged.

### A fourth review, and how each rule is now checked

The fourth review read the work against [the threat model](threat-model.md). It said
"do not ship" with 6 findings inside the release bar. Two were leaks in work that was
called done: a privacy marker written below another key or inside braces, and
`memory_related` returning a draft. The rules were right. The checks behind them were
lists of cases written by the same hand that wrote the code. So each rule now has a
check that does not depend on that hand.

**4. A note is shared only when its whole metadata block is read.** The toolkit reads
metadata without a YAML library. The first form of this decision looked for a privacy
key in each form somebody had thought of, and a fifth review found eight more forms
(an escaped key, a tag, an anchor, a value over two lines). So the rule was turned
round. The reader takes a small grammar apart: plain `key: value` lines, lists, nested
blocks, text values, and a value that is one whole JSON object or list (read with the
JSON parser of the standard library). A block in any other form is not searched. It keeps the note
private, and `doctor` counts such notes apart from the marked ones. The toolkit's own
flat parser is asked too, so the two readings never disagree.
`tests/test_privacy_yaml_oracle.py` changes known texts at random and compares the
answer with a real YAML library. It found a fault in the reader of `a0171e0` in about
one block of seventy. The library is a tool of the test only. The cost: a note whose
metadata uses a `{...}` mapping with a value inside, a tag or an anchor is not offered
until it is written as plain lines, and a metadata line that reads `privacy: private`
keeps the note private even inside a text value. `doctor` counts such notes and
`import` names such files.

The first form of that test handed the library the inside of the block. A sixth review
found a marker in the opening line (`--- # note`, then a line separator that only a
full parser honours, then the key), which that test could not see. The test now hands
over the whole text and changes the opening line, the closing line and the text after
it too. In that form it failed on the reader of `fd1bac1` within 3,000 texts, and it
found one more gap by itself: a no-break space after a colon, which a full parser
reads as an ordinary character and the reader read as a space. After both repairs it
found no fault in 2 million texts. The full suite then showed a fault of the builder's
own: the strict reader refused the JSON record that the toolkit writes into a decision
when an outcome is recorded, so 15 older tests failed and such a note would have been
withheld. A whole JSON value is now read, and the test of what the toolkit writes
records an outcome too. A second random run then found a comment line that ended at
one of the rare line separators; the reader now refuses those characters before it
sets any comment aside. After that repair the run found no fault in 20 million texts.
The reader now holds three more rules. The opening
line is cut where a full parser cuts it. An opening line that holds more than a
comment (`--- {privacy: private}`) is a form that is not read. A space that is not a
YAML space is an ordinary character.

A text that comes in is judged with its own metadata block, and with a marked block
between two `---` lines further down: after a line of introduction, in a code fence,
with a margin. A private note that is pasted into `memory_capture` or
`memory_propose_note_update` in one of these forms is refused. A note that is typed
again in another shape is not recognised, because the policy does not judge meaning.
A text that opens with a rule line and words (a link, bold words, a quotation) is
ordinary writing and is accepted. A text that opens with a block in a form that is
not read is refused with a message of its own: send the words without the block,
unless the block marks them private. A text on its way out is a piece of a note that
was already judged, so a body that begins with a metadata example is an ordinary body.

The toolkit writes a title in quotes when this reader or a full YAML parser would not
read it as text: `Decision: use this`, a ` #`, a leading `[`, `&`, `!` or `- `. A
character that metadata cannot hold (a control character, a byte order mark) becomes
a space. So a saved fact can be read back under any title, here and in a note tool.
`tests/test_privacy_metadata_comments.py` writes 4,000 random titles and reads each
one back with both.

**5. One list of notes.** A route that reads files itself starts from
`indexer.iter_notes`, which leaves drafts out. The same test file names each remaining
caller of the plain file list and the reason it may see a draft. A new caller fails
that test until it is named.

**6. Import does not enter a linked folder while it walks.** A Windows junction is a
link. Import walks the folder itself, skips each linked file and folder below the
source, and names it, a link that leads nowhere too. The source path itself is the
person's choice: a path that is a link is refused, and a path that passes through a
linked folder higher up is read, because a home folder often is one.

**7. A draft that is not in the signed record is reported.** When the state folder is
lost, every import run, a dry run too, counts each draft it cannot check and says that
a rule the person already decided can be drafted again. An older signed draft whose
file was changed is counted in the same way. The profile still needs a decision in a
terminal.

**8. The settings merge refuses `-0`.** A rewrite would turn it into `0`.

Recorded and not repaired, with the reason:

- Import knows a source by its exact label. Two labels that differ only in case or
  punctuation are two sources. Import was never released, so no person has notes under
  the older rule; a second import under a different spelling adds the notes again.
- A text that only looks like a metadata block at the top of a note body is read as
  the body. Only the first block of a file is metadata.
- A one-line `{...}` mapping with a value inside that is not JSON keeps a note or an
  import file private, also where it is valid and holds no privacy key (the Agent
  Skills format allows `metadata: {author: x}`; `{"author": "x"}` is read). Each form the reader takes apart is one more place
  where it can differ from a full parser, so this form waits for 0.6 with the random
  test as its gate. The same file with the mapping on indented lines is read.

A fifth review is over the limit of four that the owner's general rules set. The
builder ran one narrow check of these repairs because two leaks reached the fourth
review. It said "do not ship": the privacy reader still missed eight forms, and a
change to the outgoing check let a pasted private note be saved. Decision 4 above is
the answer to both. Its lesser findings (a draft as a start for neighbours, a lost
state reported only for a rule import, a link that leads nowhere, the list of sharing
values in this document) are repaired in the same change.

A sixth review, also over the limit, checked the reader of decision 4. It said "do not
ship" with 8 findings inside the bar. Two were leaks: the marker in the opening line,
and a private note pasted after a line of introduction. Four were costs: a fact saved
under a title with a byte order mark could not be read back, a text that opens with a
rule line and a link was refused, a valid agent file with a `{...}` mapping was
withheld without a reason, and `~` was missing from the list of sharing values. Two
were statements in documents. The text after decision 4 says what changed. The
`{...}` mapping is recorded above as a limit; import now names the file and the cure.
The builder did not run a seventh review. The random test now covers the place where
the sixth review found its leak, and the next useful check is a person who is not the
builder.

## The path to a release, planned backwards

Written on 13 November 2026, after six reviews. The owner asked for the goal first and
the path back from it. Review findings are not the goal.

**The goal.** A person who is not the builder installs the toolkit from the public
repository, connects one assistant, saves a fact, and gets it back in a new chat, in
ten minutes and without help. A week later they still use it. Then the owner announces
it.

Each step below needs the step under it.

| Step | Needs | Gap today | Who |
|---|---|---|---|
| 7. Announce | Step 6, and a package on the package index | No package is published. The name `twinaatma` on the index is not checked. | Owner |
| 6. Three to five people finish day one | Step 5, a one-page test script, a place for reports | The script is `docs/try-it.md`; reports come as issues on the repository. Only Claude Code was run for real; Codex, Cursor and Claude Desktop were not. | Owner invites |
| 5. A stranger can install what was built | `pip install git+https://github.com/Gargeya-Grey/TwinAatma` installs `main`, so the work must be on `main` | 39 commits are not pushed. They change code, tests, skills, documents, scripts and two workflows; no note folders. | Owner says yes to the push |
| 4. The pull request is green | The suite on Linux and Windows, Python 3.11 and 3.13 | The suite ran only on Windows with 3.13. The check of the privacy reader was skipped in CI, because CI had no YAML parser; CI now installs one. | Builder |
| 3. The last commit is proved here | Full suite, the first-day driver, one fresh install with a real chat | In progress on the day of writing. | Builder |

What this order changes:

- **No seventh review.** Each review found rarer faults in one part, the privacy
  reader, and each repair cost one run of the suite. That part now has a random test
  against a full parser that anybody can run again. A review is used again after
  step 6, on what real people report.
- **The measure is a stranger's first ten minutes**, then recall on day two. The
  largest known risks to that measure are not in the privacy reader: only one host was
  run for real, recall is by words and concept clusters (a question that shares no
  word with the note finds nothing), and the prompt hook is slow in a vault of
  thousands of notes, which is the vault of a person who already uses a note tool.
- **0.6 starts from the reports of step 6**, not from a list made by the builder.
  Candidates until then: recall for a question with other words, hook speed in a large
  vault, a `{...}` mapping in metadata.

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
