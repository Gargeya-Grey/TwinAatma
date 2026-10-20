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
**Technical package:** `knowledgeos` (legacy name; may appear in schema ids and paths)

**Your job:** wire the MCP Memory server once.
**The agent's job:** load your Self, search memory, capture what matters, propose twin updates, and ask only for high-leverage yes/no. See [AGENTS.md](AGENTS.md).

Local-first cognitive memory: markdown you own, an MCP Memory API any agent can call, and a Self-model updated through explicit yes/no — never silent rewrites.

---

## 🔌 One-time setup

Pick one:

**A. Binary (no Python required)**

```bash
twinaatma init C:\Users\you\brain --name "Your Name"
cd C:\Users\you\brain
twinaatma setup-host --host cursor --write
```

**B. From source (Python 3.9+)**

The library and CLI run on 3.9. Generating an MCP server command from a *source checkout*
needs 3.11+, because it uses `python -P` to keep the vault off `sys.path`; on 3.9/3.10 use
`pip install -e .` (which installs a console script) or the packaged binary instead.

```bash
pip install -e .
twinaatma init ./my-brain --name "Your Name"
cd ./my-brain
twinaatma setup-host --host cursor --write
```

`init` creates the folders, `People/Self.md`, Agent rules, the Cursor hook *config*, a
project MCP config at `.cursor/mcp.json`, and a ready search index. It never overwrites
an existing file — conflicts are written beside the original as `*.new` and listed in the
output. `--dry-run` shows the plan and changes nothing.

The hook **program** is not part of your vault. `hooks.json` points at the copy inside
the installed toolkit, so writing a note can never change what runs on your next chat —
a vault an agent can write must not hold the program that agent's next session executes.

Then **just chat**. Autopilot keeps the twin current:

| Ritual | What happens |
|---|---|
| Chat starts | Host pre-warms the index; the agent's first tool call loads Self + relevant memory |
| During chat | Captures + search without you managing folders |
| Preference change | Soft “Want me to remember that?” → yes/no |
| Chat ends usefully | Session summary saved; index freshened |
| ~Weekly | Activity reviewed without inferring a belief change |

Agents follow `AGENTS.md` / `.cursor/rules` / MCP `instructions`. You should not manage
indexes, scripts, or cadences after setup.

---

### Codex project setup

From the vault directory, run `twinaatma setup-host --host codex --write`, then start
Codex there. This writes native `.codex/config.toml` for that project and preserves
other servers and custom settings. Codex must trust the project before it loads
project configuration. `--print` displays the native TOML without writing anything;
`--out <new-file>` creates a new configuration snippet and refuses existing files.

The memory server's tools are approved during this setup so routine capture needs
no repeated permission prompts. Its identity approval tool still always refuses;
only the owner can apply a proposal through the separate terminal approval path.
Merging an existing Codex TOML file requires Python 3.11+; older installed runtimes
can emit a fresh snippet but preserve and refuse an existing file they cannot parse.
Codex CLI acceptance uses genuine model conversations. Desktop UI and other hosts
need their own evidence; a CLI result is not acceptance for all advertised hosts.

## 🤖 Agent reference (CLI fallback, debugging only)

```bash
twinaatma memory list
twinaatma memory memory_session_start --task-hint "ship MCP"
twinaatma memory memory_ops_status
twinaatma memory memory_breathe
```

Self writes are **proposal-only**, and only *you* can apply them:

```bash
twinaatma memory memory_propose_self_update \
  --summary "..." --section heuristics --proposed-markdown "..."
twinaatma self pending                       # what is waiting for you
twinaatma self approve <file>                # reads it, asks y/N — needs a terminal
twinaatma memory memory_reject_self_update --path People/Self-Proposals/<file>.md
```

`memory_accept_self_update` exists but **always refuses** — by design. Approval is a
terminal command so an agent cannot complete propose → accept on its own. A confirmation
code returned through a tool result would be no protection at all: the model reads tool
results.

A proposal only applies if **all** of these hold:

1. the toolkit created it (a signed row in the ledger, which lives **outside** the
   vault at `%LOCALAPPDATA%/TwinAatma/vaults/<hash>/self-proposals.jsonl`),
2. it is still a draft, not applied/rejected/superseded,
3. its fenced block is byte-identical to what was recorded,
4. the target section of `Self.md` has not changed since it was written,
5. the document's headings and section markers are unchanged by the patch, the patch
   contains visible characters, and it does not delete most of a section unless the
   proposal says it intends to.

Anything else fails closed and leaves `Self.md` untouched. A hand-written file in
`People/Self-Proposals/`, a rewritten ledger, a hardlink, or a symlinked `Self.md` can
never change your identity.

Other commands:

```bash
twinaatma doctor                   # environment + vault diagnostics
twinaatma validate                 # frontmatter and link health
twinaatma ids assign [--write]     # stable kos:<type>:<slug> ids
twinaatma self summary             # parsed ego node as JSON
twinaatma setup-host --help        # hosts: codex, cursor, vscode, claude-desktop, windsurf
twinaatma version                  # also --version
```

---

## 📂 Vault structure

```text
brain/
├── Inbox/          — Raw captures (unprocessed inputs)
├── Concepts/       — Ideas, principles, mental models
├── Projects/       — Active work streams with concrete outcomes
├── Experiments/    — Hypothesis testing
├── Research/       — Long-form investigations, papers, syntheses
├── Decisions/      — Decision logs (first-class citizens of strategy)
├── People/         — Self.md + network database
├── MOCs/           — Maps of Content
├── Templates/      — Note blueprints
├── Assets/         — Media and attachments
├── Archive/        — Retired material
├── .cursor/        — Agent rules, hook config and MCP config (no hook code)
└── .knowledgeos/   — Tool state: index manifest, session state (gitignored)
```

The index manifest and session state live in `.knowledgeos/`. The **proposal ledger
does not**: it is kept outside the vault, under your OS application-data directory and
signed with a per-install key, because a ledger an agent can write to is not a boundary.

The vault is **data only**. No `scripts/` folder, no code, nothing to run by hand.

---

## 🔄 Operating cadence (agent-owned)

| When | What the agent does |
|---|---|
| Every chat | `memory_session_start` — refresh index if stale, load Self + relevant notes |
| Important idea | `memory_capture` into Inbox, without asking you to "save" |
| Preference changes | propose → tell you the one approval command |
| Work wraps up | `memory_session_end` with a short summary |
| Weekly | review activity; propose identity changes only with explicit evidence of a changed belief |

New vaults mark uncollected owner beliefs as **Unknown**. Activity volume is not
proof of a changed belief: the current drift tick reports activity without creating
an identity proposal. A semantic comparison across time is still an acceptance gap.

Session startup returns `session_id`. Agents retain it and pass it to wrap-up and
retries. Separate chats keep separate records; identical wrap-up retries save one
summary. An unavailable Inbox leaves the session unfinished. The end hook can mark
a specific interrupted chat using the host event's session ID; when a host cannot
supply one, it acts only if exactly one chat is open.


You are not asked to run anything, with exactly one exception: applying a change to
`Self.md` is a terminal command you run yourself. That is the one action worth a real
yes from you, and it is what makes "the agent cannot rewrite who you are" true rather
than a claim.

---

## 🔒 Guarantees and their tests

| Guarantee | Proven by |
|---|---|
| The agent cannot apply a Self change by itself | `GateBoundaryTests.test_approve_interactive_itself_refuses_without_a_tty`, `GateLeverageTests.test_mcp_accept_refuses_even_with_a_plausible_code`, `test_gate_command_refuses_without_a_terminal` |
| Not even a piped `y` applies a proposal | `GateBoundaryTests.test_piped_answer_is_refused_not_read_as_a_yes` |
| `Self.md` cannot be changed by a forged or hand-written proposal | `SelfGateTests.test_forged_origin_without_base_hash_is_refused`, `GateLeverageTests.test_forged_ledger_row_is_ignored` |
| What the approval screen shows is what gets applied | `GateBoundaryTests.test_editing_proposal_metadata_invalidates_it`, `RoundElevenRegressionTests.test_approval_screen_ignores_metadata_written_into_the_summary`, `test_frontmatter_lookup_stops_at_the_closing_fence` |
| A proposal whose text was edited on disk is refused | `SelfGateTests.test_tampered_proposal_body_is_refused` |
| A hardlink or symlinked `Self.md` cannot be used to write identity | `GateLeverageTests.test_hardlinked_proposal_is_refused`, `test_symlinked_self_is_refused` |
| Rejecting cannot be redirected into `Self.md` | `GateBoundaryTests.test_reject_cannot_be_redirected_into_self_md`, `test_reject_cannot_append_to_a_file_the_gate_did_not_render` |
| A proposal cannot create, hijack, or hide sections (including via raw HTML) | `SelfGateTests.test_patch_cannot_inject_sections`, `GateBoundaryTests.test_raw_html_is_refused_in_every_form`, `GateLeverageTests.test_heading_with_leading_space_still_counts_as_structure` |
| Neither the destructive ratio nor the approval diff can be fooled by markup that draws nothing | `GateBoundaryTests.test_raw_html_cannot_hide_a_wipe`, `test_a_mismatched_fence_cannot_hide_a_wipe` |
| Setext and `#` headings cannot inject a section | `GateBoundaryTests.test_setext_and_h1_headings_cannot_inject_sections`, `test_document_shape_sees_h1_and_setext_headings`, `test_a_one_character_setext_underline_is_still_a_heading` |
| An unclosed code fence cannot hide the rest of a section | `GateBoundaryTests.test_an_unclosed_code_fence_is_refused` |
| A terminal escape cannot hide text from the approval screen | `GateBoundaryTests.test_terminal_escapes_cannot_hide_a_rule_from_the_approval_screen`, `test_c1_terminal_controls_are_refused_too` |
| Invisible, filler, or reordering characters cannot slip a patch through | `GateLeverageTests.test_invisible_only_patch_is_refused`, `GateBoundaryTests.test_bidi_override_is_refused`, `test_blank_filler_cannot_fake_a_non_destructive_replace`, `test_invisible_format_characters_are_refused` |
| Ordinary emoji and non-Latin orthography are not accused of hiding text | `GateBoundaryTests.test_an_unexpected_format_character_is_refused_but_real_script_is_not` |
| A busy gate says "try again", not `TimeoutError` | `GateBoundaryTests.test_a_busy_gate_answers_with_a_sentence_not_a_traceback` |
| The approval screen renders your own text on any console, and a closed stdin is a no | `GateLeverageTests.test_the_approval_screen_survives_a_note_the_console_cannot_encode`, `test_a_closed_stdin_is_a_no_not_a_traceback` |
| Padding cannot pay for deleting a section | `GateBoundaryTests.test_padding_cannot_pay_for_deleting_a_section`, `test_a_padded_wipe_is_refused_through_the_tool_surface` |
| A destructive whole-section replace needs explicit consent, and the waiver is named on screen | `GateLeverageTests.test_destructive_replace_needs_explicit_permission`, `GateBoundaryTests.test_approval_preview_shows_removals`, `RoundElevenRegressionTests.test_destructive_waiver_is_confirmed_separately` |
| Approving one line does not rewrite the whole identity file, not even when one line has a stray CRLF | `GateBoundaryTests.test_approval_does_not_rewrite_line_endings`, `RoundTwelveRegressionTests.test_one_stray_crlf_does_not_rewrite_the_whole_identity_file` |
| A Windows-sourced patch can still be approved | `GateBoundaryTests.test_crlf_patch_can_still_be_approved` |
| A moved vault keeps its pending proposals | `GateBoundaryTests.test_moving_the_vault_keeps_pending_proposals_valid` |
| Re-running `init` keeps the vault id and does not orphan proposals | `InitSmokeTests.test_reinit_keeps_the_vault_id_so_proposals_stay_verifiable` |
| Reject only touches Self proposals | `SelfGateTests.test_reject_cannot_touch_notes_outside_proposals_dir` |
| Second proposal for one section is superseded, not stuck | `SelfEvolutionTests.test_second_proposal_for_same_section_is_superseded_not_stuck` |
| Edits in any folder and deletions are seen, including same-size in-place edits, with no size at which verification is quietly skipped | `IndexIntegrityTests`, `DispatchRobustnessTests.test_same_size_edit_with_preserved_mtime_is_still_seen`, `RoundElevenRegressionTests.test_hash_budget_no_longer_silently_skips_verification` |
| Nothing the product writes can escape the vault through a junction | `GateBoundaryTests.test_reject_cannot_be_used_to_write_outside_the_vault`, `test_a_proposal_cannot_write_through_a_junctioned_inbox` |
| A planted link at the write temp name cannot rewrite `Self.md` | `GateBoundaryTests.test_planting_a_hardlink_at_the_temp_name_cannot_rewrite_self_md` |
| A second signing key does not orphan pending proposals | `GateBoundaryTests.test_a_second_signing_key_does_not_orphan_pending_proposals` |
| Text that never renders cannot hide a wipe from consent or the screen | `GateBoundaryTests.test_a_multi_line_comment_cannot_hide_a_wipe`, `test_raw_html_cannot_hide_a_wipe`, `test_a_mismatched_fence_cannot_hide_a_wipe`, `test_the_llm_renderer_agrees_with_the_destructive_ratio` |
| A deleted note is never served, with no grace window | `DispatchRobustnessTests.test_search_does_not_serve_a_deleted_note`, `IndexIntegrityTests.test_locked_index_does_not_serve_a_deleted_note`, `test_every_search_bucket_drops_a_deleted_note`, `test_capture_does_not_leave_a_deleted_note_in_the_manifest`, `test_every_read_path_drops_a_deleted_note`, `test_related_drops_a_deleted_neighbour` |
| A busy index is detected, answers quickly, and never surfaces `database is locked` | `IndexIntegrityTests.test_locked_index_returns_quickly_instead_of_stalling`, `test_index_state_detects_a_real_writer_and_search_degrades` |
| Search re-checks the vault every time, with no freshness throttle | `IndexIntegrityTests`, `DispatchRobustnessTests` |
| A note edited seconds ago is never quoted from a locked index, including its tags, title, and project | `IndexIntegrityTests.test_an_edited_note_is_not_quoted_from_a_locked_index`, `RoundElevenRegressionTests.test_locked_index_does_not_serve_removed_metadata` |
| A frozen index does not turn a stem into a miss, filter on stale project names, or serve a deleted link | `RoundTwelveRegressionTests.test_locked_index_keeps_stemmed_hits`, `test_decisions_filter_on_the_file_not_the_frozen_index`, `test_related_drops_a_removed_link_while_locked` |
| Refreshing a row never loses a hit the index found by prefix or substring | `spec: reads.a_prefix_still_finds_the_note` |
| An answer from a frozen index is not presented as a complete one | `RoundTwelveRegressionTests.test_a_frozen_index_says_so` |
| The freshness manifest cannot be rewritten to hide an edit | `RoundTwelveRegressionTests.test_an_unsigned_manifest_is_not_trusted` |
| Rewriting the index cannot make search quote a sentence no note contains | `spec: truth.forged_index_text_is_never_quoted` |
| Rewriting any indexed column cannot make search describe a note as something it is not, in any bucket | `spec: truth.a_forged_metadata_column_is_not_served` |
| Rewriting or emptying index rows cannot make a note unsearchable, and a tampered index is repaired, not trusted | `spec: truth.a_forged_index_row_cannot_hide_a_note`, `truth.deleted_index_rows_are_repaired` |
| An ordinary capture repairs a tampered index instead of certifying it, and restores a deleted row | `spec: truth.a_capture_cannot_bless_a_forged_index`, `truth.a_deleted_index_row_is_repaired_by_a_capture` |
| The index is a cache: every row returned re-derives every displayed field from the note, and the manifest vouches for the whole index | `spec: truth.a_forged_metadata_column_is_not_served`, `reads.removed_metadata_is_not_served` (`index_digest`) |
| A closed decision stays closed, and is never asked about again, even when the index lags | `spec: truth.forged_status_cannot_reopen_a_closed_decision`, `truth.the_closed_decision_is_not_asked_about` |
| A held index does not turn a stemmed query into a miss | `spec: reads.stemmed_query_survives_a_locked_index` |
| A template is not a decision | `spec: truth.a_decision_template_is_not_a_decision` |
| Editing the vault marker cannot orphan a pending Self proposal | `spec: identity.rewriting_the_vault_marker_cannot_orphan_proposals` |
| A file where the state folder belongs is reported as an error | `spec: ops.the_state_folder_must_be_a_folder` |
| A vault whose index path cannot be opened is reported as broken, not healthy | `spec: ops.a_directory_where_the_index_belongs_is_an_error` |
| An index that opens but cannot answer a search is reported, repaired, and never reads as "no matches" | `spec: ops.a_directory_where_the_index_belongs_is_an_error` |
| An index that holds none of the notes is not called healthy | `spec: ops.an_incomplete_index_is_not_called_healthy` |
| One note with a YAML list property cannot stop the index being built | `spec: truth.a_yaml_list_property_does_not_break_the_index` |
| A title that lives in the H1 or the filename is found, and shown | `spec: reads.a_title_in_the_filename_or_h1_is_found_and_shown` |
| A new line takes the file's own line ending | `spec: reads.approving_one_line_keeps_the_files_line_ending` |
| A capture that has to rebuild the vault says so, and restores the digest | `spec: autopilot.an_absent_digest_says_it_rebuilt` |
| The index digest tells NULL from the word `None` | `spec: reads.the_digest_tells_null_from_the_word_none` |
| A query with no searchable words cannot keep a row whose field stopped matching it | `spec: reads.an_undecidable_query_does_not_resurrect_a_row` |
| A lock the index cannot take is reported, not silently swallowed | `IndexIntegrityTests.test_a_lock_path_that_is_a_directory_is_reported_not_swallowed` |
| The proposal ledger lives outside the vault and is HMAC-signed | `GateLeverageTests.test_forged_ledger_row_is_ignored` |
| A capture is searchable immediately | `CaptureSearchTests` |
| Long notes stay searchable past any internal cap | `DispatchRobustnessTests.test_long_note_is_searchable_past_the_old_1mb_cap` |
| A note in the vault root, or named like a conflict copy, is still searchable | `VaultIntegrityTests.test_a_users_root_changelog_is_searchable`, `test_a_note_named_like_a_conflict_copy_is_searchable`, `IndexIntegrityTests.test_a_users_root_readme_is_searchable`, `test_the_toolkit_checkout_keeps_its_plumbing_out_of_the_index` |
| Unmerged `*.new.md` conflict copies are not indexed as notes | `VaultIntegrityTests.test_a_real_conflict_copy_is_still_skipped` |
| `search` and `validate` always describe the same note set | `IndexIntegrityTests.test_search_and_validate_walk_the_same_file_set` |
| Editing one field does not rewrite every line of a user's note, including its line endings | `IndexIntegrityTests.test_a_capture_and_an_id_assignment_keep_the_files_line_endings`, `spec: reads.approving_one_line_keeps_every_other_line_ending`, `reads.one_stray_crlf_does_not_rewrite_the_file` |
| `ids` and `validate` cannot be pointed outside the vault | `VaultIntegrityTests.test_ids_does_not_follow_a_junction_out_of_the_vault`, `test_validate_uses_the_same_file_set_as_the_index` |
| The section reader and the section writer agree on what a section is | `VaultIntegrityTests.test_self_model_and_gate_agree_on_which_sections_exist`, `test_a_decoy_heading_does_not_satisfy_a_section` |
| A missing required tool argument is an error, not a guess | `DispatchRobustnessTests.test_missing_required_argument_is_an_error_not_a_guess`, `test_every_required_field_in_the_schema_is_enforced` |
| Corrupt index is quarantined, locked index is not | `IndexIntegrityTests.test_corrupt_index_is_quarantined_and_rebuilt` |
| A pre-warm hook cannot fake a first session | `FirstSessionTests.test_prewarm_does_not_count_as_a_session` |
| Drift is proposed on evidence, not on the second chat | `FirstSessionTests.test_two_chats_in_one_afternoon_do_not_propose_drift` |
| A hostile note title cannot masquerade as instructions in agent context | `AutopilotTests.test_soft_prompt_neutralises_hostile_note_titles` |
| The vault cannot get code executed through a planted binary, a hook interpreter, a hook folder, or a planted `git` | `GateBoundaryTests.test_planted_binary_in_vault_is_not_selected`, `test_hook_does_not_resolve_the_working_directory`, `test_init_pins_the_hook_interpreter`, `test_the_hook_is_launched_with_p_so_its_own_folder_is_not_on_sys_path`, `test_a_planted_file_in_the_hooks_folder_never_executes`, `test_replacing_a_vault_hook_script_does_not_change_what_runs`, `test_init_reports_an_unexpected_file_in_the_hooks_folder`, `test_doctor_flags_an_unexpected_file_in_the_hooks_folder`, `test_planted_git_in_the_vault_is_not_executed`, `test_resolve_executable_refuses_a_binary_inside_the_working_directory` |
| No hook runs executable code that lives inside the vault | `GateBoundaryTests.test_replacing_a_vault_hook_script_does_not_change_what_runs` |
| The end-of-chat hook actually runs and marks an unfinished session | `GateBoundaryTests.test_the_end_hook_runs_and_marks_an_orphaned_session` |
| No ordinary write can reach `People/Self.md` through a hardlink or a predictable temp name | `GateBoundaryTests.test_state_writers_cannot_reach_self_md_through_a_hardlink`, `test_the_end_hook_cannot_write_through_a_hardlinked_state_file`, `test_a_hardlinked_self_md_is_refused_as_an_identity_target` |
| A `.knowledgeos` junction cannot move vault state outside the vault | `IndexIntegrityTests.test_a_junctioned_state_folder_is_refused` |
| An append stores exactly the text the approval screen showed, and says when it changes nothing | `SelfEvolutionTests.test_append_stores_the_trailing_spaces_it_shows`, `test_append_screen_shows_the_merge_not_the_patch`, `test_repeated_appends_do_not_duplicate_rows` |
| `> ## X` and `- ## X` cannot inject a section | `IndexIntegrityTests.test_blockquote_and_list_headings_cannot_inject_sections` |
| A broken `Self.md` is reported, not a crash | `GateBoundaryTests.test_self_md_replaced_by_a_directory_reports_instead_of_crashing`, `RoundElevenRegressionTests.test_doctor_fails_on_a_missing_identity_section` |
| A stray folder is not silently treated as a vault | `GateBoundaryTests.test_a_stray_directory_is_not_treated_as_a_vault` |
| Re-running `init` on a vault is a refresh; a foreign folder still needs `--force` | `InitSmokeTests.test_reinit_existing_vault_is_a_refresh_not_an_error`, `test_init_still_refuses_a_non_empty_foreign_directory` |
| A pip install and the binary both produce a working vault | `DocsContractTests.test_wheel_build_stages_the_starter_kit`, `test_pyinstaller_bundles_what_init_needs` |
| The end of a chat reports one prompt, not a Python tuple | `RoundElevenRegressionTests.test_session_end_reports_a_soft_prompt_as_a_string` |
| Docs match the code | `tests/test_docs.py` |
| The suite never writes into the repo | `IsolationTests` |

Run them with `python tests/test_core.py`, `python tests/test_docs.py`, and
`python tests/test_stabilization.py`. The last suite covers seeded newline round-trips,
failure/recovery, realistic frontmatter values, and the verifier's own failure handling.

### The scorecard

`python tests/score.py` turns those guarantees into one deterministic number.

```
  Identity safety          ########## 100.0  (x30, 6 ok, 1 skip)
  Approval fidelity        ########## 100.0  (x25, 8 ok)
  Vault integrity          ########## 100.0  (x15, 5 ok)
  Truthfulness of reads    ########## 100.0  (x15, 34 ok)
  Autopilot reliability    ########## 100.0  (x10, 9 ok)
  Install/ops honesty      ########## 100.0  (x5, 8 ok)
  SCORE 100.0/100 across 71 scenarios
```

Each scenario is a claim plus an observation (`tests/spec/scenarios.py`). Weights are
declared in `tests/spec/__init__.py` and are deliberately identity-heavy: the boundary
around `Self.md` is the thing that must not break. `--json` emits the scorecard for CI,
`--baseline` diffs against `tests/spec/baseline.json`, and `--save-baseline` records a new
reference.

`python tests/mutation_check.py` checks fifty-one targeted defect reversions in a scratch
copy and requires each named scenario to record an assertion failure. A finding that was fixed
in two places is reverted in both, because reverting only one leaves the other still holding
the line and reports a false BLIND. A scenario that stays
green under its own bug is deleted rather than kept as decoration. That rule has teeth in
both directions: round thirteen found four scenarios whose mutations still passed, and the
fix was to strengthen the scenarios (assert the stored row, not just what a read returns)
rather than to keep a check that proved nothing.

The harness first requires a passing unmutated baseline. Unknown IDs, ambiguous edit
anchors, syntax errors, scenario crashes, malformed scorecards and inconsistent exit codes
are harness failures, not caught mutations. The final restored tree must pass again.
`--only <scenario-substring>` runs a subset. CI runs both the verifier self-tests and the
complete mutation check; these are not temp-only probes.

Packaging is checked separately with `python tests/package_smoke.py --wheel <wheel> --source .`
or `--binary <executable>`. The explicit artifact path and SHA-256 appear in the result;
the wheel check compares its module bytes with the source and imports from an isolated
installation, not the checkout. A previous temp probe's hard-coded artifact paths made
its results unsuitable as evidence for a new build; CI now uses this checked-in test.

Read the number honestly. It measures the **corpus**, not the product: it cannot see a
class of bug nobody imagined, and it found none of the first fourteen rounds' defects by
itself. Round thirteen is one example: the scorecard said 100/100 while a critical defect
was live, because no scenario asserted that a *metadata* column, not just the body, has to
survive a refresh. Round fourteen is the sharper one: 100/100 across 50 scenarios while a
single note with a YAML block-list property — the most ordinary thing Obsidian writes —
left the index with zero rows and every search answering "Another process is using the
note index". No scenario had ever written a list where a string was expected, and none
had searched a note whose title was its filename.

The mutation harness is what stops that being purely retrospective. Round fourteen taught
it the difference between *the scenario failed* and *the process failed*: it used to treat
any non-zero exit as "caught", so a mutation that did not compile, and a mutation aimed at
a scenario id that no longer existed, both counted as successes. Reading the verdict out
of the scorecard instead immediately surfaced one stale entry that had been reporting
`caught` for nothing. Every scenario here is seeded from a reviewer's reproducer, and a
scenario that does not fail when its bug is put back is deleted rather than kept as
decoration. The adversarial review is still what finds new *classes*; the scorecard is
what stops the same class being paid for twice, and what makes "is this better than
yesterday" a diff instead of a memory.

The separate [18 October stabilization review](tests/reviews/stabilization-2026-10-18.md)
revalidated six newly reproduced defects against a hash-verified frozen snapshot and
assigned **100/100, no cap**, under the unchanged weights. That is a scoped independent
judgment, not this corpus score or a guarantee about untested behavior. Its initial capped
assessment, actual probes, fixes, and coverage limits are recorded alongside the result.

---

## 📐 Architecture

```text
  Obsidian (thinking)  <--- markdown you own --->  TwinAatma vault
                                                        ^
                                     MCP Memory API (stdio)
                                                        |
                                              Cursor / Claude / any agent
```

| Layer | Role |
|---|---|
| **Vault** | Markdown source of truth. Portable, diffable, no lock-in. |
| **Index** | SQLite + FTS5, rebuilt automatically. Disposable by design. |
| **Gate** | The only path that writes `People/Self.md`, behind an explicit yes. |
| **Autopilot** | Keeps index and proposals current without human chores. |

Optional external sync (Notion) lives outside the core package and is not required.
Publishing requires an explicit source path. Sequential retries reuse a page identified
by that source URL; changed remote content is refused instead of overwritten. There
is no atomic deduplication guarantee for concurrent publishers. Adapter checks use
mocked transport; no live publishing is part of the regression suite.

### What this does *not* protect against

A trust claim is only worth the limits it admits. This defends against an agent that was
persuaded by vault content, and against an agent driving the tool surface. It does not
defend against an agent that can run arbitrary shell commands as you, or one that can
spawn and type into an interactive terminal — such an agent can satisfy the TTY check.
No local design survives that.

Practical consequence: the vault is markdown you can read and diff, and the gate lives in
`%LOCALAPPDATA%/TwinAatma/` (keyed by a `vault_id` written at `init`, so moving the vault
keeps your pending proposals). If you copy a vault to another machine, copy that state
directory too, or re-propose. A proposal made on one machine is not approvable on another,
by design.

---

## 📜 Rules of the road

* **No orphans**: every note links to at least one other page.
* **Decisions are sacred**: major shifts get a note in `Decisions/`.
* **Projects need actions**: an active project without next steps is dead.
* **Portability first**: plain YAML frontmatter and markdown.
* **Identity is gated**: the agent proposes; you accept.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development contract, and
[Decisions/](Decisions/) for the architectural record.
