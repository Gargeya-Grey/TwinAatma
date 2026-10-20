---
name: verify-twinaatma
description: Verify TwinAatma CLI, MCP, host-chat memory, identity approval, recovery, and portability against observable product outcomes. Use before claiming a feature works, assessing readiness, or planning backwards from the ideal system.
---

# Verify TwinAatma

Prove the promise in `AGENTS.md`: after one successful setup, the person receives grounded help without operating memory infrastructure. Preserve the human-only identity boundary.

Read [the feature index](features/README.md) first. For a readiness review or backwards plan, also read [the ideal-system contract](references/ideal-system.md). Consult [the dated assessment](references/current-assessment.md) for original gaps and [the repair status](references/repair-status.md) for subsequent changes, then recheck the current code. An old observation is not a current verdict.

## Choose the proof

- A focused change needs its mapped journey and relevant existing regression checks.
- A product-readiness claim needs every mandatory ideal gate, including real host chats and independent human approval evidence.
- A source smoke result proves source CLI and MCP behavior in synthetic vaults. Keep installed artifacts, host integration, answer quality, and human consent as separate verdicts.
- A missing future capability is an unmet acceptance gate. Preserve its expected outcome rather than weakening the journey to match today's implementation.

## Launch

From the repository root, use Python 3.11 or newer for the source driver:

```powershell
python -B .agents/skills/verify-twinaatma/scripts/verify.py --journey core --output work/gc-artifacts/.knowledgeos/verify-twinaatma
```

The driver creates a unique run directory, initializes a fresh vault through the CLI, and requires a usable Self file, successful post-init checks, and a passing doctor. It launches the real `python -P -m knowledgeos mcp --vault <fixture> --framing ndjson` process. The driver supplies the explicit checkout import path, isolated gate state, and explicit fixture vault. It does not install or prove an installed distribution.

Every output path must contain a .knowledgeos directory beneath work/gc-artifacts. The root note census skips that component, keeping synthetic identities out of working memory. The driver refuses an uncontained output path.

Every run owns its vault and gate state. Independent runs may run in parallel. Never point these journeys at the user's working vault or reuse a live host's instance.

For prompt and failed-summary recovery, run:

```powershell
python -B .agents/skills/verify-twinaatma/scripts/verify.py --journey failure --output work/gc-artifacts/.knowledgeos/verify-twinaatma
```

For separate chats, replay, the end hook, and 20 simultaneous MCP capture processes, run:

```powershell
python -B .agents/skills/verify-twinaatma/scripts/verify.py --journey concurrency --output work/gc-artifacts/.knowledgeos/verify-twinaatma
```

The helper retains startup session IDs across process restarts and passes them to wrap-up. Concurrent journeys use explicit distinct IDs. This does not establish that a real host propagates IDs correctly.

A nonzero exit means a failed behavior or execution error. Inspect `report.json` and `transcript.jsonl` in the printed directory. Known product failures are still failures. The driver does not repair them.

## Real Codex host

Run the genuine-host journey with the signed-in Codex CLI and Python 3.11+:

```powershell
python -B .agents/skills/verify-twinaatma/scripts/host.py --output work/gc-artifacts/.knowledgeos/verify-twinaatma-host
```

This uses native project configuration, a synthetic vault and task-owned profiles.
It ignores unrelated user configuration, disables optional app/plugin catalogs for
the task-owned host invocation, retains the configured model, and uses the
existing host sign-in without copying credentials. Three genuine model conversations
capture a fact, recall it after process restart, abstain on an unknown, and wrap two
concurrent chats with separate IDs. A transparent wire proxy runs the exact generated
server command and retains requests/responses. Host usage counters and durations are
observations, not performance acceptance. This is source-backed Codex CLI acceptance;
desktop UI, installed-artifact host wiring and other hosts remain separate gates.

After changing only a grader, re-evaluate unchanged retained observations with
`host.py --replay <original-report.json> --output <fresh-contained-output>`. Replay
requires unchanged product bytes and isolation sentinels, retained transcript hashes,
and original shutdown proof. It records its original report and explicitly labels the
result as a regrade; it is never an additional live trial or a substitute for rerunning
a changed product. Keep the original successful and failed trials.

## Installed packages

Use [the installed-package recipe](references/installed-packages.md) for exact wheel
and executable acceptance. The build driver retains input hashes, commands and full
runtime inventories. The artifact driver installs outside the checkout import path;
the installed-host driver launches that exact installation through genuine Codex.
Source-host proof cannot substitute for this journey. The release-install outcome
requires wheel and executable on both Windows and Linux. Use [the real-runtime hook
recipe](references/runtime-hooks.md) for generated start/end commands on CPython
3.9 through 3.14 and both frozen binaries. Desktop invocation and other hosts remain
separate evidence scopes. Follow [native installed relocation](references/installed-native-move.md)
for zero-model Windows host calls before, after and after reuse of the old path.
The complete current wheel and executable pair can verify only the existing
`PORT.same_device_move` outcome. A native protocol call does not prove a model chat,
clean-device restore or independent approval.

## Source data preservation

Follow [the data-preservation recipe](references/data-preservation.md) for complete
synthetic toolkit copies, safe exports, all public generated writers, and the shared
personal-memory census. The same recipe drives ID/link/map maintenance, Git hook
preservation and both validation commands through `maintenance.py`. The drivers
retain exact commands, full before/after source inventories, injected filesystem
failures, retry observations and stopped direct and traced nested children.
They prove source behavior only. Native link setup failures remain unresolved.

## Source identity and retrieval

Use [the identity and quality source recipe](references/source-identity-quality.md)
for `identity.py --journey unknown`, `identity.py --journey canonical` and the
frozen 36-case `quality.py` startup evaluation. These public-process checks keep
owner approval, host answers, privacy and representative use as separate gates.
A valid corpus can pass while retrieval fails.

Use [complete alternative-writer preservation](references/source-identity-writers.md) for the native Windows/Linux focused journeys and required source-family reports. Include both focused reports with repeated `--identity-writers-report`. Source preservation never grants independent owner approval.

## Policy and longitudinal source proof

Use [the privacy source recipe](references/source-privacy.md) for the 44-case
policy, exposure and external-write refusal journey, then include its original
report with `--privacy-report`. Use [the longitudinal source recipe](references/source-longitudinal.md)
for 27 semantic-evidence and signed-rejection cases, then include the original
report with `--longitudinal-report`. Their strict adapters recompute retained
public-process evidence. These scopes cannot award genuine-host, elapsed-week,
independent owner or clean-device outcomes.

## Quantify every verification iteration

The fixed [54-outcome rubric and scoring contract](references/acceptance-scoring.md)
measures verified fulfillment and unresolved distance. Unknown, blocked and failed
mandatory outcomes remain in the denominator. Safety failures veto readiness.
Source and host drivers emit run-only `acceptance.json`. Artifact reports are combined
through the complete release matrix. Partial coverage is not a cumulative
progress comparison. After a repair proof batch, combine its current, hash-matching
source reports and host report with the immutable baseline:

```powershell
python -B .agents/skills/verify-twinaatma/scripts/acceptance.py --source-report <core/report.json> --source-report <failure/report.json> --source-report <concurrency/report.json> --host-report <host/report.json> --artifact-report <wheel-win/report.json> --artifact-report <binary-win/report.json> --artifact-report <wheel-linux/report.json> --artifact-report <binary-linux/report.json> --baseline <baseline.json> --output <fresh-score.json>
```

Report the fixed denominator, verified count/percentage, unresolved count/percentage,
newly verified and lost-proof outcomes, remaining critical vetoes, and evidence scope.
Never change criteria to improve the number. A revised contract needs a new rubric
version and an explicit migration; snapshots from different rubrics are incomparable.
Choose the next work by dependency and risk among unresolved outcomes, not by which
check is easiest to make green. Read [the ideal contract](references/ideal-system.md)
for quality, human consent and device targets that are still mandatory.

## Doctor

On the driver-owned fixture, the read-only readiness command is:

```powershell
python -B -m knowledgeos doctor --vault <printed-run-directory>/vault
```

Replace the path with the one actually printed. Run from the trusted checkout so its source module resolves. For this manual doctor, set KNOWLEDGEOS_STATE_DIR to the run's gate-state directory and restore the prior environment value afterward. Confirm the interpreter with `python --version`. The driver independently checks the MCP server identity during initialization and captures the actual commands. A passing doctor does not prove that a host discovered the server or consumed memory context.

If readiness fails, retain the attempted command and error. Diagnose that instance rather than attaching to another process.

## Drive

The note census excludes toolkit and task directories, including .agents, work and outputs. Regression checks cover instruction and fixture exclusion. Keep synthetic fixtures below .knowledgeos as defense in depth; do not refresh the working vault merely to verify this skill.

The helper exercises public CLI commands and JSON-RPC `initialize`, `notifications/initialized`, and `tools/call` over real stdio pipes. It restarts the process between batches to prove durability. It reads generated files as an independent view of writes. It uses normal filesystem changes to simulate an external note editor and an unavailable Inbox.

Read the matching feature file for additional entry points. CLI fallback is not equivalent to host-chat proof. For real-host checks, use a separate host profile and synthetic vault, preserve unrelated host configuration, and capture host version, tool discovery, actual call trace, and the resulting answer. If the host is unavailable, report NOT CHECKED.

## Evidence

Each run retains:

- `report.json` with revision, dirty-tree inventory, selected source hashes, interpreter, observed assertions, and process shutdown results.
- `transcript.jsonl` with exact CLI commands, MCP requests, responses, stdout, stderr, and exit codes.
- The synthetic vault and isolated gate state needed to inspect side effects.

The helper's real-vault isolation check compares sentinel files only. The explicit vault and state-directory arguments provide additional isolation. Do not call this an exhaustive filesystem audit.

Use PASS, FAIL, BLOCKED, NOT CHECKED, and NOT APPLICABLE. Attach the action, expected result, actual result, and evidence path to each verdict. A blocked or untested mandatory gate prevents an overall PASS. Record denominators and skipped platform checks. Never average away an identity, data-loss, privacy, or grounding failure with a corpus score.

Register only actual task evidence according to `C:/Users/Gargeya/Documents/Codex/harness-gc/AGENT-WORKFLOW.md`. Synthetic fixture files, database files, gate keys, and source files are not real-task observation registrations. If the shared observer cannot write its registry, retain a local handoff receipt and report the integration gap.

## Cleanup

The driver closes stdin after each request batch and waits for its own MCP process. On interruption or timeout it stops that exact child and waits. It never kills by process name. Inspect `all_started_mcp_processes_stopped` and each PID record.

For host journeys, close only the task-owned profile, tab, or process, and record the actual result. Retain reports, transcripts, fixtures, and gate state. Restoring the failure fixture moves its synthetic obstruction aside without deleting it. This skill does not collect or quarantine artifacts.

Before handoff, confirm the evidence still exists after shutdown and write a durable receipt outside the disposable run root. Declare source-only, platform, host, packaging, or human-approval limits.

## Maintain and work backwards

Keep feature IDs and their outcomes stable. Add a newly discovered failure as a reproducible acceptance case before planning its fix. Update the feature index when a user entry point changes.

Choose the earliest failed dependency in the ideal-system contract, produce the smallest change that can make its journey pass, and rerun it. Keep the remaining gates visible. The current regression score is supporting evidence, never the definition of the ideal product.
