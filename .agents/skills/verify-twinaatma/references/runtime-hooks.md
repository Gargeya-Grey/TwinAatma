# Generated hooks on real runtimes

Run this after building current candidates with `scripts/build.py`. The fixed
`SETUP.runtime_hooks` outcome requires Windows and Linux wheels on each CPython
minor from 3.9 through 3.14, plus both native frozen binaries. These are fourteen
matrix cells proving one outcome. An incomplete matrix earns no point. A newly
supported stable minor requires an additional cell on each platform before making
a current compatibility claim.

Use Python 3.11+ with pip to orchestrate the driver. Supply an actual target
interpreter, never a mocked `sys.version_info`:

```powershell
python -B .agents/skills/verify-twinaatma/scripts/runtime_hooks.py --python <actual-python-3.9> --wheel <current-wheel> --output work/gc-artifacts/.knowledgeos/runtime-hooks/windows-3.9
```

Repeat for each actual runtime and platform. Binary mode uses its bundled
interpreter and requires its exact build manifest:

```powershell
python -B .agents/skills/verify-twinaatma/scripts/runtime_hooks.py --binary <current-executable> --build-manifest <build-manifest.json> --output work/gc-artifacts/.knowledgeos/runtime-hooks/windows-binary
```

The driver creates a retained pip-less venv with `--copies` under an installation
path with spaces and installs only the supplied wheel. A copied Linux interpreter
remains a real target-runtime executable and can be inspected from Windows without
following LX reparse links. Use an orchestration pip that supports the oldest
target; the current matrix uses pip 25.1.1 after pip 26.2.1 refused Python 3.9
in the retained preflight.
The driver clears checkout import settings and records actual
interpreter identity, installed origin, module/assets inventory and launcher hashes.
Frozen acceptance binds the complete distribution and manifest. Its embedded minor
is labeled unavailable rather than inferred from a builder command.

It runs both exact generated shell commands from a synthetic vault containing `&`,
empty PATH and hostile PYTHONPATH. Vault-local hook, package, startup and standard
library shadows must never execute. The start hook must index a newly added literal
note before any memory tool runs. Returning context and exit zero alone is insufficient.
Repeated warm-up must consume no genuine session or soft prompt. Two explicit public
session IDs then prove targeted end events, retry idempotence, retained unfinished
work and deferred recovery. Self bytes must remain identical.

Keep each report, hashed command/stdin/stdout/stderr, generated configuration,
state observations, original package and installation after child shutdown. Combine
all fourteen reports with the existing source, installed-host and four release
artifact reports using repeated `--runtime-hook-report <report.json>` arguments to
`scripts/acceptance.py`. Copied interpreter fixtures allow the pinned native Windows
scorer to inspect the complete matrix. Native Linux grading is also supported,
but full source-inventory validation on a Windows-mounted drive can be slow.
Never replace an interpreter link after collecting a report; regenerate every
cell when the producer changes. The adapter rejects changed producers, stale product/build
inputs, altered transcripts, misdeclared interpreter minors, missing cases,
unsubstantiated shutdown and duplicate cells. The original 54-item rubric is unchanged.

This proves generated commands ran on the recorded CPython implementations and
Ubuntu WSL/Windows installations. It does not claim Cursor desktop invoked those
commands, another Python implementation passed, a future runtime works, or a clean
physical Linux device was used. Source-only Python 3.9/3.10 initialization refuses
unless isolated import resolves this exact installed package. Windows setup refuses
paths containing `%`, `!`, quotes or control characters before writes because the
host shell cannot preserve them through this command contract. POSIX uses shell
quoting. Keep these explicit refusals in the compatibility report. Agent tests are never
independent owner approval.
