# Preserve private data through capture, export, and maintenance

Memory remains local by default, external writes require scope, and maintenance cannot destroy source material or unrelated configuration.

## Sub-features

- PRIVACY.1. Synthetic secrets and disallowed sensitive content follow an explicit capture policy.
- PRIVACY.2. Host data, logs, and bundles expose only permitted content.
- PRIVACY.1 source boundary. Ordinary project facts and contextual preferences auto-persist. Explicit `privacy=exclude|credential|sensitive-third-party` capture metadata and matching legacy frontmatter refuse admission. Finite credential and explicit third-party patterns provide conservative additional checks; they do not establish arbitrary semantic detection.
- Retention and correction. `memory_get_note` supplies the exact reviewed `sha256`. After an explicit forgetting request, call `memory_forget(path_or_id, expected_sha256)`. It preserves sources and excludes their paths, exact copies and normalized literal passages from current recall, future capture and exports. `memory_supersede` records two reviewed source paths and hashes; the prior direct read is labeled historical and current recall uses its replacement. Neither tool changes Self.
- DATA.1. Export refuses overlapping source targets and existing unowned output.
- DATA.2. Link/schema/ID maintenance preserves original notes on failure.
- DATA.4. Tool instructions, unchanged owned reports and synthetic verification vaults are excluded from personal-memory indexing. User edits remain personal evidence.
- DATA.3. Restore verifies content and declares external approval-state dependencies.
- DATA.5. Hook installation preserves existing hooks, honors contained custom paths and reports failed publication truthfully.
- DATA.6. Both validation commands distinguish valid personal data from precise schema, ID and link defects.

## How to get to it (user POV)

Share information, export a selected project, update links or schema, or restore a backup. Optional Notion publishing is separate from memory operation.

## Driving it with isolated CLI copies and file comparisons

Preconditions: inspect every source-only script's vault resolution. Use a complete task-owned checkout copy with synthetic notes. Never run destructive export probes in the working vault.

- Note census. Enumerate indexable notes read-only. Require tool instructions, caches, fixtures, and nested synthetic identities to be excluded. Focused census regressions now cover .agents, work, outputs, tests and AGENTS.md; the driver also stores its fixtures beneath .knowledgeos.
- Scope inventory. Include installed CLI, MCP tools, host hooks, source-only scripts, Notion integrations, and local evidence. Record the entry points that are absent from the installed package.
- Export overlap. Seed synthetic identity and source notes. In the isolated copy, invoke `scripts/export_bundle.py --paths Concepts --out People` and an output equal to selected source. Require refusal and byte-for-byte preservation. Also test a sibling path with the same string prefix, an existing unrelated output, and linked output directories.
- Successful export. Select synthetic notes with links and attachments. Export to a fresh owned destination. Verify source invariance, bundle manifest, exact selected content, link behavior, and whether dependencies are included or explicitly omitted.
- Derived writers. Exercise supported intelligence/dashboard writers in the full synthetic copy. Seed linked parents, linked or hardlinked outputs where permitted, and edited existing reports. Require protected sentinels and edits to survive with explicit failures.
- Hook installation. In a task-owned Git repository, seed an existing pre-commit hook and test custom `core.hooksPath`. Require preservation or an explicit refusal.
- Validation. Run `twinaatma validate --vault <fixture>` on known-good and deliberately malformed notes. Require precise broken-link, ambiguous-link, status, date, tag, and duplicate-ID diagnostics.
- Maintenance. Run the documented dry-run and write entry points for ID assignment, link refactoring, and map updates in the isolated copy. Compare all affected files and exit codes. Require Self, proposal evidence, and fenced examples to remain unchanged. Inject a failed write and require recoverable originals.
- Privacy. Use synthetic credentials and sensitive records under the agreed retention policy. Inspect persisted notes, context, transcripts, bundles, and publish selections. Keep external credentials absent for local verification. Real external publishing requires the user's explicit authorization and a concrete reviewed selection.
- Approved-policy source checks. Exercise direct API, CLI and real MCP process refusals for titles, bodies, tags, task hints and summaries. Require sanitized protocol errors, source hashes unchanged, stale/forged cache exclusion, explicit forgetting across duplicates/restarts/retries, historical correction attribution, and merged concurrent exclusions. Fail closed on malformed, duplicate-key, hardlinked or linked state. Inject a failed ledger publication and retain the failed observation before checking recovery.
- Inventory control. `iter_markdown` remains the raw source inventory for validation and maintenance; `iter_memory_markdown` applies narrower personal-memory admission. An invalid excluded source must still produce validation errors, with private diagnostic values redacted. Preserve ordinary direct text bytes and existing export collision refusals.
- Restore. Restore a bundle to a new fixture. Verify source hashes and documented omissions. Test pending approvals according to the portability feature rather than copying untrusted keys into a working identity.

Use [the 44-case privacy source recipe](../references/source-privacy.md) for
approved-policy provenance, signed state, admission, forgetting, historical
corrections, diagnostics and guarded publishing. The independent `--privacy-report`
adapter awards only the policy and two source outcomes; zero credential resolution
and zero outbound transport attempts are required for the publishing refusals.

Use [the source data-preservation recipe](../references/data-preservation.md) for
repeatable complete-copy export, generated-writer, census and maintenance journeys.
The maintenance driver has separate `maintenance`, `hooks` and `validation` choices.
Each driver
retains observable cases without assigning fixed-outcome credit itself. Combine its
current report through the strict data adapter before updating the accepted score.

## Gotchas

Focused deterministic source checks do not certify complete privacy enforcement, installed-host data operations or restore. Finite patterns cannot recognize arbitrary sensitive meaning. Forgetting does not classify arbitrary paraphrases, and corrections refer to exact reviewed sources. After first adoption, the strict policy has signed off-vault authority and a signed local mirror. A missing mirror recovers from authority; changed mirrors and missing or altered trusted state or signing keys refuse release. An interrupted publication retains the newest signed restrictions and repairs the mirror on a later write. Unsigned legacy v1 is adopted whole; edits made before adoption cannot be authenticated retroactively. Restore, trusted-state loss, two-device divergence and power-loss behavior need their own evidence. Genuine-host selective capture, note-instruction handling, correction advice, complete local log coverage, optional publishing transport and restore remain separate gates. The export continues to refuse existing output, source overlap and linked paths. Artifact-observer registration is observation only and never authorizes deletion.

Diagnostic policy checks also cover `self pending` and the source drift report. They withhold excluded source references, fail closed when policy state is unavailable, and preserve ordinary sources. Drift reports current permitted personal-note activity, never treating edit counts as belief evidence. Root diagnostic controls use a real pending CLI; their Git-history input is stubbed and is not genuine Git acceptance.
