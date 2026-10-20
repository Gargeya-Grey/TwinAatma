# Learn from outcomes without inventing personal change

The assistant remembers decisions and revisits outcomes when useful. It proposes belief changes only from meaningful evidence.

## Sub-features

- LEARNING.1. Pending decisions and outcomes retain correct source and status.
- LEARNING.2. A lesson proposal names its supporting outcome and uncertainty.
- LEARNING.3. Formatting churn is not semantic drift.
- LEARNING.4. Rejected or superseded suggestions do not recur without new evidence.

## How to get to it (user POV)

Record a decision, later describe its outcome, and receive relevant future help. Occasionally receive a specific preference suggestion supported by evidence.

## Record a reviewed outcome through the public API

An assistant can close an ordinary pending decision with `memory_record_outcome`.
First read the exact decision through `memory_get_note`. Pass the returned `path`
and `sha256` as `path` and `expected_sha256`, then supply `outcome_status`
(`confirmed`, `invalidated`, or `superseded`), a nonempty `actual_outcome`, and a
nonempty `lesson`. The generic CLI exposes the same tool:

```powershell
python -B -m knowledgeos memory memory_get_note --vault <synthetic-vault> --args '{"path_or_id":"Decisions/Courier.md"}'
python -B -m knowledgeos memory memory_record_outcome --vault <synthetic-vault> --args '{"path":"Decisions/Courier.md","expected_sha256":"<exact-reviewed-sha256>","outcome_status":"confirmed","actual_outcome":"The pilot met all six delivery deadlines.","lesson":"Try a short pilot first"}'
```

The source update is atomic and preserves unrelated bytes and existing line
endings. A source-bound receipt in that same update makes an exact retry with the
original reviewed hash converge without another edit. Changed requests, changed
sources and already closed versions refuse. Protected identity, proposal,
template, generated, linked and hardlinked sources refuse. The complete proposed
source must satisfy the shared remembering policy while its lock is held.

The source outcome closes even while indexing is unavailable. `recorded: true`
means the source is saved; `index_refresh` and `index_frozen` separately disclose
busy or blocked discovery. Pending lists reread current source metadata, so an
indexed decision stops appearing pending immediately. A new process automatically
refreshes the index after the obstruction is released.

`belief_before` and `belief_after` are optional paired, explicit statements.
Recording a lesson never invents them. This operation neither applies a Self
change nor establishes independent verification of the user's reported outcome.
Requested text must roundtrip exactly through the supported single-line note
format. Unsupported control characters, quoted boolean/list-like literals and
strings requiring unsupported quote escaping refuse without publishing a change.

Verify public discovery, review, recording and exact replay in separate CLI/MCP
processes. Compare the actual source hash and literal fields after restart. Require
pending and reminder closure, current timeline attribution, stale-source refusal,
native busy-index truthfulness and automatic recovery. Keep publication fault
injection and concurrency tests as supporting evidence. Snapshot Self and all
preexisting proposals before and after. Do not invoke approval in this journey.
Source command proof leaves ordinary host behavior and the fixed 54-outcome
readiness criteria unchanged.

## Source decision and lesson proof

Use [the source learning recipe](../references/source-learning.md) for the twelve-case
`learning.py` journey and strict `--learning-report` adapter. It retains literal
source states, original MCP wire, a live SQLite holder, unchanged toolkit and
identity bytes, and the unapproved source-linked draft. Exact project precision
and attributed lessons receive separate verdicts. Use [the longitudinal source recipe](../references/source-longitudinal.md) for
27 frozen formatting, semantic-evidence, signed rejection and new-source cases.
Its independent `--longitudinal-report` grader covers only semantic drift and
rejection recurrence. Source proof leaves the host outcome loop, representative
elapsed use and owner approval unresolved.

## Driving it with MCP and longitudinal chats

Preconditions: seed synthetic decisions with known pending/closed states, dates, sources, and lessons. Keep meaningful changes separate from mechanical edits.

- Decision views. Call `memory_decisions`, `memory_pending_outcomes`, and `memory_timeline` through MCP. Edit a decision externally, including during a frozen index, and require current metadata and honest completeness indicators.
- Review timing. An old decision with blank outcome metadata stays searchable without automatically asking the person to review it. An explicit pending outcome is eligible without a date; a valid due ISO date also establishes review intent. Future or malformed dates and completed outcomes are ineligible. Verify that already asked rows are removed before the bounded queue is selected, so a ninth due decision can still be reached. Unreported results stay unknown.
- Outcome loop. Share an outcome in an ordinary host chat. Require the assistant to associate it with the right decision, preserve uncertainty, and stop asking about a completed outcome. A note-update proposal awaiting manual application does not establish an automatic closed loop.
- Lesson. Call `memory_propose_from_lesson` for the completed synthetic decision. Require a source-linked proposal. Keep Self unchanged until independent owner approval.
- Drift discrimination. Reformat and retimestamp a synthetic corpus without changing meaning. Run ordinary session starts across the cadence fixture. Require no asserted identity change. Then supply corroborated old/new beliefs and require a proposal that names both, cites evidence, and expresses uncertainty.
- Rejection. Reject the proposal through `memory_reject_self_update`. Repeat unchanged evidence. Require no equivalent new suggestion unless the reminder/reconsideration policy allows it and new evidence is named.

## Gotchas

Activity counts alone still establish no belief change. The integrated source can propose an attributed, explicitly uncertain change from matching before/after claims and lessons in at least two distinct completed decision sources with distinct outcome narratives. This is a conservative engineering threshold, not an owner-approved universal rule for identity. The signed proposal history suppresses recurrence on unchanged, renamed, rekeyed or copied evidence; inconsistent or unavailable history refuses. Fixed-outcome credit requires complete current-byte longitudinal observations through their strict adapter; host proof remains separate. Timed fixture state cannot replace a week of actual host behavior. Outcome completion requires the exact reviewed source mutation, not merely a populated pending list. Every resulting identity change remains unapproved until the owner independently uses their terminal.
