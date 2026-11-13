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

## What checks it

Preconditions: read how each source-only script finds its vault. Use a complete task-owned checkout copy with synthetic notes. Never run an export probe in the working vault. Run one suite with `python -B -m unittest discover -s tests -p <file>`.

- Remembering policy. `tests/test_privacy_policy.py`, `tests/test_privacy_authority.py`, `tests/test_privacy_normalization.py`, `tests/test_policy_snapshot.py`, `tests/test_refresh_policy_boundary.py` and `tests/test_pattern_reuse.py`: admission and refusal of marked and credential-like content; forgetting across exact copies; historical corrections; signed policy state that refuses a changed mirror or a missing key.
- The privacy reader. `tests/test_privacy_metadata_comments.py` and `tests/test_privacy_yaml_oracle.py` (random texts against a full YAML parser; needs PyYAML). See [the first day](first-day.md).
- Sensitive relations and diagnostics. `tests/test_privacy_sensitive_relations.py` and `tests/test_privacy_diagnostics.py`: `self pending` and the drift report withhold an excluded source and fail closed when the policy state is unavailable.
- Reads of a bound source. `tests/test_source_binding.py`: a path outside the vault, a hard link, a symbolic link and a replaced file are refused.
- Note census. `tests/test_note_census_types.py`, `tests/test_template_census.py`, `tests/test_generated_census.py` and `tests/test_recall_repairs.py`: tool instructions, caches, fixtures and nested synthetic identities are not personal memory; a person's edit to a generated report is.
- Export and maintenance. `tests/test_data_repairs.py` and `tests/test_id_maintenance.py`: export refuses an overlapping source, an existing output and a linked path, and a fresh bundle keeps its source and manifest; link and ID maintenance keep identity, proposals, fenced examples and mixed line endings, and a failed write keeps the whole note.
- Generated writers. `tests/test_generated_writer_faults.py`: a failed commit keeps the original reports and a retry converges.
- Validation. Classes `SchemaTests` and `VaultIntegrityTests` in `tests/test_core.py` and class `ValidatorRootGuideTests` in `tests/test_journey_gaps.py`.
- Publishing. Class `NotionPublishingTests` in `tests/test_learning_repairs.py`: a dry run and an unselected note never call the transport. Real publishing needs the owner's explicit authorization and a reviewed selection.
- Inventory control. `iter_markdown` is the raw source inventory for validation and maintenance; `iter_memory_markdown` applies the narrower personal-memory admission. An invalid excluded source must still give validation errors, with private values redacted.

Not checked by any script: hook installation in a real Git repository with a custom `core.hooksPath`, data operations from an installed package, and a restore of a bundle to a new machine. The driver for each was removed on 13 November 2026; the last commit that holds it is `69bec1e`.

## Gotchas

Focused deterministic source checks do not certify complete privacy enforcement, installed-host data operations or restore. Finite patterns cannot recognize arbitrary sensitive meaning. Forgetting does not classify arbitrary paraphrases, and corrections refer to exact reviewed sources. After first adoption, the strict policy has signed off-vault authority and a signed local mirror. A missing mirror recovers from authority; changed mirrors and missing or altered trusted state or signing keys refuse release. An interrupted publication retains the newest signed restrictions and repairs the mirror on a later write. Unsigned legacy v1 is adopted whole; edits made before adoption cannot be authenticated retroactively. Restore, trusted-state loss, two-device divergence and power-loss behavior need their own evidence. Genuine-host selective capture, note-instruction handling, correction advice, complete local log coverage, optional publishing transport and restore remain separate gates. The export continues to refuse existing output, source overlap and linked paths. Artifact-observer registration is observation only and never authorizes deletion.

Diagnostic policy checks also cover `self pending` and the source drift report. They withhold excluded source references, fail closed when policy state is unavailable, and preserve ordinary sources. Drift reports current permitted personal-note activity, never treating edit counts as belief evidence. Root diagnostic controls use a real pending CLI; their Git-history input is stubbed and is not genuine Git acceptance.
