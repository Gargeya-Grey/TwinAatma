"""In-package diagnostic doctor (stdlib only).

Lives in the package so the binary works on a data-only vault with no ``scripts/``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REQUIRED_DIRS = [
    "Inbox",
    "Concepts",
    "Projects",
    "Experiments",
    "Research",
    "Decisions",
    "People",
    "MOCs",
    "Templates",
    "Assets",
    "Archive",
]


def _check_hook_interpreter(vault: Path, hooks_dir: Path) -> bool:
    """A hook launched as bare ``python`` resolves through PATH, and CWD is on PATH
    for some hosts — a `python.bat` dropped in the vault would then run instead.

    `init` now pins an absolute interpreter. This reports installs that predate that
    fix instead of leaving them quietly exposed.
    """
    import json
    import shlex

    config = hooks_dir.parent / "hooks.json" if hooks_dir.name == "hooks" else hooks_dir / "hooks.json"
    if not config.exists():
        return True
    try:
        data = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"  [ERROR] hooks.json cannot be read as JSON: {exc}. Repair the config and retry.")
        return False
    if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict):
        print("  [ERROR] hooks.json must contain a 'hooks' object. Repair the config and retry.")
        return False
    commands = []
    valid = True
    for event, group in data["hooks"].items():
        if not isinstance(group, list):
            print(f"  [ERROR] Hook event '{event}' must contain a list of commands.")
            valid = False
            continue
        for entry in group:
            if not isinstance(entry, dict) or not isinstance(entry.get("command"), str) or not entry["command"].strip():
                print(f"  [ERROR] Hook event '{event}' has no usable command string.")
                valid = False
                continue
            commands.append(entry["command"])
    # In the toolkit checkout the vault *is* the install: `.cursor/hooks/` there is the
    # source of the shipped hook, and `.cursor/hooks.json` is the template `init`
    # rewrites. Flagging the developer's own tree would train everyone to ignore these
    # warnings, which is how a real one gets missed.
    from knowledgeos.indexer import _is_toolkit_repo

    if _is_toolkit_repo(vault):
        return valid
    from knowledgeos.safe_exec import resolve_executable

    for command in commands:
        try:
            tokens = shlex.split(command, posix=os.name != "nt")
        except ValueError as exc:
            print(f"  [ERROR] Hook command cannot be parsed: {exc}.")
            valid = False
            continue
        executable = tokens[0].strip('"') if tokens else ""
        path = Path(executable)
        available = path.is_file() if path.is_absolute() else bool(resolve_executable(executable))
        if not available:
            print(f"  [ERROR] Hook executable is missing or unusable: {executable}. Reinstall or update hooks.json.")
            valid = False
    relative = [
        command
        for command in commands
        if command.strip().lower().startswith("python ") or command.strip() == "python"
    ]
    if relative:
        print("  [WARNING] A hook is launched with bare 'python', which resolves through PATH.")
        print("            Re-run `twinaatma init` to pin an absolute interpreter.")
    # Without -P, CPython puts the script's own directory first on sys.path, and that
    # directory is inside the vault. A file there called json.py is imported by the hook
    # itself. This is the vector that made "the vault cannot get code executed" false.
    # A hook that runs `twinaatma hook <name>` has no script directory at all, so the
    # rule only applies to commands that name a `.py` file.
    scripted = [command for command in commands if ".py" in command or "knowledgeos hook" in command]
    if scripted and not all("-P" in command.split() for command in scripted):
        print("  [WARNING] A hook is launched without -P, so its own folder is on sys.path.")
        print("            A file there named json.py would run on every chat.")
        print("            Re-run `twinaatma init` to fix the command.")
    # A hook that runs code *out of the vault* is a vault-write-to-code path: an agent
    # that can write notes can rewrite the file whose next execution is a chat. `init`
    # stopped shipping the code there, so a `.py` in the hooks folder is either a
    # leftover from an older install or something planted.
    code_in_vault = sorted(p.name for p in hooks_dir.glob("*.py")) if hooks_dir.is_dir() else []
    # (an absent hooks directory is the healthy state now, not a reason to skip checks)
    if code_in_vault:
        print(f"  [WARNING] Executable hook code sits in the vault: {', '.join(code_in_vault)}")
        print("            A note write could replace it, and it would run on the next chat.")
        print("            The hooks now run from the installed toolkit; delete these files.")
    # A binary install launches `twinaatma hook <name>`. Without `--vault` the hook script
    # falls back to `Path(__file__).parents[2]`, which inside the bundle is the extracted
    # bundle directory, so it pre-warms a vault that is not the user's and reports success.
    binary_hooks = [
        command for command in commands if " hook " in f" {command.strip()} "
    ]
    if any(" hook " in f" {c.strip()} " and "--vault" not in c.split() for c in binary_hooks):
        print("  [WARNING] A hook runs the installed binary without --vault, so it acts on")
        print("            the application folder instead of your vault.")
        print("            Re-run `twinaatma init` to write the vault path into the command.")
    unexpected = sorted(
        p.name + ("/" if p.is_dir() else "")
        for p in (hooks_dir.iterdir() if hooks_dir.is_dir() else [])
        if p.name not in {"twin_session_start.py", "twin_session_end.py"}
    )
    if unexpected:
        print(f"  [WARNING] Unexpected files in the hooks directory: {', '.join(unexpected)}")
        print("            A hook can import anything in this folder. Remove what you")
        print("            did not install.")
    return valid


def run_doctor(vault: Path) -> int:
    from knowledgeos.indexer import index_schema_problem, index_state
    from knowledgeos.vault_resolve import is_vault_root

    db = vault / "knowledge_index.db"
    print("=== TwinAatma Diagnostic Doctor ===")
    print(f"Vault Root: {vault}\n")
    passed = True

    print("[*] Checking Python version...")
    version = sys.version_info
    if version < (3, 9):
        print(f"  [ERROR] Python {version.major}.{version.minor} detected. TwinAatma requires 3.9+.")
        passed = False
    else:
        print(f"  [OK] Python {version.major}.{version.minor}.{version.micro}.")

    if getattr(sys, "frozen", False):
        print("  [OK] Running from the packaged binary.")

    print("\n[*] Checking vault marker...")
    if is_vault_root(vault):
        print("  [OK] Directory is a vault root.")
    else:
        print("  [ERROR] No .knowledgeos-vault.json or People/Self.md here.")
        passed = False

    print("\n[*] Checking folder structure...")
    missing = [d for d in REQUIRED_DIRS if not (vault / d).exists()]
    if missing:
        print(f"  [WARNING] Missing directories: {', '.join(missing)} (created on demand).")
    else:
        print("  [OK] All core vault directories are present.")

    # A missing required section used to be a `[WARNING]` and the run still ended
    # `PASSED` with exit 0, even though `memory_propose_self_update` for that section
    # fails and the twin can never record that kind of preference. `doctor` is the one
    # command whose whole job is to say whether the install works, so a fault that
    # blocks a documented operation is an error, not a note.
    print("\n[*] Checking identity sections...")
    self_file = vault / "People" / "Self.md"
    if not self_file.is_file():
        print("  [ERROR] People/Self.md is missing; preference changes cannot be applied.")
        passed = False
    else:
        try:
            from knowledgeos.gate import SECTION_ALIASES, section_body

            identity = self_file.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeError) as exc:
            print(f"  [ERROR] People/Self.md could not be read: {exc}")
            passed = False
        else:
            # Every key the gate accepts is one a preference can target, so every one
            # has to exist. There is no read-only section: `propose` validates against
            # exactly this mapping.
            try:
                absent = [key for key in sorted(SECTION_ALIASES) if section_body(identity, key) is None]
            except ValueError as exc:
                print(f"  [ERROR] Invalid identity sections: {exc}")
                passed = False
                absent = None
            if absent:
                passed = False
                print(
                    "  [ERROR] Self.md is missing section(s) the gate writes: "
                    f"{', '.join(absent)}."
                )
                print(
                    "  [ERROR] Proposals for those sections will be rejected. Restore them "
                    "from the template, or re-run init."
                )
            elif absent is not None:
                print("  [OK] All writable identity sections are present.")

    print("\n[*] Checking Git (optional)...")
    if not (vault / ".git").exists():
        print("  [INFO] Not a git repo; drift falls back to note timestamps.")
    else:
        from knowledgeos.safe_exec import run_trusted

        # Not `subprocess.run(["git", ...])`: doctor runs with the vault as its working
        # directory, and on Windows that resolves `git` to `./git.exe` first. A planted
        # binary would run here just by the human typing `doctor`.
        proc = run_trusted("git", ["--version"], cwd=vault, timeout=20)
        if proc is not None and proc.returncode == 0:
            print("  [OK] Git present and repository initialized.")
        else:
            print("  [WARNING] Git not usable from PATH.")

    print("\n[*] Checking search index...")
    try:
        state = index_state(db)
    except (OSError, ValueError) as exc:
        print(f"  [ERROR] Unsafe or inaccessible index path: {exc}")
        print("          Original paths are preserved; automatic recovery is blocked.")
        print(f"          Path: {db}")
        passed = False
        state = "unsafe"
    if state == "unsafe":
        pass
    elif state == "ok":
        # Shaped right is not the same as *holding the vault*. An index that is empty —
        # or missing most of its notes — answers every search with `[]`, which reads as
        # "nothing matches" and is the most confidently wrong answer the product can
        # give. `doctor` called a 0-row index in a 42-note vault `[OK] Index healthy` and
        # exited 0. Reported as a warning because the next read repairs it, but said out
        # loud, because until that read happens search is wrong.
        from knowledgeos.indexer import index_coverage_problem
        from knowledgeos.remembering import PolicyError

        try:
            coverage = index_coverage_problem(vault)
        except PolicyError:
            print("  [ERROR] Remembering policy is unavailable; index coverage could not be checked.")
            passed = False
        else:
            if coverage:
                print(f"  [WARNING] Index is incomplete: {coverage}.")
                print("          The next memory call will rebuild it.")
            else:
                print(f"  [OK] Index healthy ({db.stat().st_size} bytes).")
    elif state == "missing":
        print("  [INFO] Index missing; rebuilt automatically on the next memory call.")
    elif state == "locked":
        print("  [INFO] Index is in use by another process; that is not an error.")
    elif db.exists() and (problem := index_schema_problem(db)) is not None:
        # Openable but the wrong shape: no `links`, a `notes_fts` that is an ordinary
        # table, columns a query names that are not there. `doctor` used to print
        # "Index healthy" for these, and the failure then surfaced as an empty search
        # (which reads as a real answer) or `no such column: type` out of a tool call.
        print(f"  [ERROR] Index database cannot answer a search: {problem}.")
        print("          The next memory call will move it aside and rebuild from the notes.")
        print(f"          Path: {db}")
        passed = False
    else:
        print("  [WARNING] Index is unreadable and will be quarantined on the next rebuild.")
    # A lock path that is not a file is not contention — nobody holds it, and no rebuild
    # can ever take it. `breathe` used to swallow the resulting error, so the vault went
    # quietly stale forever. This is the one place a human finds out.
    from knowledgeos.indexer import LOCK_REL

    lock_path = vault / LOCK_REL
    # Static check only: *taking* the lock here would block for the full wait when another
    # process is legitimately rebuilding, and `doctor` is not allowed to be slow on a
    # healthy vault. Whether a lock can be taken is decided by the writer.
    if lock_path.exists() and not lock_path.is_file():
        print(f"  [ERROR] {LOCK_REL} exists but is not a file, so the index cannot rebuild.")
        print(f"          Remove it: {lock_path}")
        passed = False

    print("\n[*] Checking vault state folder...")
    state_folder = vault / ".knowledgeos"
    if state_folder.exists() and not state_folder.is_dir():
        # One ordinary write turns the state folder into a file, and every session tool
        # then answered `{"error": ...}` while this report said PASSED. The twin keeps its
        # session bookkeeping and index manifest there, so this is a broken install, not a
        # cosmetic problem.
        print("  [ERROR] .knowledgeos exists but is not a folder, so state cannot be kept.")
        print(f"          Remove it: {state_folder}")
        passed = False
    else:
        print("  [OK] State folder usable.")

    print("\n[*] Checking Self.md sections...")
    self_path = vault / "People" / "Self.md"
    if not self_path.exists():
        print("  [ERROR] People/Self.md missing.")
        passed = False
    else:
        from knowledgeos.self_model import SECTION_ALIASES, load_self

        try:
            model = load_self(self_path)
            found = sorted(model.sections)
        except (OSError, ValueError) as exc:
            print(f"  [ERROR] Self.md sections could not be parsed: {exc}")
            passed = False
            found = []
        expected = sorted(SECTION_ALIASES)
        if found == expected:
            print(f"  [OK] All {len(expected)} sections parsed.")
        else:
            print(f"  [WARNING] Sections found: {', '.join(found) or '(none)'}")
            print(f"            Expected: {', '.join(expected)}")

    print("\n[*] Checking identity gate...")
    try:
        from knowledgeos.gate import ledger_health, list_open

        health = ledger_health(vault)
        pending = list_open(vault)
        if health["signed"]:
            print(f"  [OK] Proposal ledger is signed ({health['rows']} entries, outside the vault).")
            print(f"       Key: {health['key_source']}")
            print("       This detects tampering with vault-side content. It is not a")
            print("       defence against a program that can read your whole disk.")
        else:
            print("  [WARNING] No signing key available; the ledger cannot be verified.")
        try:
            from knowledgeos.gate import untrusted_proposals

            orphans = untrusted_proposals(vault, vault / "People" / "Self-Proposals")
        except Exception:
            orphans = []
        if orphans:
            print(
                f"  [WARNING] {len(orphans)} Self proposal file(s) are not in the ledger, so "
                "they cannot be approved:"
            )
            for path in orphans:
                print(f"            {path}")
        if health["rejected_rows"]:
            print(
                f"  [WARNING] {health['rejected_rows']} ledger row(s) failed signature "
                "verification and were ignored."
            )
        from knowledgeos.gate import vault_marker_mismatch

        mismatch = vault_marker_mismatch(vault)
        if mismatch:
            # The marker is a vault file; the binding is not. If they disagree, someone
            # edited the marker. The ledger stays where it was bound, so pending proposals
            # are still listed — this line is how the human finds out why the count they
            # expected is not the count they see.
            print(f"  [WARNING] {mismatch}")
        if pending:
            print(f"  [INFO] {len(pending)} Self proposal(s) waiting for you:")
            for item in pending:
                print(f"         {item['path']}")
            print("         Approve with: twinaatma self approve <file>")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"  [WARNING] Could not read the gate ledger: {exc}")

    print("\n[*] Checking toolkit assets...")
    try:
        from knowledgeos.resources import missing_assets, toolkit_root

        gaps = missing_assets()
        if gaps:
            print(f"  [ERROR] This install is missing: {', '.join(gaps)}")
            print(f"          Expected under {toolkit_root()} — reinstall the package or binary.")
            passed = False
        else:
            print(f"  [OK] Starter kit present in {toolkit_root()}.")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"  [WARNING] Could not check toolkit assets: {exc}")

    print("\n[*] Checking Cursor hooks...")
    # The hook *config* is what matters now: `init` no longer puts executable code in the
    # vault, so a missing `.cursor/hooks/` is the healthy state, not "no hooks installed".
    # Checking the directory first meant that as soon as the code moved out, every
    # command was left unchecked — the guard would have silently stopped running.
    hooks_dir = vault / ".cursor" / "hooks"
    config = vault / ".cursor" / "hooks.json"
    if not config.exists():
        print("  [INFO] No Cursor hooks configured (only needed for the Cursor host).")
    else:
        if not _check_hook_interpreter(vault, hooks_dir):
            passed = False
    if hooks_dir.exists():
        clashes = sorted(
            p.name for p in hooks_dir.iterdir() if ".new" in p.name or p.name.endswith(".bak")
        )
        if clashes:
            print(f"  [WARNING] Unresolved hook conflicts: {', '.join(clashes)}")
            print("            Your originals were kept; review and merge them by hand.")
        else:
            print("  [OK] No unresolved hook conflicts.")
        for hook in sorted(hooks_dir.glob("*.py")):
            try:
                compile(hook.read_text(encoding="utf-8", errors="replace"), str(hook), "exec")
            except SyntaxError as exc:
                print(f"  [ERROR] Hook {hook.name} does not compile: {exc}")
                passed = False

    print("\n[*] Checking Notion configuration (optional)...")
    has_key = bool(os.environ.get("NOTION_API_KEY"))
    has_db = bool(os.environ.get("NOTION_DATABASE_ID") or os.environ.get("NOTION_DATA_SOURCE_ID"))
    if has_key and has_db:
        print("  [OK] Notion credentials detected in environment.")
    elif has_key or has_db:
        print("  [WARNING] Partial Notion configuration (need both key and database id).")
    else:
        print("  [INFO] Notion not configured; core TwinAatma does not need it.")

    print("\n--- Diagnostic Summary ---")
    if passed:
        print("[OK] Environment check PASSED.")
        return 0
    print("[FAIL] Environment check FAILED; resolve the errors above.")
    return 1


def main(argv: list[str] | None = None) -> int:
    from knowledgeos.vault_resolve import resolve_vault

    args = list(sys.argv[1:] if argv is None else argv)
    explicit = None
    if "--vault" in args:
        index = args.index("--vault")
        if index + 1 < len(args):
            explicit = args[index + 1]
    return run_doctor(resolve_vault(explicit))


if __name__ == "__main__":
    raise SystemExit(main())
