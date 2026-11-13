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

## What checks it

Preconditions: a fresh task-owned directory and a synthetic vault. Run one suite with `python -B -m unittest discover -s tests -p <file>`.

- Source initialization. `first_day.py` and class `InitSmokeTests` in `tests/test_core.py`: a successful post-init rebuild and validation, a real Self file, and usable memory calls.
- Honest failure. `tests/test_setup_repairs.py`: a required setup step that fails gives a nonzero exit; setup with a name alone invents no preference.
- Package. `python -B tests/package_smoke.py --wheel <actual-wheel> --source .` or `--binary <actual-executable>` installs in a neutral place and drives it. CI runs it for a wheel on Python 3.9 to 3.14 and for both binaries. `tests/test_installed_launchers.py` and `tests/test_hook_shell_paths.py` cover the generated commands.
- Codex configuration. `tests/test_host_acceptance.py` and `tests/test_codex_required_setup.py`: native project TOML, the memory server marked required, a merge that keeps foreign text, comments and custom values, and a refusal that keeps every byte of a malformed or unsupported file. An interpreter without `tomllib` refuses a merge into an existing file.
- Other project configurations. `tests/test_host_acceptance.py` (class `ExistingProjectConfig`), `tests/test_setup_repairs.py` and class `SetupHostTests` in `tests/test_core.py`: valid, malformed and wrong-shaped files for Cursor and VS Code keep foreign settings or are refused unchanged.
- User-level setup and the Claude Code hook. See [the first day](first-day.md).
- Same-device move. `tests/test_host_vault_move.py`: the generated configuration binds the full vault ID, works after a move, ignores a different vault at the old path, and refuses conflicting markers.
- Reconnect after a restore. `tests/test_restore_host_configuration.py`: `setup-host --write` restores generated files by their recorded hashes and keeps edited and foreign hooks.
- Signing state, versions and conflict copies. `tests/test_journey_gaps.py` and `tests/test_binding_guard.py`: doctor names a ledger signed by another key, prints the version verdict and warns about sync conflict copies; a pending draft from another install is refused with a recovery hint.

Not checked by any script: a host chat from an installed wheel or binary; Cursor, VS Code, Claude Desktop and Windsurf in a real session; the speed budget at 100, 1,000 and 10,000 notes; an upgrade in place from an older release; loss of signing state with an installed package; a restore on a second clean machine. The driver for each was removed on 13 November 2026; the last commit that holds it is `69bec1e`.

## Gotchas

Doctor checks local files and index health. Current generated MCP configurations bind the full vault ID, omit a fixed working directory and retain an absolute fallback. A matching vault in the host working-directory ancestry takes precedence; an unrelated fallback or conflicting visible copies refuse. Markerless legacy launchers keep their previous absolute semantics. Cursor hooks use absolute paths. `setup-host --write` reconnects files whose hashes match the ownership record made by `init`; legacy or edited hooks that need replacement are preserved and refused with a diagnostic. Pending approvals depend on off-vault signing state. A Windows MCP move does not establish other-host hooks, clean-device restore or approval-state transfer.

## Journey fixes (21 October 2026)

- Doctor says in plain words when ledger rows were signed by a different key (key lost or replaced, or a ledger from another device or install), that those proposals cannot be approved here, and how to recover; it no longer prints the healthy "signed" line when no row verifies.
- Doctor prints the installed version, the vault's declared schema and a compatibility verdict; `vault_version_check` orders a dev build before its release and returns None for a compatible vault.
- `twinaatma validate` exempts a vault-root `README.md` guide only when it has no frontmatter. A root README with a metadata block and every README inside a note folder are validated as notes.
- Doctor warns, on every device, about sync conflict copies (Syncthing, Dropbox, Nextcloud names) and notes that share an `id:`; it never renames, merges or rewrites either copy.
