# Independent stabilization review — 18 October 2026

## Outcome and provenance

**Scoped independent assessment: 100/100, no cap.** This is a review judgment under the
declared rubric, not the corpus pass rate and not proof of exhaustive safety.

The reviewer began with fresh context, tested a frozen copy, reported six defects and a
**capped 40/100** assessment (uncapped weighted total 92), then independently replayed
its actual probes against a second frozen copy after repairs. The initial assessment
has not been erased or presented as a score for the repaired code.

Revalidated input: `ta-stabilization-review-jp_5d9q_/frozen`, under the session's approved
temp directory. All **167/167 source-file SHA-256 hashes matched**. Its manifest SHA-256 is
`e36e16184c77071c8c5e0d946950d06afa0f7dd38624c4872924bebc42568c0b`.
The reviewer used a new scratch copy, state directory, and fresh Python processes.

Original reviewer-authored reports and raw probes are retained at:

- `C:/Users/Gargeya/AppData/Local/Temp/opencode/ta-product-adversarial-20261018/REPORT.md`
- `C:/Users/Gargeya/AppData/Local/Temp/opencode/ta-product-revalidation-cycle1/REPORT-REVALIDATION.md`

Product modules in the working tree were hash-compared with the reviewed snapshot.
Later changes were verification/documentation-only. The live `People/Self.md` was unchanged.

## Findings and independent revalidation

- **F1, HIGH — forged drift metadata:** fixed. Genuine writer contention and the
  vault-file-only unusable-lock attack now return real file titles with frozen/blocked
  diagnostics. Forged cached dates do not determine inclusion.
- **F2, HIGH — forged entity-ID mapping:** fixed. IDs resolve from authoritative files;
  unique unindexed IDs work, duplicate IDs (including unindexed duplicates) are refused,
  and explicit paths remain deterministic.
- **F3, MEDIUM — concepts treated as pending decisions:** fixed. File-derived type is
  required for pending-outcome and lesson selection. Genuine decisions remain included.
- **F4, MEDIUM — failed quarantine credited as successful rebuilding:** fixed. The actual
  idle Windows SQLite-handle reproducer now reports unavailable full-text search and a
  blocked repair. Closing the handle permits recovery. Additional final-state fault
  injection raises before signing; manifest bytes remain unchanged.
- **F5, MEDIUM — list lesson crashes promotion:** fixed. The same list-shaped lesson
  creates a ledger-backed proposal through MCP, without applying identity changes.
- **F6, LOW — newly created notes omitted from timeline:** fixed. File-derived
  created-OR-updated filtering occurs before limits; forged cache dates neither suppress
  current notes nor admit stale ones.

**New confirmed severity findings during revalidation: none.**

## What the reviewer actually ran

- `python tests/test_stabilization.py`: **21 passed**.
- `python tests/score.py --json`: **70 passed, one Windows-specific skip**, 71 scenarios.
- `python replay_prior.py`: all ten original behavioral probe groups, replayed from the
  original probe source rather than reconstructed approximations.
- `python seam_probes.py`: three additional groups covering ID ambiguity/path precedence,
  file predicates before limits, and failed-repair/final-state recovery.
- `python verify_replay.py`: replay assertions, completed recovery, and input-integrity
  checks passed.

Successful paths retained: title/list metadata searches, byte-exact no-ops and disjoint
edits, failure-safe atomic replacement, explicit disk-full/partial-index diagnostics,
sandbox and junction refusal, public-accept/no-TTY refusal, approval-seam tamper refusal,
actual six-message NDJSON MCP lifecycle, and verifier failure/restoration/baseline checks.

## Scoring under unchanged weights

Identity safety **100** (weight 30); approval fidelity **100** (25); vault integrity
**100** (15); truthfulness of reads **100** (15); autopilot reliability **100** (10);
install/ops honesty **100** (5). No demonstrated remaining deductions.

Weighted total: `(30*100 + 25*100 + 15*100 + 15*100 + 10*100 + 5*100) / 100 = 100`.
The original headline truthfulness violation no longer reproduces, so no cap applies.

## Limits and separate maintainer checks

The reviewer did not personally build packaging or execute the full mutation catalog.
Exhaustive fuzzing, scale/concurrency exploration, real-host integration and actual
OS-terminal owner approval remain outside the review. Owner approval was explicitly
simulated; no-TTY CLI and MCP used real subprocesses. A failed probe is cached for five
seconds; a fresh caller independently demonstrated recovery.

Separately, the maintainer built the reviewed product snapshot and ran the checked-in
explicit-artifact smoke test: **57 wheel checks and 27 binary checks passed**, on Windows
with Python 3.13. The wheel's module bytes matched the reviewed source. Earlier results
from temp scripts with hard-coded older artifact paths are withdrawn as evidence for
new builds. Linux/macOS and Python 3.9 runtime execution are CI scope, not claimed local runs.

## Final maintainer gates

- 200 core tests, 21 stabilization/verifier tests, and 12 documentation tests: passed.
- 71 scenarios: 70 passed, one platform-specific skip; saved baseline has no regressions.
- All 51 targeted defect reversions: caught by the named assertion FAIL, with passing
  pristine and restored baselines. The ID-lookup mutation initially leaked its own SQLite
  handle and was correctly rejected as a setup failure; closing that handle fixed the
  mutation itself before the complete passing rerun. No product behavior was changed to
  make the verifier green.
- Artifact logs: `C:/Users/Gargeya/AppData/Local/Temp/opencode/ta-artifacts-stabilized-uaz2nhcl/`.
  Wheel SHA-256: `6ed20207496a62ea34f839c0d9eb07cdaf9a5fa76cb6bed434c27bda75e937f2`.
  Executable SHA-256: `5f842019f38ad68a228f441c5c2e76fca510892f2c02425215d761be72972bfe`.
- Product modules still match the independently reviewed snapshot; the frozen snapshot
  remains unchanged. No live identity edit, commit, publication or merge was performed.

Execution was Tier 2 because runtime, verification and review were separate units with
security implications. Implementation stayed in the main session; one fresh-context
reviewer supplied the independent gate, then revalidated repairs (first try: no; repair
cycle: one; token usage unavailable). The harness's default agent setting was used because
model/effort presets were not exposed here. The plan stayed in chat rather than creating
an extra visual page; no PR/merge gate was run because this task did not authorize one.
