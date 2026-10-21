# Set up once and keep working

The person completes setup once, then memory is available from ordinary conversations. Their notes remain usable when they move or restore them.

## Sub-features

- SETUP.1. A clean supported install initializes a usable vault with honest exit status.
- SETUP.2. Host discovery and the first meaningful chat use the intended memory.
- SETUP.3. Reconfiguration and upgrades preserve existing configuration and custom content.
- PORT.1. Same-device moves and clean-device restores have explicit, tested semantics.
- PORT.2. Missing approval keys or divergent device state fail visibly without corrupting identity.

## How to get to it (user POV)

Install a wheel or binary, run `twinaatma init`, then `twinaatma setup-host`. Start a normal conversation in each advertised host. Move or restore the vault through its supported procedure.

## Driving it with CLI and host traces

Preconditions: use a fresh task-owned directory, the exact artifact under review, and a separate host profile.

- Source initialization. Run the core driver from SKILL.md. Require successful post-init rebuild and validation, a real Self file, and usable memory calls.
- Installed distribution and host. Follow [the retained installed-package recipe](../references/installed-packages.md): build exact candidates, install in neutral environments, check the Windows/Linux wheel/executable matrix, then drive actual Windows Codex conversations through each installed launcher. Retain full assets, packaging inputs, dependencies and independent current-source bindings.
- Distribution. Build an artifact to a task-owned output. Run `python -B tests/package_smoke.py --wheel <actual-wheel> --source .` or `--binary <actual-executable>`. Retain its hash and isolated-import evidence. Follow [the real-runtime hook recipe](../references/runtime-hooks.md) to run both generated commands under every current supported minor, without PATH activation and with poisoned imports. The source driver's Python 3.11 requirement does not change the package's Python 3.9 promise.
- Codex CLI. Run the host driver from SKILL.md. Generated setup must mark its memory server required so the first turn waits for initialization; preserve foreign servers' startup policy. A delayed-start diagnostic earns no normal installed-host credit. It creates native project TOML, discovers tools through the genuine host, and retains actual wire/tool/final-answer evidence across three conversations. Existing config merging preserves foreign text or refuses unsupported layouts. Older interpreters without tomllib refuse existing TOML merges.
- Other hosts. Run `twinaatma setup-host --host cursor --vault <fixture> --write` inside the isolated profile. Start a meaningful chat. Capture tool discovery and the actual first memory call. Repeat equivalent advertised host entry points. A printed config is insufficient.
- Preservation. The core journey executes valid, malformed and wrong-shaped configurations for Cursor, VS Code and Codex, preserving foreign settings and recording exact refusal bytes. Seed the fixture host config with another server, custom fields, malformed JSON, and a wrong-shaped server collection in separate cases. Record bytes before setup. Require safe merge for valid configs and preservation plus an actionable failure for unreadable configs.
- Honest failure. Obstruct initialization storage in a task-owned fixture. Require a nonzero exit and accurate partial-state report when required setup steps fail.
- Same-device move. Follow [native installed relocation](../references/installed-native-move.md) with both current Windows artifacts. Keep generated configuration bytes unchanged. Require original notes, IDs, relative links and recall before the move, while the old path is absent, and after a distinct unrelated vault reuses that path. The unrelated vault must remain untouched. Duplicate visible roots with the bound ID must refuse.
- Upgrade and divergence. Build the old wheel from `e831fdc` (that revision has no packaging, so add a minimal `pyproject.toml` and `setup.py` to its `git archive` extraction and run `pip wheel --no-deps --no-build-isolation`). Install the current wheel and executable with `artifact.py`, then run `python -X utf8 -B scripts/upgrade_divergence.py --artifact-report <wheel-report> --artifact-report <binary-report> --old-wheel <old.whl> --output work/gc-artifacts/.knowledgeos/upgrade/report` on native Windows. It upgrades one environment in place, drives two vault copies with separate state directories through a simulated sync with a conflict copy, and observes each approval in a hidden console only up to its refusal or prompt. It never answers a prompt. Score it with `acceptance.py --extension-report upgrade-divergence=<report.json>`; `upgrade_divergence_adapter.py` recomputes all 23 cases. The owner's device-local policy (21 October 2026) is the expectation, so a missing doctor flag or hint stays a FAIL.
- Restore. Restore a separate copy on a clean device. Verify notes, links, identity, retrieval, host wiring, and pending-proposal behavior. Retain both originals. When approval state cannot transfer, report the limitation and require a fresh proposal instead of silently accepting the old one.

## Gotchas

Doctor checks local files and index health. Current generated MCP configurations bind the full vault ID, omit a fixed working directory and retain an absolute fallback. A matching vault in the host working-directory ancestry takes precedence; an unrelated fallback or conflicting visible copies refuse. Markerless legacy launchers keep their previous absolute semantics. Cursor hooks still contain absolute paths and need separate relocation evidence. Pending approvals depend on off-vault signing state. A Windows MCP move does not establish other-host hooks, clean-device restore or approval-state transfer.
