# Source data preservation

Use Python 3.11+ from the trusted checkout. Each driver creates a unique run beneath
a `.knowledgeos` component of `work/gc-artifacts`, makes full toolkit copies with
synthetic notes, sets explicit fixture/state paths, and retains commands and source
inventories. The working vault is never a test target. Keep output paths short
enough for the native filesystem. A native link permission failure is NOT CHECKED.

```powershell
python -B .agents/skills/verify-twinaatma/scripts/data_preservation.py --output work/gc-artifacts/.knowledgeos/data-preservation/export
python -B .agents/skills/verify-twinaatma/scripts/generated_writers.py --output work/gc-artifacts/.knowledgeos/data-preservation/gw
python -B .agents/skills/verify-twinaatma/scripts/memory_census.py --output work/gc-artifacts/.knowledgeos/data-preservation/census
python -B .agents/skills/verify-twinaatma/scripts/maintenance.py --journey maintenance --output work/gc-artifacts/.knowledgeos/data-preservation/maintenance
python -B .agents/skills/verify-twinaatma/scripts/maintenance.py --journey hooks --output work/gc-artifacts/.knowledgeos/data-preservation/hooks
python -B .agents/skills/verify-twinaatma/scripts/maintenance.py --journey validation --output work/gc-artifacts/.knowledgeos/data-preservation/validation
```

Export has fourteen cases. Existing files/directories, source overlap, prefix
siblings, linked source/output and hardlinks must refuse with unchanged complete
source and external-target inventories. Two fresh bundles must contain the exact
selected bytes and literal manifest entries. Linked-note and attachment omissions
must be explicit. An exit-zero message or manifest existence alone cannot pass.

Generated-writer proof covers the trajectory and weekly library entry points,
intelligence views, experiment dashboard, outcomes dashboard and legacy weekly draft.
The v2 generated producer has 48 cases. Its earlier five-writer, 40-case predecessor
omitted the legacy draft and cannot prove complete generated-report preservation. Eight scenarios
per writer exercise regeneration, unowned/edited output, linked target/parent,
hardlinked target, and faults at receipt/report replacement. Faults are injected
at the filesystem boundary inside a real subprocess. Prior report bytes must
survive; an ordinary retry and repeated call must converge. The six writers, including `scripts/draft_weekly_synthesis.py`,
produce ten output files. Atomicity is per output, not a transaction across all
views. Derived index/database refreshes are observed separately from source and
report preservation.

A versioned generated-write receipt records prior and proposed content hashes
before the report is replaced. Either interrupted state can retry. Legacy hashes
remain readable; malformed or linked receipts cannot authorize replacement.
Unknown metadata cannot hide a personal note from the census.

Census proof uses literal forbidden markers in host instructions, toolkit files
including shipped root Templates, and synthetic fixtures. Public searches and the shared census must exclude them
and all ten unchanged owned writer outputs. Positive personal MOC/synthesis
controls prevent passing by returning no results. A user-edited generated report
must become searchable without being overwritten. Self and proposal bytes remain
unchanged. The explicit toolkit-copy inventory precedes instruction-marker probes.

Maintenance has thirteen cases. ID assignment must actually write in a contained
fixture, preserve declared schemas, body bytes and fenced examples, reserve protected
IDs, refuse identity hardlinks and linked directories, and preserve originals after
replacement or partial-write faults. Link refactoring and all seven map outputs
retain the same preservation and retry requirements.

Hook preservation has eight cases. Run an installed custom hook through Git,
refuse existing, external, linked and hardlinked destinations, and inject both
partial-write and executable-permission failures. New hooks are fully staged and
made executable before exclusive publication. A competing existing destination
survives. Windows permission handling is NOT APPLICABLE; an unavailable native
symlink remains NOT CHECKED. A complete native Linux run supplies these cases.

Validation has ten literal fixtures. Both the CLI and source script must
accept exactly seven good personal notes and return nonzero with precise diagnostics
for missing metadata, status, date, tags, unknown schema, malformed or duplicate IDs,
and broken or ambiguous links. The shipped root Templates directory is toolkit data;
a nested personal directory named Templates remains eligible. Validation is read-only.

Combine complete current reports using repeated `--data-report <report.json>`
arguments to `acceptance.py`, alongside current source, host, artifact and runtime
reports. Adapter v5 checks the complete toolkit inputs, current producer/support
bytes, contained nonlinked evidence, actual command/PID/exit binding, fixed case
inventories, source stability and selected real-vault sentinels. For maintenance,
parent stderr traces independently bind nested child argv, PID, exit and shutdown.
These six existing source outcomes are DATA.safe_export, DATA.atomic_generated,
DATA.memory_census, DATA.safe_maintenance, DATA.preserve_hooks and
DATA.honest_validation. Partial coverage earns no point; failures remain failures.
The original 54-outcome rubric, criticality and required scopes remain unchanged.

This is source API/script evidence on the recorded native filesystem. It does not
establish an agreed capture/retention policy, independent owner approval, host
instruction resistance, clean-device restore, or data-operation portability. Keep
all original failures and interrupted attempts, register actual observations only,
and retain a real durable handoff outside disposable evidence roots.
