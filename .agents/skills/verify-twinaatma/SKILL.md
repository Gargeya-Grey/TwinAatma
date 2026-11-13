---
name: verify-twinaatma
description: Verify TwinAatma CLI, MCP, host-chat memory, identity approval, recovery, and portability against observable product outcomes. Use before claiming a feature works or assessing readiness.
---

# Verify TwinAatma

Prove the promise in `AGENTS.md`: after one successful setup, the person receives grounded help without operating memory infrastructure. Preserve the human-only identity boundary.

Read [the feature index](features/README.md) first, then the file of the feature you change. `docs/product-direction.md` holds the scorecard that decides readiness, and `docs/threat-model.md` holds the release bar for safety.

## Choose the proof

- A focused change needs the suites its feature file names, then the first-day journey.
- A push needs the full suite, the scorecard and the mutation check, each run once.
- A readiness claim also needs a real chat in a real host, and a person's own review in a terminal. No script in this repository replaces either.
- A source result proves source CLI and MCP behaviour in synthetic vaults. An installed package, a host chat, answer quality and human consent are separate verdicts.

## The checks

Run every command from the repository root. Close standard input (`< /dev/null`, or `< NUL` in cmd), because a hook test reads it. On Windows, use a checkout with a short path: at a path of 56 characters, 54 tests in five files fail with `WinError 3` or `WinError 206`, because their fixtures lie deep under `work/gc-artifacts`. A worktree below `.claude/worktrees/` is too deep.

| Check | Command | Time on the builder's Windows machine |
|---|---|---|
| First-day journey | `python -B .agents/skills/verify-twinaatma/scripts/first_day.py --output <new-dir>` | under 1 minute |
| Full suite | `python -B -m unittest discover -s tests` | about 15 minutes |
| One suite | `python -B -m unittest discover -s tests -p test_first_contact.py` | seconds to minutes |
| Scorecard | `python tests/score.py` | about 1 minute |
| Mutation check | `python tests/mutation_check.py` | about 3 minutes |
| Documents | `python tests/test_docs.py` | seconds |
| Package | `python -B tests/package_smoke.py --wheel <wheel> --source .` or `--binary <executable>` | about 1 minute |
| Recall evaluation | `python -B .agents/skills/verify-twinaatma/scripts/quality.py --output work/gc-artifacts/.knowledgeos/<new-name>` | about 17 minutes |

CI (`.github/workflows/ci.yml`) runs the suite on Linux and Windows with Python 3.11 and 3.13, the scorecard, the mutation check, the document check, a wheel install on Python 3.9 to 3.14 and both binaries.

### First-day journey

`first_day.py` drives the real command line and the real MCP stdio server on a synthetic vault: init, first chat, capture, import, review refusal, second chat, searches, the Claude Code hook, both user-level command lines and doctor. It sets its own `KNOWLEDGEOS_STATE_DIR`, compares `People/Self.md` with its state right after init after every stage, prints one PASS or FAIL line per check and writes `report.json`. It makes no model call. [The first day](features/first-day.md) lists what it covers.

### Mutation check

`tests/mutation_check.py` puts one known defect at a time into the code and requires a scenario to fail. `tests/test_mutation_targets.py` fails in the ordinary suite when a seeded defect no longer finds its place. After a rewrite of code that a seeded defect names, run the mutation check.

### Recall evaluation

`quality.py` asks 108 frozen questions (`tests/fixtures/quality-v3.json`: 72 earlier cases and 36 held-out cases over 126 notes) through real MCP startup and writes a report with a verdict. It is not part of CI or of the suite, because it takes about 17 minutes. Run it after a change to search, ranking, the concept lexicon or the startup context. Run it from a short path: a deep output path fails on Windows. `data_preservation.py` in the same folder is its support module. `tests/test_quality_verifier.py` checks that the evaluation refuses a changed fixture and scores as documented.

Result on 13 November 2026 at `69bec1e`: verdict PASS; 91 cases pass, 3 fail, 14 not applicable; every critical source is offered (44 of 44); held-out 32 of 32. The labels are not exhaustive, so the precision figure in the report (138 of 738) is a lower bound.

## Rules for every run

- Use a synthetic person and a task-owned vault. Never point a check at the working vault or at a live host's instance.
- Place fixtures below a `.knowledgeos` folder under `work/gc-artifacts`. The note census skips that folder, so a synthetic identity never becomes memory.
- Each run owns its vault and its state folder. Independent runs may run in parallel.
- Never answer an approval prompt, never edit `People/Self.md`, never write a proposal file by hand. `self approve` and `self review` need a real console and a person.
- Never run `setup-host --global` without `--print` on the owner's machine.
- A nonzero exit is a failed behaviour or an execution error. Read the report in the printed folder. A known product failure is still a failure.

## A real host chat

No driver in this repository starts a model. To prove a host journey, use a fresh vault and a separate host profile, keep unrelated host configuration unchanged, and record the host version, the tools the host found, the calls it made and the final answer. For Claude Code without a change to anyone's settings, write the JSON part of `setup-host --host claude-code --global --print` to a new file and start `claude --settings <that file>`. `docs/try-it.md` is the script for a person who is not the builder. If the host is unavailable, report NOT CHECKED.

## Doctor

```powershell
python -B -m knowledgeos doctor --vault <fixture-vault>
```

Set `KNOWLEDGEOS_STATE_DIR` to the fixture's state folder for this call and restore the earlier value afterwards. A passing doctor does not prove that a host found the server or used the memory.

## Verdicts and evidence

Use PASS, FAIL, BLOCKED, NOT CHECKED and NOT APPLICABLE. Give each verdict its action, the expected result, the actual result and the evidence path. An entry point that was not run stays NOT CHECKED, also when another entry point passed. Never average away an identity, data-loss, privacy or grounding failure with a pass rate.

## Cleanup

A driver closes standard input and waits for its own MCP process. On a timeout it stops that exact child. It never stops a process by name. Delete a run folder you made when its job ends. Leave folders you did not make, and name them in the report.

## What this skill no longer holds

Until 13 November 2026 this skill also held a 54-outcome acceptance programme: 46 more driver and grader files, 37 test files for those files, 16 reference documents and two workflows. It was removed because it tested its own evidence format and not the product: the removed tests alone ran 15 lines of the package, and those behaviours now have direct tests. The last commit that holds the whole programme is `69bec1e`. The journeys it drove and that no kept check drives are named as "not checked" in each feature file.

## Maintain

Keep feature IDs stable. Add a newly found failure as a test that fails before you plan its repair. Update the feature file and the index when a user entry point changes. A test stays when it fails for a fault that a user or a caller of the toolkit can observe.
