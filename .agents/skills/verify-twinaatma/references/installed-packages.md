# Installed-package proof

Keep the v1 rubric unchanged. `SETUP.artifact_install` needs all four declared
release-install cells: Windows wheel, Windows executable, Linux wheel, Linux
executable. This gate does not establish every supported Python hook runtime.
An incomplete matrix earns no fractional outcome. Genuine installed-host traces
strengthen the existing host outcomes; repeated proof earns no duplicate credit.

## Build and retain

Use Python 3.11+ for these engineering drivers, with pip, setuptools, wheel and
PyInstaller available in the builder environment. Product dependencies remain
stdlib-only. Provision tooling into a task-owned environment when needed.

```powershell
python -B .agents/skills/verify-twinaatma/scripts/build.py --output work/gc-artifacts/.knowledgeos/installed-proof
```

The driver copies enumerated toolkit inputs into a unique build directory; it does
not copy private vault content. It builds a wheel and native executable, preserving
commands, logs, current input hashes, full dependency bytes and contained link
metadata in `build-manifest.json`. Build separately on Windows and Linux. WSL Ubuntu
is Linux evidence, not a clean physical device or another host application.

The manifest layout is deliberate: `wheel/<candidate>.whl` and its sibling parent
`build-manifest.json`; the executable is under `dist/twinaatma/`. The acceptance
adapter independently checks current build inputs and shipped assets. A wheel
without the required build provenance stays unaccepted even if installation works.

## Install each exact candidate

Substitute the actual printed paths; preserve unsuccessful candidates and reports.

```powershell
python -B .agents/skills/verify-twinaatma/scripts/artifact.py --wheel <build>/wheel/<candidate>.whl --output work/gc-artifacts/.knowledgeos/installed-proof/wheel
python -B .agents/skills/verify-twinaatma/scripts/artifact.py --binary <build>/dist/twinaatma/twinaatma.exe --build-manifest <build>/build-manifest.json --output work/gc-artifacts/.knowledgeos/installed-proof/binary
```

On Linux use that platform's Python environment and executable without `.exe`.
Each run retains its isolated environment, vault and signing state. Wheel setup
creates a pip-less target venv and uses the builder's pip `--python` option to
install offline with no dependencies. It verifies the isolated import origin,
current module bytes, capture/recall, initialization/doctor, exact generated
installed launcher and identity invariance. Binary proof fingerprints the complete
runtime and permits only links whose resolved targets remain inside it.

Raw artifact reports provide observed component checks. They require the
acceptance adapter's independent current asset/build-input validation before they
can earn a current-artifact acceptance outcome. The installed-host driver runs
that validation before any model call and again before accepting the result.

## Drive the genuine host

On a signed-in Codex CLI, run once for each prepared supported artifact:

```powershell
python -B .agents/skills/verify-twinaatma/scripts/installed_host.py --artifact-report <artifact-run>/report.json --output work/gc-artifacts/.knowledgeos/installed-proof/host
```

This uses three normal conversations, including restart and two concurrent chats,
against the retained installed executable. The protocol proxy imports verification
code in its own process; the memory server runs the exact generated installed
command, with no checkout `PYTHONPATH`. Retain raw calls, final replies, correlation
IDs, durable summaries and shutdown records. A failed startup stops further model
calls. Desktop and other host applications remain independent evidence gaps.

After a grader-only repair, use `--replay <original-host-report.json>` with the
same `--artifact-report` and a fresh output directory. It validates unchanged
product/artifact data, isolation, transcript hashes and original shutdown proof,
then regrades those exact observations. It is labeled as replay and earns no
additional trial count. Changed product or artifact bytes require new live proof.
The literal English graders exercise this fixed luggage/unknown fixture; they do
not certify general semantic answer quality or a retention policy.

## Quantify the repair batch

Combine current source reports, installed-host reports and all four artifact
reports with the frozen baseline via `acceptance.py`. Repeat `--artifact-report`
for the four matrix cells. The scorer records its adapter version/hash while
preserving the 54 outcomes, wording, scope and rubric digest. Missing or stale
proof stays unresolved; every unresolved mandatory gate vetoes readiness.

For the shared Windows/WSL workspace, compute the combined matrix score natively
in Linux so Linux link metadata can be inspected. The cross-platform mapper accepts
only the observed shared project prefix; arbitrary foreign paths are refused.
Report the native Python/OS evidence and retain the exact scoring command.

Keep the full prior snapshot as a historical baseline. Supply only the designated
current reports, retain failed predecessors separately, and report any lost proof.
Do not count regression tests or repeated conversations as additional outcomes.

Genuine host proof disables optional apps, plugins and remote plugin loading in
the child invocation. It retains the current model and sign-in. `--ignore-user-config`
alone does not isolate those catalogs. Retain polluted/failed predecessors when
repairing this verification environment; a later clean trial does not erase them.
