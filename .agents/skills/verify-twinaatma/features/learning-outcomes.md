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

## What checks it

Preconditions: synthetic decisions with known pending and closed states, dates, sources and lessons. Run one suite with `python -B -m unittest discover -s tests -p <file>`.

- Outcome recording. `tests/test_outcome_recording.py`: discovery, review, recording and an exact retry; the source hash and literal fields; pending and reminder closure; refusal of a stale or protected source; a truthful answer while the index is busy.
- Decision views and review timing. `tests/test_followup_review.py` and `tests/test_project_precision.py`: an old decision with blank outcome metadata asks for no review, an explicit pending outcome or a due date does, and rows that were already asked leave the queue before it is cut.
- Lessons and drift. `tests/test_evidence_learning.py` and class `LearningEvidenceTests` in `tests/test_learning_repairs.py`: a proposal needs two distinct completed sources and names them with its uncertainty; formatting churn is no evidence; a rejected proposal does not return without a new completed source.
- Identity. Each of these suites leaves Self unchanged. No check invokes approval.

Not checked by any script: an outcome shared in an ordinary host chat and tied to the right decision, and a week of real use. The driver for each was removed on 13 November 2026; the last commit that holds it is `69bec1e`.

## Gotchas

Activity counts alone still establish no belief change. The integrated source can propose an attributed, explicitly uncertain change from matching before/after claims and lessons in at least two distinct completed decision sources with distinct outcome narratives. This is a conservative engineering threshold, not an owner-approved universal rule for identity. The signed proposal history suppresses recurrence on unchanged, renamed, rekeyed or copied evidence; inconsistent or unavailable history refuses. Timed fixture state cannot replace a week of actual host behavior. Outcome completion requires the exact reviewed source mutation, not merely a populated pending list. Every resulting identity change remains unapproved until the owner independently uses their terminal.
