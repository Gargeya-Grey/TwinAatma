# Fixed distance from the ideal

Run the scorer after each verification pass and supply every relevant current report. It scores observed product outcomes from the ideal-system contract. Passing regression tests, repaired bug counts, code size and effort do not enter the formula.

The v1 rubric has **54 mandatory, equal-weight, binary outcomes**. Its JSON file is the machine-readable source of truth. Each item names its expected result, required proof scope, criticality and the exact executable check IDs that can currently prove it. Items without an adapter remain unverified.

## Calculate and compare

From the repository root:

```powershell
python -B .agents/skills/verify-twinaatma/scripts/acceptance.py --source-report <core-report.json> --source-report <failure-report.json> --source-report <concurrency-report.json> --host-report <host-report.json> --baseline <previous-score.json> --output <fresh-score.json>
```

Omit `--host-report` while no genuine host run exists. Omit `--baseline` only for the first snapshot. Repeat report arguments for independent relevant runs. The output refuses an existing file so prior measurements survive.

- Verified fulfillment = 100 x outcomes with complete scoped PASS evidence / 54.
- Unresolved distance = 100 x all other outcomes / 54.
- Status counts distinguish PASS, FAIL, BLOCKED and NOT CHECKED. A partially observed outcome earns zero credit.
- Every unresolved mandatory outcome vetoes overall acceptance. Critical identity, grounding, privacy and data-preservation vetoes are also listed explicitly.
- The comparison lists newly verified and regressed outcomes and percentage-point changes. The baseline must have the identical rubric ID, digest, denominator and outcome IDs. Its counts and percentage are checked against its outcome rows.
- An outcome loses credit if its proof is omitted or no longer applies. A baseline carries historical evidence; it never silently carries old PASS claims into a new product.

The number is **verified fulfillment of this contract**, not the percentage of software complete, a probability of correctness, or a substitute for the vetoes. Unequal outcome difficulty and the limited current adapters prevent interpreting a one-point improvement as a uniform amount of engineering work. Keep the scope breakdown and unresolved outcomes beside every headline number.

## Evidence adapters

The source adapter consumes only the core, failure and concurrency reports from `scripts/verify.py`. It requires the current product hashes, the current producer hash in the source manifest, known executable check IDs, actual observations, a retained CLI/MCP transcript, passing source/isolation prerequisites, and stopped owned processes. It grants only source outcomes. Three source journeys cannot prove an installed artifact, host behavior, independent human consent, a week of use or a clean-device restore.

The genuine-host adapter consumes `verify-twinaatma.host/v1` reports from the current `scripts/host.py`. It requires host name/version/mode, the exact current product and producer hashes, retained hashed transcripts, expected and observed results, per-case evidence references, stopped owned processes, unchanged isolation sentinels, unchanged product bytes during observation, and verified source-server binding. Only known host case IDs can award the corresponding host outcomes.

A grader-only repair may regrade retained genuine observations after hash, product, isolation and shutdown validation. The report records the original report hash and labels the regrade. This does not count as another model trial. Changed product bytes require a new live journey.

Product binding includes every current `knowledgeos/*.py`, `.cursor/hooks/*.py` and root `AGENTS.md`. A report must match all of them. Reports and referenced transcript hashes are retained in the score. The scorer also records its own hash and the rubric hash. A source edit therefore requires fresh applicable proof before the outcome earns credit again. The adapter does not extrapolate this binding to an untested wheel or binary.

A raw hand-authored checklist, unfamiliar producer, unknown PASS case, missing observation, stale product/producer hash, altered transcript, duplicate ID, escaped evidence path, or unsubstantiated process shutdown is rejected. Conflicting evidence is conservative: a supplied FAIL remains FAIL even if another supplied run passes. Supply the designated current rerun and retain its failed predecessor separately.

Local producers and the evidence recorder are trusted. Hash binding detects edits and staleness after capture; it cannot establish that a dishonest producer or human never fabricated an observation. The independent owner gate remains unverified until genuine owner evidence exists. Do not replace it with a simulated TTY or agent-written approval claim.

## Keep the target fixed

Freeze a baseline before changing the product. Never remove inconvenient items, change weights, lower thresholds or convert unknowns into passes to improve the score. A deliberate acceptance-contract change needs a new rubric version and a separately labeled baseline; the old and new headline percentages are not directly comparable.

The fixed rubric covers all ten mandatory ideal gates. The resource-budget outcome requires fresh measurements at all scales against the owner-approved Windows laptop limits in the ideal-system contract; the approved budget alone does not verify implementation. The optional Notion adapter release gate is explicitly outside this core-local denominator and requires its own acceptance before being advertised as supported. A core-local score does not certify it.

The [installed-package adapter](installed-packages.md) requires the complete Windows/Linux wheel/executable matrix for `SETUP.artifact_install`. It separately fingerprints the exact current shipped assets and build inputs. It accepts genuine installed-host traces bound to the retained artifact without calling them source-server proof. New evidence adapters are versioned and hashed in snapshots; they preserve the rubric and its existing outcome semantics.

For future adapters, require the actual public-surface journey, scope and exact artifact identity first, then meaningful scorer rejection tests. Add mappings to the existing outcome only when the complete expected result is proved. Preserve the denominator and rubric semantics; document a version change when the acceptance meaning changes.

The first frozen snapshot is `work/gc-artifacts/.knowledgeos/host-acceptance-20261019/metric/baseline.json`. It imports the three retained source journeys from the preceding repair pass against their then-current exact product bytes. It verifies 12/54 outcomes (22.222222%) and leaves 42/54 unresolved (77.777778%). This is a baseline of available accepted proof, not a claim that the other 42 outcomes all fail.

The [runtime-hook adapter](runtime-hooks.md) adds the complete Windows/Linux CPython
3.9 through 3.14 wheel matrix and two frozen binaries for the existing
`SETUP.runtime_hooks` outcome. Actual isolated interpreter output, installed bytes,
generated shell commands and shutdown are checked independently. Fourteen passing
cells award one fixed outcome. Missing cells earn no partial credit.

Adapter v2 also maps the complete core configuration-preservation and required
post-init failure journeys to their existing SETUP outcomes. The core trace retains
21 merge/refusal cases across the three writable host formats and a real obstructed
initialization with nonzero exit and truthful partial state. These are two outcomes;
they do not inherit artifact or owner approval credit.


Adapter v3 accepts the three complete source [data-preservation journeys](data-preservation.md)
through repeated `--data-report` arguments. It binds the entire copied toolkit,
including source-only scripts, and requires exact known case sets, hashed evidence,
actual command/PID/exit records and selected-sentinel isolation. Each producer can
prove only its mapped existing DATA outcome. No source data report can prove an
installed artifact, genuine host, independent owner or privacy policy outcome.

Adapter v4 adds the three literal maintenance, hook-preservation and validation
case sets through the same `--data-report` argument. It independently binds traced
nested children to their parent's retained stderr and exact command, including the
two map-generator scripts. A missing case, linked evidence, changed copy, invented
child, mismatched trace or unsupported platform skip earns no credit. These map
only to DATA.safe_maintenance, DATA.preserve_hooks and DATA.honest_validation.
All original rubric outcomes, criticality and required scopes remain unchanged.

Adapter v5 requires all 48 generated-writer v2 cases, including the previously
omitted weekly draft, and the ten-output census v2 proof. Earlier partial writer
inventories earn no complete generated-report credit. It adds the two source
identity journeys and the two independently graded quality evaluation outcomes
through `--identity-report` and `--quality-report`. See the
[source identity and quality recipe](source-identity-quality.md). A complete valid
corpus can pass while its retrieval target fails; neither result implies owner,
privacy, host-answer or longitudinal acceptance. The 54-outcome rubric is unchanged.


Adapter v6 adds the complete sixteen-case source graph journey and six-case
index-recovery journey. Ownership requires both fifteen ordinary native lock cases
and three native POSIX partial-marker-write cases. Repeated --graph-report and
--recovery-report arguments bind actual protocol bytes, literal cases, full source
inventories, native holder ownership and stopped processes. These map only to the
existing MEMORY.correct_links, RECOVERY.index_degradation and
RECOVERY.ownership_locks outcomes; the rubric remains unchanged at 54. A complete
FAIL remains FAIL. See [source graph and recovery](source-graph-recovery.md).


Adapter v7 accepts the complete twelve-case source learning journey through repeated
`--learning-report` arguments. It independently grades the existing
`LEARNING.decision_views` and `LEARNING.attributed_lessons` outcomes from exact
literal source states, original public MCP requests/responses, unchanged complete
toolkit inputs, actual native SQLite-holder observations, retained draft bytes,
selected-sentinel isolation and stopped direct/nested process records. Both
outcomes require the shared source/Self preservation case. A real project-filter
failure remains FAIL while independent attributed-lesson proof can pass. The
54-outcome rubric, quality thresholds and every other scope remain unchanged.
See [source decision views and attributed lessons](source-learning.md).

Adapter v11 retains the fixed 54 outcomes and adds complete native alternative-writer source preservation. It also supports fresh native Windows independent grading of retained genuine-host observations while the cumulative scorer inspects Linux evidence natively. The transport binds a fresh nonce, complete source/report/helper/runtime/dependency hashes and actual stopped Windows child records. A file rendezvous can connect the native graders when WSL executable interop is unavailable. No transport control or source preservation case supplies human approval or another model trial. Changed product bytes still require fresh applicable journeys.


Adapter v12 preserves the same 54-outcome rubric. The complete native Windows wheel and executable relocation pair maps only to `PORT.same_device_move`; partial pairs earn no credit and supplied failures remain failures. Each original report is freshly graded through the pinned Windows observer, including when the cumulative scorer runs in Linux. Separate per-report nonce channels prevent replaying cached grades. The advanced host adapter requires exact raw v2 bytes, a current product freeze, three distinct completed model chats and the new direct authorization plus single-use claim for that payload. Neither offline corruption controls nor local native tool calls earn genuine model-conversation credit. See [native installed relocation](installed-native-move.md).


## CI-graded route: native Linux and extra CPython runtimes

The laptop has Windows only, and WSL, virtual machines and containers are not used. The evidence that needs native Linux or CPython 3.9 through 3.14 is produced on GitHub-hosted runners by `.github/workflows/acceptance-evidence.yml` (trigger: `workflow_dispatch`, or a push to a branch named `acceptance/**`). Each job runs the existing producers unchanged, grades its own raw reports natively with the existing grading functions in `acceptance.py` and `identity_writers_grade.py`, and writes one bundle of the normalized report dictionaries those functions returned. The bundle also holds the commit, run ID and attempt, platform, product, scorer and adapter-requirement hashes, and the hash of every raw report. The workflow attests the bundle with `actions/attest-build-provenance` and uploads it as `ci-graded-linux` and `ci-graded-windows`; the raw reports go up as `raw-evidence-*` for audit.

Import on the laptop with a repeatable flag. The scorer needs `gh`, signed in to an account with access to the repository (the importer reads a token with `gh auth token --user <repository owner>` when `GH_TOKEN` is not set, and never prints it):

```powershell
python -B .agents/skills/verify-twinaatma/scripts/acceptance.py --ci-graded <ci-graded-linux.json> --ci-graded <ci-graded-windows.json> <local Windows report arguments> --output <fresh-score.json>
python -B .agents/skills/verify-twinaatma/scripts/ci_graded.py inspect <bundle.json>
```

The importer refuses a bundle unless all of these hold: `gh attestation verify` accepts the file for this repository and the acceptance-evidence workflow, and the signed commit, run ID and attempt equal the ones the bundle states; the commit equals the local `git rev-parse HEAD`; the product hashes, the 102 toolkit hashes, the scorer hash and the adapter-requirements hash equal the local ones; the digest of the graded rows still matches; and every row is well formed, in the platform's own matrix, with known check IDs and an artifact or source scope. Hashes are compared with CRLF folded to LF, because git checks the same commit out as LF on Linux and CRLF on this laptop; the commit equality fixes the committed content. A new commit needs a new run.

Rows enter the same places the local graders feed. Artifact cells join the list before `artifact_matrix`, runtime-hook cells the list before `runtime_hook_matrix`, data and recovery rows go into the report list, and the Linux writer result goes into the writers bundle as a pre-graded platform. The writers bundle keeps every check it had: both native platforms, every writer family, recovery, learning and the tool-refusal coverage are still required. A FAIL row stays FAIL. Cells the runner could not grade are listed in the bundle and printed to stderr; they earn nothing.

Which outcomes the route can complete, with the Windows rows from the laptop:

- `SETUP.artifact_install`: Linux wheel and executable from the Linux bundle, Windows pair from the laptop.
- `SETUP.runtime_hooks`: all 14 cells come from the two bundles.
- `RECOVERY.ownership_locks`: `recovery.py --journey write-faults` from the Linux bundle, `--journey locks` from the laptop.
- `DATA.preserve_hooks`: the complete Linux `maintenance.py --journey hooks` report. A NOT CHECKED row beside a PASS row is not a PASS, so do not supply the laptop's Windows hooks report (two NOT CHECKED symlink cases) with it.
- `IDENTITY.all_writers_preserve`: the Linux writers result, graded on the runner against an in-job freeze of the checked-out commit, plus the Windows writers report and the data, source, recovery and learning reports from the laptop.

Trust model. The route trusts a GitHub-hosted runner, the workflow file at the attested commit, and the Sigstore attestation that binds the bundle bytes to that workflow run. It adds no protection against a dishonest producer: as for local producers, hashes prove binding, not honesty. The laptop does not regrade the raw reports, because the graders need the installation the runner built. It awards nothing beyond artifact- and source-scoped check IDs. It never awards host, human or clean-device outcomes, and a bundle row with another scope or check ID is refused. A runner is a clean Linux or Windows machine of the hosted image, not the owner's device.
