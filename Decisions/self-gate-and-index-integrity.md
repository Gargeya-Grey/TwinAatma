---
type: decision
title: Self gate is a ledger boundary, index freshness is a manifest
description: Two adversarial reviews found the same class of defect twice; this note records the structural fix.
id: kos:decision:self-gate-and-index-integrity
schema: knowledgeos-v0.3
status: active
created: 2026-10-17
updated: 2026-10-17
timestamp: 2026-10-17T00:00:00Z
tags: [decision, security, architecture, self-model]
project: TwinAatma
outcome_status: confirmed
outcome: Replace convention-based checks with state that cannot be forged; make freshness a manifest instead of a folder whitelist.
evidence: []
reversed_by: []
supersedes: []
---

# Self gate is a ledger boundary, index freshness is a manifest

## Context

Three adversarial reviews of this project produced the same score (52/100) across
different fix sets. The findings were not independent bugs; they were one design error
repeated:

| Check that was added | How the next review defeated it |
|---|---|
| "proposal must carry `proposal_origin`" | a string the proposal author types |
| "proposal must match the section hash" | `if expected and expected != digest` — an absent hash meant no check |
| "only drafts apply" | status was read from a substring the content controls |
| "extract the markdown block" | anchored to the *last* fence, so `rationale` won |

Every guarantee was a convention enforced against content the same actor controlled.
Adding a fifth convention invited a fifth bypass.

## Decision

**1. The ledger is the source of truth for Self proposals, and it lives outside the vault.**

`%LOCALAPPDATA%/TwinAatma/vaults/<vault-id>/self-proposals.jsonl` (or
`$XDG_DATA_HOME/TwinAatma/...`; `KNOWLEDGEOS_STATE_DIR`) records `id`, `section`,
`mode`, `base_digest`, `body_sha256`, `file_sha256` and `status` for every proposal, and
each row is signed with HMAC-SHA256 under a per-install key at `TwinAatma/gate.key`
(`KNOWLEDGEOS_GATE_KEY`). The markdown file in `People/Self-Proposals/` is only a
rendered view.

`<vault-id>` is a random id written to `.knowledgeos-vault.json` at `init`, not a hash of
the folder path. A path hash meant moving or renaming a vault silently orphaned every
pending proposal; a stable id survives the move, and vaults created before the change
fall back to the path hash and say so.

Two things had to move for this to mean anything:

- **The ledger left the vault.** Inside the vault it was a markdown-adjacent JSON file
  that any agent with `memory_capture`-grade write access could rewrite. Outside, it is
  a different trust domain.
- **The key is not the vault's.** Signing with a key stored beside the ledger would just
  move the forgery one file over. `gate.key` is per-install, mode 0600, and is never
  written into the vault.

Accept requires, in order:

1. a *verified* ledger row for that path — an unsigned, tampered or absent row fails, so
   a hand-written file and a rewritten ledger both cannot apply;
2. `status == draft` from the ledger, not from the file's text;
3. `sha256(fenced block) == body_sha256`, so editing the file on disk fails;
4. `sha256(whole file) == file_sha256`, so editing *anything* else in it fails too —
   including the frontmatter that says which section this is;
5. the section the file claims (`proposal_section`) must be the section the ledger
   recorded, so a proposal cannot be re-labelled to land somewhere else;
6. `section_digest(Self.md, section) == base_digest`, so a human edit in between fails
   (unconditionally — there is no "absent hash means no check" path);
7. `document_shape(Self.md)` unchanged — same headings, same `kos:section` markers
   before and after — and a patch with no visible characters is refused. Raw HTML
   headings (`<h2>`) are rejected outright: a renderer shows a heading, the shape check
   sees a paragraph, and the two disagree.

**1b. Approval happens in a terminal the model does not drive.**

`memory_accept_self_update` always refuses. Approval is
`twinaatma self approve <file>`, which requires **both** `sys.stdin.isatty()` and
`sys.stdout.isatty()`, shows a real unified diff of what the section will become, and
reads a `y/N` answer at the prompt. There is no `--yes` and no way to pipe the answer in:
piping makes stdin not a TTY, which is itself the refusal.

The check lives inside `gate._apply`, not only in the CLI. A guard that exists only in
the caller is a suggestion: importing the library skipped it, and there were two such
paths. It still cannot prove a human is present — an agent that can spawn and drive an
interactive terminal satisfies it — and the ADR says so rather than implying otherwise.

The first design here used an 8-character confirmation code, and it was wrong for a
simple reason: the code was returned in a tool result, so the model reads it. A secret
the model relays is not a secret. The parameter is gone from the tool schema rather than
left as a knob that does nothing. `authorized_by: terminal` in the ledger records which
path was used.

Applying writes through a temp file and `os.replace`, under a lock file, and marks any
other draft for the same section `superseded` so a second proposal is resolved rather
than stuck forever. The ledger is written *before* `Self.md`, and rolls back to `draft`
if the write fails. A proposal file that is a symlink, or hard-linked to anything
(`st_nlink != 1`), is refused — a hardlink to `Self.md` would make "apply a proposal"
into "write identity directly".

**2. Section identity comes from markers, not heading text.**

Writes resolve `kos:section=<key>` first. Alias matching is exact-normalised (`_name_key`),
not substring, survives only as a fallback for vaults that predate markers, and a
duplicate match is an **error**, not first-match-wins. Heading detection ignores leading
whitespace. The reader (`self_model`) and the writer (`gate`) use the same rule, because
they used to disagree: a heading like `Counter-Values I Reject` satisfied the `values`
alias by substring in the reader, so `memory_self_get` reported a section that
`gate.section_index` then could not find.

Patch content is rejected at propose **and again at apply** if it contains `##`, a `# `
H1, a setext heading (text underlined with **one or more** `=` or `---` — CommonMark
accepts a single `-`, and requiring three let `Text` + `-` through while the shape check
agreed there was no heading), a raw HTML heading in any form (`<h2>`, `<h2/>`, `<h2\n>`,
`<H2 class=…>`), a `kos:section=` marker, a `---` delimiter, a nested ` ```markdown `
block, an unclosed HTML comment, an unclosed code fence (everything after it renders as
code and hides what is stored), a bidi control, a format character (`Cf`: soft hyphen,
zero-width space, word joiner — a soft hyphen stored `dep\u00adloy` while drawing
`deploy`), a line with no ASCII and no letter or digit in it, or a control character
including the C1 block (U+009B is CSI, which an ANSI console executes). The SGR 8
"conceal" escape was a real bypass: it made a stored rule invisible on the approval
screen, so the human approved text they could not see. Apply-time revalidation matters
because a proposal can outlive the code that wrote it — the ledger is permanent, the rules
are not.

Vault-side content that a reader renders is not the only way to hide text; what the code
*imports* matters too. Cursor runs the hook at `.cursor/hooks/twin_session_start.py`, and
CPython puts the script's own directory first on `sys.path`, so a `json.py` dropped in
that folder was imported **by** the hook on every chat: code execution from vault content,
with `init` reporting no conflict because it only compared files it ships. Hooks are now
launched with `-P` (which stops the script's directory being prepended), and `init` and
`doctor` both report any unexpected file in that folder.

The frozen binary is not an interpreter, so it cannot be named as one: writing
`sys.executable` there produced `twinaatma.exe -P -E -s hook.py`, a command that does
nothing at all, and the hook silently stopped running. A binary install writes
`twinaatma hook <name>` instead, and the CLI runs the bundled script with `runpy` — no
second interpreter, and no vault directory on `sys.path` in the first place.

The "is this destructive" ratio counts **surviving old lines**, not total length. An
allow-list of blank-looking code points (U+3164 HANGUL FILLER, U+2800 BRAILLE BLANK, …)
lost the race to the next code point chosen: 400 U+034F COMBINING GRAPHEME JOINERs, or
400 U+FE0F VARIATION SELECTOR-16s, counted as visible text and bought consent for a
replace that deleted every rule in a section. Lines that survive cannot be padded —
padding adds lines, and only the old ones are counted.

`append` is `append_unique`: it returns `(body, changed)`, skips rows that are already
present, and preserves existing lines byte for byte, so a user's markdown hard-breaks
(`two spaces + newline`) are not silently reformatted.

**3. Extraction requires exactly one fenced block.**

Zero or two blocks means the proposal is ambiguous and is refused. Rationale text has
its fence openers neutralised when rendered, so it can never compete with the proposal.

**4. Index freshness is a manifest diff, not a folder whitelist.**

`.knowledgeos/index-manifest.json` stores `(size, mtime_ns, sha256)` per markdown file.
The hash matters: a same-size edit inside one filesystem timestamp tick is invisible to
`(size, mtime)` alone. Any change, addition, rename, or deletion in **any** folder is
detected. The old whitelist (`Inbox/Decisions/People/Projects/Concepts`) made `Research/`
edits invisible and left deleted notes in search results.

Capture indexes the new note immediately, so "captured now, searchable next breath" is
not the behaviour. Search also re-checks the manifest on **every** query rather than
trusting a database that another process may have outgrown. An earlier version throttled
that check to five seconds, which meant a note edited or deleted in the last five seconds
was still served — the throttle was there to save work that costs milliseconds.

The manifest covers every markdown file with a fixed hash budget: past 64 MB of total
content, remaining files are tracked by `(size, mtime_ns)` and marked approximate rather
than silently exempted.

Indexed text is the whole note body. A 1 MB per-note cap used to exist, so a long note
was findable by its first megabyte and invisible past it — a search that returns nothing
is indistinguishable from a note that does not exist.

Health is three-valued — `ok`, `corrupt`, `locked` — and only `corrupt` is quarantined.
Quarantine names carry a pid and a collision counter so two corruptions in one second
never overwrite the earlier backup, and `-wal`/`-shm` sidecars move with the database so
a fresh index cannot replay the old journal. Rebuilds take a lock file and use WAL, so
two processes cannot corrupt each other.

"Locked" is not a licence to be stale. While another process held the index, the freshness
check used to be skipped entirely, so a note deleted seconds ago was still served. A
rebuild is impossible then, so the read path filters its rows against the filesystem
instead: a handful of `exists()` calls, no lock, no write. That filter covers **every**
bucket `blended_search` returns, not just `ranked`: the metadata buckets (`title`, `tags`,
`project`, `description`) and the `fts` snippets carry note text too. The busy timeout is
two seconds, because a search that stalls for thirty behind somebody else's write reads as
a broken product.

The capture fast path reconciles deletions as well. It used to report `removed: 0` and
merge only its own signatures into the saved manifest, so a note deleted around a capture
stayed in the index *and* in the manifest, and the next freshness check called the vault
fresh while serving a file that no longer existed.

The file set is one function (`iter_markdown`) shared by the indexer, the validator and
`ids`. `rglob` follows directory junctions, so `ids assign --write` could rewrite files
*outside* the vault. `iter_markdown` walks without following links and confirms each file
resolves inside the vault. Its exclusions are equally literal: `AGENTS.md`/`README.md` are
product files and always skipped, `CONTRIBUTING.md`/`Changelog.md` are plumbing only in
the toolkit's own checkout, and a `*.new.md` conflict copy is skipped only when the file
it duplicates is actually beside it — otherwise a user's own `notes.new.md` existed on
disk and was never searchable.

FTS5 `unicode61` splits CJK into characters and drops emoji, so a CJK or emoji query
falls back to a substring scan instead of returning confident nonsense.

**5. A pre-warm is not a session, and drift is not a second-chat event.**

Host hooks call `breathe --prewarm`, which freshens the index but never records a
session or emits a soft prompt. The first real chat therefore stays silent, and the
weekly drift proposal cannot be triggered by a background warm-up.

"Weekly" means weekly: drift needs at least three real sessions **and** three days since
the first one. It used to fire on the second chat of the same afternoon, which reads as
noise rather than as a pattern. Once asked, a question is not repeated every session —
an open proposal stays open until the human acts, and re-asking it each chat is a chore
wearing a prompt's clothes.

A soft prompt may quote a note title, and note titles are attacker-controlled text that
lands inside the agent's own context. Titles are stripped of control and bidi characters,
collapsed to one line, and truncated before they are quoted. It is still *data*: the
prompt says "how did “…” turn out", and the quote is bounded so it cannot pose as a new
instruction block.

**6. The vault cannot turn itself into code.**

Cursor hooks live *inside* the vault and run on every chat, so they must never import
from the vault or its ancestors: hooks run `twinaatma` directly, or
`python -P -m knowledgeos` with `PYTHONPATH` set from the *installed package's* own
location. `-P` keeps the workspace off `sys.path`, so dropping a `knowledgeos/` folder
into the vault does not get it executed. The same reasoning applies to `setup-host`:
it refuses to emit a python fallback when it cannot guarantee `-P` (Python < 3.11), and
says so instead of pretending.

The same rule applies to *subprocesses*. On Windows, `CreateProcess` resolves an
unqualified executable against the current working directory before it consults `PATH`,
and every process this package starts runs with the vault as its working directory. A
file called `git.exe` in the vault root was therefore executed: the drift pass shelled
out to `git` on every chat, and `doctor` did the same. Vault content became code, which
is the exact thing this section claims cannot happen. All subprocesses now go through
`knowledgeos/safe_exec.py`, which accepts only an absolute `PATH` entry and refuses any
candidate inside the working directory. Nothing in the package calls `shutil.which`,
`subprocess.run("name")`, or `shell=True`.

`init` also no longer changes a vault's `vault_id`. Regenerating it on a re-run would
leave every pending proposal pointing at an old ledger key — unapprovable, with no
visible cause. Re-running `init` on an existing vault is a refresh: it fills in what a
newer version added and never overwrites.

## Threat model

This defends against **content-driven** mutation: an agent that read an untrusted note,
a lesson, or a tool result and was persuaded to change the identity layer. It also
defends against an agent using *tool calls* to complete propose → accept alone, which is
why approval left the tool surface entirely.

It does **not** defend against an agent that can run arbitrary shell commands as the
user: such an agent can call the library directly, or type into a terminal. No local
design survives that, and claiming otherwise would be the dishonest move. The boundary
is: the tool surface cannot change identity, and no secret travels through a tool result.

One consequence is worth stating without varnish: the ledger's HMAC key sits on the same
filesystem as the vault, so an agent with shell access can read it and forge a row. That
row is inert on its own — applying it still needs a terminal — but it means the ledger
detects tampering from *vault-side* content, not from a local shell.

It does not defend against the vault owner, who edits `Self.md` in Obsidian by design.

## Consequences

- **You approve identity changes in a terminal, once.** That is a real cost, and it is
  the price of the agent not being able to rewrite who you are. Everything else stays
  zero-command.
- Legacy proposals in `People/Self-Proposals/` are listed as `untrusted` and cannot be
  accepted. They must be re-proposed. Deliberate: silently trusting them would reopen
  the bypass.
- Proposals created before the ledger moved outside the vault are unsigned and therefore
  unverifiable; they are reported, not deleted.
- Applying a proposal preserves the file's existing line endings. Writing `Self.md` with
  `Path.write_text` translated every `\n` to `os.linesep`, so approving one appended line
  rewrote all 55 lines of an LF identity file as CRLF.
- A moved or renamed vault keeps its pending proposals: the ledger is keyed by a
  `vault_id` written at `init`, not by the folder path. Older vaults without one fall
  back to the path hash and say so.
- A generated `.cursor/mcp.json` records an absolute vault path. If that path no longer
  exists (the vault moved or was opened on another machine), the server falls back to
  walking up from its working directory instead of failing every call.
- `memory_list_self_proposals` returns `{open, untrusted}` instead of a bare list.
- `init --force` never overwrites; conflicting generated files are written as `*.new`
  and reported under `conflicts`, including `.cursor/hooks/*` and `hooks.json` — a
  silent hook swap would be silent code execution. A file `init` did *not* install but
  that sits in `.cursor/hooks/` is also reported: it is on the hook's import path.
- A `People/Self.md` that is a directory, a link, or unreadable yields `{"error": …}` from
  the read and propose paths instead of a traceback. `exists()` is true for a folder, and
  `IsADirectoryError` arriving through an MCP tool result is a crash, not an answer.
- The `updated:` rewrite on apply touches the frontmatter only. A `re.sub` over the whole
  document rewrote the first line anywhere in the file that began with `updated:`, which
  could be a rule the user wrote.
- `setup-host` writes to the host's project config (`.cursor/mcp.json`), and HTTP
  transport reports "not implemented" instead of emitting a URL for a `serve` command
  that never existed.
- `ids assign` skips `People/`, so no command other than the gate rewrites `Self.md`.
- Applying writes through a temp file created with `mkstemp` (`O_EXCL`, unpredictable
  name) and verified to be a single-link regular file. The temp name used to be
  `<proposal>.gate-write` — predictable from `proposal_path` — and `reject` has no
  terminal check by design, so an agent could hardlink `Self.md` at that name and have the
  final `os.replace` rename the identity file over the proposal. One tool call, no TTY.
- `propose` validates `People/Self-Proposals` the same way apply and reject do. It used to
  `mkdir` whatever path it was handed, so a junction there made a tool call write a
  proposal file outside the vault.
- The ledger write no longer rebuilds the file from the verified working set. Rows that
  failed verification — a different signing key, a tampered row, a row from another
  machine — were silently dropped on the next write, so a pending identity edit vanished
  from `self pending`. They are preserved byte for byte and reported as rejected.
- Text that is stored but never drawn cannot carry a proposal. HTML comments (including
  the multi-line form opened by `--><!--`) and Obsidian `%%…%%` are refused, the
  destructive ratio counts *rendered* survivors, and the approval diff diffs rendered
  text. A patch whose old rules sat inside a comment looked non-destructive to every
  source-line check and showed two removals of blank lines on screen.
- Every row-returning tool filters deleted notes, not just `search`: `timeline`,
  `decisions`, `related`, `bootstrap_context` (all three buckets), `pending_outcome_reviews`
  and the `recent_notes` fallback. The filter was added to `search` first and the rest
  kept serving dead rows while another process held the index.
- Note signatures hash the whole file. Sampling the first and last 4 MB of notes over 8 MB
  reintroduced the very bug it was meant to fix: a mid-file edit with size and mtime
  preserved was reported `fresh` forever.
- Raw HTML is refused outright rather than tag by tag. Refusing `<h1>…<h6>` was one
  round of the same bug: a patch that wrapped the retained rules in
  `<script>…</script>`, or in `<div style="display:none">`, passed every source-line
  check, scored as non-destructive, and showed only blank-line changes on the approval
  screen, while a reader saw none of the old rules. Since the only legitimate use of
  markdown here is prose, the honest rule is "no markup", which is also checkable
  without a renderer. `rendered_text` still strips those constructs, so the ratio and the
  diff stay honest for a body that predates the rule; the refusal is what makes them
  moot.
- A code fence closes only on a run of the same character at least as long as the opener
  and followed by nothing but whitespace. Counting fence *lines* for an even number made
  a four-backtick opener closed by three backticks look balanced, while CommonMark leaves
  it open to the end of the document and turns every later section into code.
- `index_state` probes with `BEGIN IMMEDIATE`, not `SELECT count(*)`. Under WAL a reader
  succeeds while a writer holds the database, so the old probe said `ok`, the caller went
  on to rebuild, and the rebuild blocked for the whole busy timeout before answering the
  user's first message with `OperationalError: database is locked`. A failed rebuild is
  now a normal state (`index_locked`), and the read paths filter rows against the
  filesystem instead.
- `Inbox` is a sandboxed path before it is a directory. It was a plain attribute, so
  `mkdir(parents=True)` and `write_text` followed a junction and wrote the file *before*
  containment was checked — a write outside the vault reported as an error. The same
  helper now guards `capture` and `propose_note_update`.
- Every write of a file the user owns preserves its line endings. `Path.write_text`
  translates `\n` to `os.linesep`, so a capture into an LF vault arrived with CRLF pairs
  and `ids assign --write` rewrote every line of a file for a one-field change. The rule
  is stated once in `knowledgeos/textio.py`.
- The frozen binary names the vault in the hook command (`twinaatma hook <name>
  --vault <path>`). A hook script derives its vault from `__file__`, which under `runpy`
  from the bundle is the extraction directory: the hook ran, reported success, and
  pre-warmed a vault that did not exist, so the chat had no memory in it.
- `PRODUCT_FILES` is `AGENTS.md` only. Skipping every root `README.md` hid the user's
  own, while `memory_get_note` read it — search and the reader disagreed about what a
  note is. The toolkit-only names moved to `ROOT_SKIP_FILES`, gated on
  `_is_toolkit_repo`, which is what that helper already existed for.
- The validator has no skip list of its own. Two lists drifted (`.cursor`, `docs`,
  `.commandcode` were in one and not the other), so `validate` and `search` described
  different note sets in the project whose whole argument is that there is one.
- U+200C and U+200D are allowed when a neighbour is outside ASCII and refused between
  ASCII letters. Every `Cf` was refused, which made a family emoji or a Persian word
  unproposable with an accusation of deception; the joiner is the same hiding trick only
  in the second position, and the neighbour is what tells the two apart.
- A busy gate answers `{"error": "Self gate is busy; try again in a moment",
  "retryable": true}`. It raised `TimeoutError`, whose type name reached the agent as
  part of the message and read like a crash.
- The CLI never fails to render because of a character. The approval screen prints the
  current section of the user's `Self.md`, so it prints whatever they wrote; the starter
  kit already contains `Capture → Decide`, and a Windows console on cp1252 raised
  `UnicodeEncodeError` inside `_self_approve` and killed the binary with a PyInstaller
  traceback. Failing to show the diff is a security failure for the one command whose
  whole purpose is "read this before you say yes". Output is reconfigured to
  `backslashreplace`, so the character is still distinguishable.
- `input()` raises `EOFError` when stdin is closed, which is the normal state of a CLI
  run from an agent or a scheduled task. That reached the human as a traceback. Being
  unable to ask is the same answer as "no".
- Hook *code* is not shipped into the vault any more. `init` used to copy
  `twin_session_start.py` into `<vault>/.cursor/hooks/` and point `hooks.json` at that
  copy, which made any write to that path a change to the program the next chat runs —
  a vault an agent can write holding the code that agent's session executes. A digest
  check cannot repair that: the compromised file is the thing doing the checking, and it
  runs before anything else. The hook program now lives in the installed toolkit and the
  vault holds only `hooks.json`, which is configuration the host reads. `doctor` reports
  executable hook code left in a vault by an older install instead of blessing it.
- Every state write goes through one atomic writer. `.knowledgeos/autopilot.json.tmp`
  and its siblings were names any agent could compute, and `breathe` persists the
  agent's own `task_hint` on every session start. A hardlink from `People/Self.md` to
  that name turned an ordinary tool call into a complete identity rewrite with no
  proposal and no terminal; `index-manifest.json.tmp` and `gate`'s signing-key and
  ledger temp names were the same shape. `knowledgeos.textio.atomic_write` picks an
  unpredictable name, verifies with `fstat`/`lstat` that it is a single-link regular
  file, and only then replaces. `propose` also refuses a hard-linked `Self.md`, which
  `_apply` already did.
- `.knowledgeos` is containment-checked like `Inbox`. `mkdir(parents=True)` follows a
  junction, so a junctioned state folder made `breathe` write `autopilot.json` and
  `index-manifest.json` outside the vault and report success for every call.
- A lock the index cannot take is a reported fault, not "busy". `os.open(...,
  O_CREAT|O_EXCL)` on a directory raises `PermissionError`, not `FileExistsError`, so a
  single `mkdir` at `.knowledgeos/index-rebuild.lock` stopped every rebuild for good:
  the error escaped one caller, was caught-and-dropped in `breathe`, and `doctor` kept
  printing a healthy index. It now raises `IndexLockUnusable`, `breathe` marks the tick
  `blocked`, `ops_status` says so in plain language, and `doctor` fails the check.
- A locked index refreshes body snippets from the file. A row that quotes note text
  survived an edit because `exists()` is true for a modified file, so `search` returned
  the old sentence while `get_note` returned the new one — the same note described two
  ways, and the stale half is the one an agent quotes.
- Append shows and stores the same text. `append_unique` `rstrip()`-ed each added line,
  so the approval screen showed `* Handled by email  ` and the file got `* Handled by
  email` — two trailing spaces are a markdown hard break. The preview is now the
  `section_body` of the file that would be written, not `before + patch`, and an append
  that changes nothing returns an error and leaves the draft open instead of reporting
  `ok`.
- A heading inside a blockquote or a list item is still a heading. `> ## Anti-Goals` and
  `- ## Anti-Goals` render as sections while starting with `>` or `-`, so every "starts
  with `#`" check called them ordinary text; container markers are stripped before
  asking.
- Docs are checked against the code by `tests/test_docs.py`; a documented command or
  tool that does not exist fails CI.

### Round eleven

- The approval screen and the apply path read the section from one place. `_preview_diff`
  scanned the whole proposal for the last `proposal_section:` / `proposal_mode:` line,
  while `_apply` used the ledger. A summary string that happened to start with
  `proposal_mode: append` therefore changed what the human was shown without changing
  what happened: the screen said "3 kept, 1 added" over a section that was emptied. The
  two are now the same signed ledger row (`gate.describe`), and frontmatter lookups stop
  at the closing fence instead of scanning the first forty lines.
- A destructive waiver is named on screen and confirmed separately. `allow_destructive`
  is an argument the *agent* supplies; the screen offered the same single `y` for a
  replace that keeps every line and one that empties the section. The waiver is now
  recorded in the ledger, printed as a `DESTRUCTIVE` line above the diff, and the
  confirmation becomes `yes-wipe`.
- No size at which freshness checking is silently switched off. Past the hash budget,
  `manifest_diff` compared `(size, mtime)` and returned `fresh` for files it never read,
  so an equal-size edit with a restored mtime was invisible forever. Every file with a
  stored digest is hashed; exceeding the budget is reported in the reason
  (`fresh_over_budget:<bytes>`) rather than weakening the comparison.
- A locked index refreshes metadata, not just snippets. Only rows with a `snippet` key
  were re-derived, so while another process held the index `search` returned a hit whose
  own `tags` field named a tag the note no longer had, and `index_blocked` stayed `None`.
  Rows are now refreshed per row from the file, the match must still be present, and the
  same refresh applies to the project and decision lists `bootstrap_context` builds.
- `doctor` fails on a missing identity section. It printed `PASSED` and exited 0 while
  proposals for that section could not be made — the command whose whole job is to say
  whether the install works was reporting success on a vault that could not take a
  preference.
- `session_end` reports a prompt, not a tuple. It stored `(prompt, key)` where
  `session_start` unpacks it, so `ask_human` was always truthy and printed as a Python
  tuple.

### Round twelve

That round's reviewer crashed before writing its report, leaving its probe scripts
behind. The defects below are transcribed from its measurements, and the first is a
regression introduced by the round-eleven fix.

- A frozen index does not turn a stem into a miss. The round-eleven refresh asked
  `query in text`, which is a different question from the one FTS5 answers: the index is
  `porter unicode61`, so a note saying "reviews" matches "review". With the index held by
  another process, `reviews`, `reviewing` and `deploys` returned nothing at all while the
  note sat on disk. The refresh now asks the same question the index does.
- `decisions()` filters on the files, not on frozen SQL columns. Closing a decision and
  moving it to another project left `decisions(project='alpha')` still returning it and
  `decisions(project='beta')` returning nothing. Re-filtering after a refresh could not
  help, because the SQL had already discarded the row; the query is widened to the whole
  decision set and the caller's filters are applied to the refreshed values.
- `related()` reads its edges from the notes while the index is frozen. Dropping a
  neighbour whose file was gone was not enough. Removing a link still left its former
  neighbour in the answer for as long as anything held the index. The flag was also read
  before `_conn()` had probed for freshness, so the file-based branch was never taken on
  the first call.
- One stray CRLF no longer rewrites a file. `dominant_newline` asked whether a CRLF
  existed *anywhere* and then wrote the whole file with it, so a single line pasted from
  Notepad into an otherwise-LF note made an approved append convert all 49 lines. It
  counts now, with ties to LF.
- The freshness manifest is signed. It decides whether search rebuilds and it lives
  inside the vault, so an agent that can write notes can write it. Rewriting it to match
  an edited file made search go on serving "a human reviewer must sign off" from a
  note that now said deploys were automated, with `index_locked` false and `doctor`
  printing PASSED. An unsigned or mismatched manifest is not trusted; that sends the
  caller down the rebuild path, which always produces the truth.
- A frozen index says so. Rows are refreshed from the files, so quotes are current, but
  a note added since the freeze cannot appear at all and the payload was indistinguishable
  from a complete answer.

### Round twelve, second pass

That round's first reviewer crashed before reporting; a retry finished and found the
largest defect of the series. It is worth recording in full, because it is the one where
the tests, the scorecard and `doctor` were all green at once.

- **The index database was a second, unsigned content authority.** The manifest signed
  the *files*, not the index, and the rebuild trusted a `notes.file_hash` column that
  lives in the same writable database. One statement —
  `UPDATE notes_fts SET body = 'Deploys require a human reviewer to sign off in writing.'`
  — was enough to make `search` quote a policy no note contained, keep quoting it through
  two full `rebuild_index()` calls that both returned `fts_updates: 0`, and hand the same
  forged sentence to the agent as "Self heuristics". It also worked in the other
  direction: searching for the sentence the note *did* contain returned nothing, because
  the forged text had replaced it in the full-text table. `manifest_diff` said `fresh`
  and `doctor` exited 0 throughout.
- The manifest now carries a digest of the index's rows, inside its HMAC, and
  `manifest_diff` compares it. A rewritten index reads as `index_tampered` and forces a
  rebuild. The rebuild no longer trusts `file_hash`: it corroborates each stored body
  against the note it claims to come from and re-extracts anything that does not match.
- More fundamentally, **every row a read path returns is now re-derived from the file**,
  not only while the index is locked. `index_locked` answers "is another process
  writing?", which says nothing about whether the rows are true. The index selects
  candidates; the note supplies every word shown. That is what makes a quoted sentence
  the user's own.
- Forged *metadata* was the same class: resetting `notes.status` and
  `notes.outcome_status` reopened a decision closed in the note, so
  `memory_pending_outcomes`, `ops_status` and the soft prompt all asked the human
  "Quick check — how did Pick vendor turn out?" about work they had finished.
  `bootstrap_context` had the predicate baked into its SQL, so its list disagreed with
  the tools in the same session. Every list is now widened, refreshed from the notes, and
  filtered on what the notes say.
- The stem check used `any(stem)`, so a note that had lost a word still matched a
  multi-word query. It now asks SQLite with the index's own `porter unicode61` tokenizer
  on a throwaway in-memory table — exact, and unable to drift from the index. CJK and
  emoji fall back to the same substring test the index uses for them.
- A template counted as a decision, so a fresh vault reported an open outcome before the
  human had decided anything.
- `.knowledgeos` replaced by a plain file made every session tool answer
  `{"error": ...}` while `doctor` printed PASSED. It is now an `[ERROR]` with a
  non-zero exit.
- The proposal ledger was keyed on `.knowledgeos-vault.json`, a file inside the vault.
  Rewriting 32 bytes of it moved the ledger path, and every pending Self proposal
  silently disappeared — `list_self_proposals` returned nothing open, `ops_status`
  counted zero, `doctor` passed, and `self approve` refused the file it had just written
  as "not registered in this install's ledger". A gate whose list of pending approvals
  can be emptied by one vault write is not a gate. The binding is now recorded once in
  install state, outside the vault; the marker is consulted only the first time, and a
  later disagreement is reported rather than obeyed.
- `decisions`, `timeline` and the pending-outcome list answered from a held index without
  saying so, so a decision created since the freeze could not appear and the payload
  looked complete. They carry `index_frozen` now, like `search`.

## Verification

`tests/test_core.py` and `tests/test_docs.py`, plus a CI matrix on
Windows/Linux with Python 3.9 and 3.13 and a binary job that builds and initializes a
vault. Every guarantee in the README names the test that proves it, and
`test_docs.py` fails if a named test stops existing. The gate tests are adversarial:
forged ledger rows, hardlinked proposals, symlinked `Self.md`, invisible patches,
whitespace-hidden headings, raw HTML headings, bidi overrides, a padded patch that tries
to buy consent for a wipe, a comment-hidden wipe, a planted `json.py` in the hooks folder,
a hardlink planted at the write temp name, a second signing key, a proposal edited
after signing, a vault moved mid-proposal, a non-TTY approval attempt, and an MCP accept
that tries to supply a confirmation code that no longer exists. Round nine added a
`<script>`-hidden wipe, a mismatched fence length, a real `BEGIN EXCLUSIVE` writer held
against a live index, a junctioned `Inbox`, a frozen-binary hook pointed at a vault, a
user's root `README.md`, and an emoji whose joiner used to be refused. Round ten added
the hardlink-to-state case, a replaced vault hook script, a hook run from the installed
toolkit, a `.knowledgeos` junction, a lock path that is a directory, an edited note under
a locked index, and a blockquote-nested heading. Round eleven added the summary-smuggled
section, the frontmatter fence boundary, the destructive confirmation word, the hash
budget, removed metadata under a locked index, the `session_end` tuple, and a missing
identity section. Round twelve added stemmed hits under a frozen index, decisions that
moved project, a deleted link, a stray CRLF, a forged manifest, and the frozen-index
notice; its retry added a forged index body that survived rebuilds, a forged row that hid
a real note, forged decision metadata that reopened a closed decision, a nag about a
decision already finished, a template counted as a decision, a file where the state
folder belongs, and a vault marker that orphaned pending proposals. Round thirteen added a
forged `notes`/`notes_fts` metadata column, a capture that re-signed a tampered index, a
prefix hit lost by the refresh, a deleted `notes` row that survived a rebuild's
reconcile, a directory at the database path, mixed line endings flattened by one
approval, and an undecidable query that counted as a match. Round fourteen added a YAML
block-list property that emptied the index, a title that lived only in a filename or an
H1, a healthy report for a zero-row index, a harness that called a syntax error a caught
mutation, a CRLF file that gained an LF line per approval, `NULL` colliding with the word
`None` in the digest, and a rebuild that happened without saying so.

### Round thirteen

Round thirteen scored 26/100 with the identity dimension at 90 and truthfulness of reads
at 12. The pattern in that split is the whole finding: the things protected by an explicit
human confirmation were solid, and the things protected by a cache were not.

- **The cache was the authority, and it vouched for itself.** Round twelve's fix
  corroborated the *body* of every index row against the note. Every other column —
  `title`, `type`, `status`, `tags`, `project`, `description`, `updated`, `created`,
  `outcome_status`, `review_after` — was served straight from the writable database.
  One `UPDATE notes SET type = 'decision'` put a project note in `memory_decisions`; one
  `UPDATE notes_fts SET title = ...` made `search[ranked]` return a title that existed
  nowhere while `search[title]`, in the same payload, returned the real one. It went
  deeper than the body fix, because `notes.file_hash` — the column the rebuild used to
  decide a row was unchanged — lives in that same database. Editing the row *and* the
  hash made the rebuild skip re-reading the file, so the forgery survived
  `rebuild_index()` and the digest was then recomputed and re-signed over it.
- **The alarm was one-shot.** `index_files` (the fast path used by `memory_capture`)
  recomputed `index_digest` over whatever rows it found and saved a new signature, so
  `manifest_diff` went from `index_tampered` to `fresh` after one ordinary capture. An
  attacker needed exactly one write and one capture, and from then on the manifest
  claimed to have verified an index that still disagreed with the notes.
- **The repair made things worse for prefixes.** Metadata buckets are found with
  `LIKE '%query%'`. Re-testing the matched field with the full-text matcher is a
  strictly stronger question — `unicode61` tokenises `Depl` as its own token, which is
  not `Deploy` — so the refresh dropped 24 of 526 real matching pairs on a realistic
  vault, including every three-letter tag prefix.
- **A rebuild reconciled the wrong set.** It reconciled `notes` and left `notes_fts`
  alone, so deleting one `notes` row removed a note from `decisions` forever while the
  full-text index still had it.
- **`st_size == 0` is true for a directory.** `index_state` therefore called a directory
  at the database path "missing", `doctor` printed "Index missing; rebuilt automatically",
  and every rebuild raised `unable to open database file`. The report that exists to tell
  a human something is wrong said nothing was wrong.
- **A "dominant line ending" rewrote the user's file.** A `Self.md` with 25 CRLF lines and
  24 LF lines became 50 CRLF after one approved append. The diff is computed on
  normalised text, so the screen showed one added line and the file had moved 49.

The fixes follow from one sentence: an index is a cache, and a cache cannot vouch for
itself. So the writable `file_hash` cache is gone (measured cost: +244 ms on a 1.2 s
rebuild at 800 notes — cheap enough that an authoritative rebuild is the right default);
`index_digest` now hashes every column of `notes`, `notes_fts` and `links`, not just the
paths; `index_files` compares the current digest with the signed manifest *before*
touching anything and hands off to `rebuild_index` when they disagree, so a capture can
only ever repair, never certify; every row returned by a read refreshes every displayed
field from the file and re-tests the field that matched using the same substring rule the
index used to find it; line endings are preserved per line rather than flattened to the
dominant one; and `doctor` opens the database it is reporting on.

Two process notes worth keeping. First, the scorecard said **100.0/100 across 43
scenarios while this critical defect was live** — the second time it has done that
(round twelve's retry was the first). No scenario asserted that a *metadata* column had to
survive a refresh, because the author of the corpus had only thought about the body. That
is not a reason to trust the corpus less; it is the reason the reviewer stays in the loop.

Second, and more useful: when the round-thirteen fixes were added to
`tests/mutation_check.py`, **four of the new mutations stayed green**. The scenarios were
passing for the wrong reason — a read-path refresh masking an index that was still
forged, a metadata fallback rescuing a row that the reverted branch had just dropped. The
honest response was to strengthen the scenarios to assert the thing that actually matters
(the stored row agrees with the note; the index is repaired, not merely not-quoted) and,
where two mechanisms held one claim, to make the mutation remove *both*. That also turned
up a real harness bug: a mutation that edited the same file twice restored the first
edit's mutated text over the second, quietly poisoning the copy for every later entry.
The harness had been reporting false BLINDs against itself.

### Round fourteen

Round fourteen scored 17/100 with truthfulness of reads at 5. Two CRITICALs, and neither
was a forgery. That is the finding: after three rounds of hardening the *read* path
against a writer who edits the index, the product was still lying because of the ordinary
notes it was reading.

- **One note with a YAML block-list property turned the index off for the whole vault.**
  `_process_file` coerced `tags`, `project` and `lesson` to text and handed every other
  field to `sqlite3` as-is. YAML produces a Python `list` for
  `description:\n  - cost\n  - risk`, which `parser.py` advertises as supported, and
  `sqlite3` raises `ProgrammingError: Error binding parameter 9: type 'list' is not
  supported`. The rebuild failed for *every* note. A 42-note vault ended with zero rows and
  no manifest at all.
- **And the failure was reported as something else.** `_try_rebuild` catches every
  exception as "the index is busy", because that was the only failure it had been taught
  to expect. So `search` answered `index_frozen: true` with the note *"Another process is
  using the note index"* — a diagnosis that names a culprit which does not exist — while
  `doctor` printed `[OK] Index healthy` and exited 0. Three layers each had a plausible
  local reason to say the reassuring thing.
- **A title that lives in the H1 or the filename was unfindable and unnamed.** The index
  derives `title` from frontmatter, then the first `# `, then the filename stem, and
  matches it with `LIKE '%query%'`. `_refresh_rows` re-tested only the *frontmatter*, so
  `Concepts/Deployment runbook.md` (no `title:` key) was found by the index and then
  dropped by the refresh: `Deployment`, `Depl`, `eplo` and `runbook` all returned `[]`.
  Separately `_refresh_display_fields` set the displayed title to `""`, so every result for
  such a note came back nameless and an agent had to tell ten notes apart by path.
- **`[OK] Index healthy` for a database with zero rows.** `index_state` proves the
  database takes a write lock and has the right tables. It says nothing about whether it
  holds the vault. Three `DELETE`s produced `[OK] Index healthy (126976 bytes)` and exit 0
  in a 41-note vault while every search returned `[]`.
- **The mutation harness could not tell a failed claim from a crashed process.** It tested
  `if code != 0`, and `score.py` exits 1 for a traceback and 2 for an unknown scenario id.
  The reviewer fed it a mutation that did not compile and a scenario id that does not
  exist; both printed `caught`. Reading the verdict out of the scorecard instead
  immediately surfaced a stale entry that had been reporting `caught` for nothing.
- **Every approval added one bare-LF line to a CRLF file.** `new_lines` was split from text
  whose CRLFs had already been normalised to `\n`, so each new line ended in `\n` and the
  `line + ending` branch never ran. On a Windows vault — the default install — that
  happened on every single append, and a file whose last line had no terminator lost 26 of
  its 48 CRLF lines in one approval. Round thirteen fixed the *reverse* case and this is
  the same function one branch over.
- **`str(value)` is not injective.** A `NULL` description and the four characters `None`
  hashed to the same bytes, so `UPDATE notes SET description = 'None'` was invisible to the
  digest that exists to notice it.
- **A missing digest was a silent 26-second capture.** With no signed digest to compare
  against, the capture path correctly falls back to a full rebuild — but said nothing, so
  the caller saw only latency.

The fixes are small and they share a shape: **answer the question you were asked.** Every
field is coerced to text before it reaches SQL (all nineteen, not the three the author
happened to think of); the refresh tests the same three title sources the index used, and
the displayed title falls back to the same derivation; `doctor` compares the row count
against the notes on disk and says "incomplete"; the digest tags and length-prefixes each
value; the rebuild sets a `rebuilt: no_signed_digest` field so the pause is explained; the
new lines adopt the file's dominant ending while untouched lines keep their own bytes; and
the mutation harness requires the named scenario to record a `FAIL`, not merely a non-zero
exit.

One process note. The corpus went from 50 to 56 scenarios and from 31 to 36 mutations, and
for the first time the stricter harness *found* a defect in the corpus rather than
confirming it: one mutation pointed at a scenario id that had been renamed, and had been
reporting `caught` on a check that could not run. A harness that grades itself on
exit codes will always be able to go green on a tree that does not import.

### Stabilization after round fourteen

The round-fourteen closeout overstated completion. Further failing tests reproduced
permanent rebuild errors still described as contention, unreported partial rebuilds,
cached `entity_id` values, candidate paths that could escape the vault, and line-ending
damage between disjoint edits. The line-ending writer had also bypassed the atomic
replacement routine. These are now covered by checked-in behavioral scenarios and
`tests/test_stabilization.py`, including seeded newline round-trips and recovery tests.

The writer now matches unchanged lines throughout the document, preserves a missing final
terminator, supports CR-only files, and stages exact bytes through atomic replacement.
Read candidates pass the sandbox boundary before opening. Failures name the real fault;
partial rebuilds retain their failed-path list instead of being called successful. Doctor
compares metadata and full-text coverage, and schema validation executes a full-text query
instead of trusting the word `fts5` in table-definition text.

The verifier now requires a passing baseline before applying mutations, an unambiguous
edit anchor, exit 1 with an actual named assertion FAIL, and a passing restored tree.
Scenario crashes, unknown IDs, malformed output and contradictory exit codes fail the
harness. Staging-file restoration preserves the original bytes. The regression suite and
the complete mutation check are CI gates, not temp-only probes. The unchanged six weights
initially produced 100.0/100 across 64 scenarios (one platform skip), with 44 targeted
reversions caught. That was corpus coverage, not a product certification.

One packaging claim also had to be withdrawn: earlier temp scripts accepted arguments but
actually used hard-coded paths to older artifacts. Their results did not verify the latest
build. `tests/package_smoke.py` now requires an explicit wheel or executable, records its
SHA-256, uses a neutral working directory, and can compare every wheel module with the
source bytes. Fresh builds of the frozen stabilization snapshot passed 57 wheel checks
and 27 binary checks on Windows/Python 3.13. Cross-platform and Python 3.9 checks remain CI
work, not claims of local execution.

The product snapshot was copied and hash-verified before independent review. Changes made
while that review ran were limited to documentation and verification/CI support; product
code and the live identity file were kept unchanged. Independent review scores remain
separate, explicitly scoped judgments under the declared weights, not the deterministic
corpus pass rate.

The independent review then found six additional defects: drift still served cache titles;
ID resolution trusted cached mappings; pending outcomes trusted cached classification;
failed quarantine could be mistaken for a successful rebuild; list lessons broke promotion;
and timeline dropped recent-created/old-updated notes. Its weighted score was 92, correctly
capped at 40 because a headline truthfulness claim was demonstrably false.

All six received failing regression tests, behavioral scenarios, repairs, and targeted
mutations. Explicit ID lookups now scan files and refuse duplicates. Drift and timeline
verify fields and reapply their predicates before limiting. Pending/lesson lists verify
file-derived type; list lessons normalize before string operations. Quarantine failure
raises, final state is checked before signing, and FTS availability is executable rather
than inferred from a table name. The corpus now contains 71 scenarios and 51 targeted
reversions; 21 stabilization tests also exercise failure/recovery and the verifier itself.

The same independent reviewer replayed its original ten probe groups against a new
hash-verified snapshot and added three seam-probe groups. All six findings were fixed;
no new confirmed severity finding was demonstrated. Its scoped judgment was **100/100,
no cap**, under the same six weights. This reaches the requested 90+ review target without
substituting the green corpus for independent judgment. The scope limits, initial capped
assessment, revalidation provenance, and separate packaging evidence are retained in
`tests/reviews/stabilization-2026-10-18.md`. This remains a bounded review, not certification.

The suite is necessary and not sufficient, and it is worth being explicit about why:
fourteen rounds of defects above were found by adversarial review *while all tests passed*. A test
asserts what its author thought to assert. `test_locked_index_does_not_serve_a_deleted_note`
checked `ranked` and not the other five buckets; `test_hook_does_not_resolve_the_working_directory`
grepped for `shutil.which(` and could not see `sys.path` shadowing. Both were green with
the bug live. The lesson is not "write more tests" — it is that a guarantee needs an
adversary who is trying to break it, not only an author who is trying to keep it.

What changed after round eleven is that the lesson now has a mechanism. `tests/score.py`
turns each guarantee into a scenario and reports one deterministic number, so "is this
better than yesterday" is a diff rather than a memory; `tests/mutation_check.py` reverts
each known defect and fails if the matching scenario stays green, so the corpus cannot
quietly become decoration. The scorecard still cannot see a class of bug nobody imagined
— it found none of the defects above by itself, and the round-twelve retry is the proof:
it reported 100.0/100 across 34 scenarios while a one-line write to the index let the
product quote text that existed nowhere, and again at 100.0/100 across 43 scenarios
while one write to a metadata column made the product describe notes as things they were
not. So the adversarial reviewer remains the thing
that finds new classes, and the scorecard is the thing that stops the same class being
paid for twice. When a reviewer finds a class, a scenario is written *and a mutation that
reintroduces it must go red* before the fix is considered done.
