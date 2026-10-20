"""CLI entry: python -m knowledgeos <command>"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _default_vault() -> Path:
    from knowledgeos.vault_resolve import resolve_vault

    return resolve_vault()


def resolve_vault_cli(explicit: Path | None) -> Path:
    from knowledgeos.vault_resolve import resolve_vault

    return resolve_vault(explicit)


def require_vault(explicit: Path | None) -> Path:
    from knowledgeos.vault_resolve import require_vault as _require

    return _require(explicit)


def _run_hook(name: str, argv: list[str]) -> int:
    """Run a shipped hook script in-process, for the frozen binary.

    The hook scripts live inside the bundle (``toolkit_root()/.cursor/hooks``), never in
    the vault, so there is no vault directory on ``sys.path`` to shadow an import. The
    script is executed with ``runpy`` rather than spawned, so the guards in it apply and
    no second interpreter has to exist on the machine.

    The vault has to be passed in. A hook script computes its vault as
    ``Path(__file__).resolve().parents[2]``, which is correct for the scripted install,
    where the file really does sit in ``<vault>/.cursor/hooks``. Under ``runpy`` from the
    bundle, ``__file__`` is ``<_MEIPASS>/.cursor/hooks/<name>.py``, so the hook quietly
    operated on a folder inside the extracted bundle: it printed its context block, said
    nothing about failing, and the session that followed had no memory in it.
    """
    import os
    import runpy

    if name not in {"twin_session_start", "twin_session_end"}:
        print(f"hook: unknown hook {name!r}", file=sys.stderr)
        return 2
    from knowledgeos.resources import toolkit_root

    vault: str | None = None
    rest = list(argv)
    if "--vault" in rest:
        index = rest.index("--vault")
        if index + 1 < len(rest):
            vault = rest[index + 1]
            del rest[index : index + 2]
        else:
            print("hook: --vault needs a path", file=sys.stderr)
            return 2
    if name == "twin_session_end":
        from knowledgeos.autopilot import mark_orphan_if_open
        raw = sys.stdin.read()
        try:
            event = json.loads(raw) if raw.strip() else {}
        except ValueError:
            event = {}
        target = Path(vault).resolve() if vault else _default_vault()
        session_id = event.get("memory_session_id") if isinstance(event, dict) else None
        mark_orphan_if_open(target, session_id=session_id)
        print("{}")
        return 0
    script = toolkit_root() / ".cursor" / "hooks" / f"{name}.py"
    if not script.is_file():
        print(f"hook: {script} is missing from this install", file=sys.stderr)
        return 2
    saved_argv = sys.argv
    saved_env = os.environ.get("KNOWLEDGEOS_VAULT")
    sys.argv = [str(script), *rest]
    if vault is not None:
        os.environ["KNOWLEDGEOS_VAULT"] = vault
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        sys.argv = saved_argv
        if vault is not None:
            if saved_env is None:
                os.environ.pop("KNOWLEDGEOS_VAULT", None)
            else:
                os.environ["KNOWLEDGEOS_VAULT"] = saved_env
    return 0


def _be_utf8_tolerant() -> None:
    """Never crash because a note contains a character the console cannot encode.

    Windows consoles default to a legacy code page, and the approval screen prints the
    current section of ``People/Self.md`` — which is the user's own text, so it contains
    whatever they wrote. A rule with an arrow in it (`Capture → Decide`) reached
    ``UnicodeEncodeError: 'charmap' codec can't encode character '\u2192'`` and the
    binary died with a PyInstaller traceback instead of showing the diff. Approval is the
    one command where failing to render is a security problem, not a cosmetic one: the
    human is being asked to read before saying yes.

    ``backslashreplace`` rather than ``?``: the character is still distinguishable, and
    a note with an emoji does not silently become a row of question marks.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="backslashreplace")
        except (OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _be_utf8_tolerant()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help", "help"}:
        from knowledgeos import __version__

        print(
            f"TwinAatma CLI (knowledgeos {__version__})\n\n"
            "Commands:\n"
            "  init <path>           Create a starter vault (--dry-run, --force)\n"
            "  mcp                   Start MCP Memory server (stdio)\n"
            "  setup-host            Write/print an MCP host config (--write, --print)\n"
            "  doctor                Environment and vault diagnostics\n"
            "  validate              Validate vault schema\n"
            "  ids assign [--write]  Assign kos:<type>:<slug> IDs (dry-run default)\n"
            "  self summary          Parse People/Self.md ego node\n"
            "  self pending          List Self proposals waiting for you\n"
            "  self approve <file>   Read a proposal and apply it (needs a terminal)\n"
            "  memory <tool>         Call Memory API tools (CLI fallback for MCP)\n"
            "  breathe               Autopilot tick (freshen + load + soft prompts)\n"
            "  hook <name>           Run a shipped host hook (used by the binary)\n"
            "  version               Print package version (also --version)\n"
        )
        return 0

    cmd = argv[0]
    # Toolkit root for commands that need the starter kit (init, setup-host). It is
    # resolved on demand so a pip install does not depend on a `scripts/` folder.
    from knowledgeos.resources import toolkit_root

    root = toolkit_root()

    if cmd in {"version", "--version", "-V"}:
        from knowledgeos import __version__

        print(__version__)
        return 0

    if cmd == "hook":
        # The packaged binary is not Python, so `hooks.json` cannot launch it as an
        # interpreter. This subcommand runs the same shipped hook script with the same
        # guards, from inside the bundle rather than from the vault.
        rest = argv[1:]
        if not rest:
            print("hook: name required (twin_session_start, twin_session_end)", file=sys.stderr)
            return 2
        return _run_hook(rest[0], rest[1:])

    if cmd == "doctor":
        rest = argv[1:]
        vault = _default_vault()
        if "--vault" in rest:
            idx = rest.index("--vault")
            if idx + 1 < len(rest):
                vault = Path(rest[idx + 1]).expanduser().resolve()
        from knowledgeos.doctor import run_doctor

        return run_doctor(vault)

    if cmd == "validate":
        from knowledgeos.vault_resolve import require_vault
        from knowledgeos.validator import validate_vault

        rest = argv[1:]
        vault = _default_vault()
        if "--vault" in rest:
            idx = rest.index("--vault")
            if idx + 1 < len(rest):
                vault = Path(rest[idx + 1]).expanduser().resolve()
        try:
            vault = require_vault(vault)
        except SystemExit:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            print(f"validate failed: {exc}", file=sys.stderr)
            return 2
        report = validate_vault(vault)
        print(json.dumps(report, indent=2))
        return 1 if report["summary"]["errors"] else 0

    if cmd == "ids":
        return _cmd_ids(argv[1:], root)

    if cmd == "self":
        return _cmd_self(argv[1:], root)

    if cmd == "init":
        return _cmd_init(argv[1:], root)

    if cmd == "memory":
        return _cmd_memory(argv[1:], root)

    if cmd == "breathe":
        return _cmd_breathe(argv[1:], root)

    if cmd == "mcp":
        return _cmd_mcp(argv[1:], root)

    if cmd == "setup-host":
        return _cmd_setup_host(argv[1:], root)

    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 1


def _cmd_setup_host(argv: list[str], root: Path) -> int:
    from knowledgeos.host_setup import main as setup_main

    return setup_main(argv)


def _cmd_ids(argv: list[str], root: Path) -> int:
    if not argv or argv[0] != "assign":
        print("Usage: python -m knowledgeos ids assign [--write] [--vault PATH]", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(prog="knowledgeos ids assign")
    parser.add_argument("--write", action="store_true", help="Write IDs into note frontmatter")
    parser.add_argument("--vault", type=Path, default=None, help="Vault root (default: resolved)")
    parser.add_argument("--include-existing", action="store_true", help="Also rewrite notes that already have ids")
    args = parser.parse_args(argv[1:])

    from knowledgeos.ids import assign_ids_for_vault
    from knowledgeos.vault_resolve import resolve_vault

    changes = assign_ids_for_vault(
        resolve_vault(args.vault),
        write=args.write,
        only_missing=not args.include_existing,
    )
    print(json.dumps({"write": args.write, "count": len(changes), "changes": changes}, indent=2))
    if not args.write and changes:
        print("\nDry-run only. Re-run with --write to apply.", file=sys.stderr)
    return 0


def _cmd_self(argv: list[str], root: Path) -> int:
    if not argv:
        print(
            "Usage:\n"
            "  twinaatma self summary [--path People/Self.md]\n"
            "  twinaatma self pending\n"
            "  twinaatma self approve <proposal.md>\n"
            "\n"
            "'approve' is the only way Self.md can change, and it refuses to run\n"
            "without an interactive terminal so an agent cannot complete the loop.",
            file=sys.stderr,
        )
        return 1

    command = argv[0]
    if command == "summary":
        return _self_summary(argv[1:])
    if command == "pending":
        return _self_pending(argv[1:])
    if command == "approve":
        return _self_approve(argv[1:])
    print(f"Unknown self subcommand: {command}", file=sys.stderr)
    return 1


def _self_summary(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="knowledgeos self summary")
    parser.add_argument("--path", type=Path, default=None)
    parser.add_argument("--vault", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.path:
        path = args.path if args.path.is_absolute() else (resolve_vault_cli(args.vault) / args.path)
    else:
        path = resolve_vault_cli(args.vault) / "People" / "Self.md"
    if not path.exists():
        print(f"Self note not found: {path}", file=sys.stderr)
        return 1
    from knowledgeos.self_model import SelfModel, _split_sections
    from knowledgeos.parser import split_frontmatter
    from knowledgeos.remembering import RememberingPolicy, PolicyError, EXCLUDED

    try:
        policy = RememberingPolicy(resolve_vault_cli(args.vault))
        text = policy.read(path)
        if text is None:
            raise PolicyError(EXCLUDED)
        frontmatter, body = split_frontmatter(text)
        model = SelfModel(path, frontmatter, body, _split_sections(body))
        summary = policy.release(model.summary())
    except PolicyError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


def _self_pending(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="knowledgeos self pending")
    parser.add_argument("--vault", type=Path, default=None)
    args = parser.parse_args(argv)
    from knowledgeos.gate import ledger_health, list_open
    from knowledgeos.remembering import RememberingPolicy, PolicyError

    vault = resolve_vault_cli(args.vault)
    try:
        policy = RememberingPolicy(vault)
        all_props = list_open(vault)
        open_props = [item for item in all_props
                      if policy.read(vault / item["path"]) is not None]
        policy.release(open_props)
    except PolicyError as error:
        print(str(error), file=sys.stderr)
        return 1
    health = ledger_health(vault)
    if len(open_props) != len(all_props):
        print("Some proposals are withheld by the remembering policy.")
    elif not open_props:
        print("No Self proposals waiting for you.")
    for item in open_props:
        print(f"{item['path']}  [{item['section']} / {item['mode']}]")
    if health["rejected_rows"]:
        print(
            f"\nWarning: {health['rejected_rows']} ledger row(s) failed signature check "
            "and were ignored. Run `twinaatma doctor`.",
            file=sys.stderr,
        )
    if not health["signed"]:
        print(
            "Warning: no gate signing key could be created; the ledger is unsigned.",
            file=sys.stderr,
        )
    return 0


def _self_approve(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="knowledgeos self approve")
    parser.add_argument("proposal", help="Path or filename of a proposal in People/Self-Proposals")
    parser.add_argument("--vault", type=Path, default=None)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Unused. Kept only so scripts fail loudly instead of silently approving.",
    )
    args = parser.parse_args(argv)

    if args.yes:
        print(
            "Refusing --yes: this command exists so a human reads the change and confirms.\n"
            "Re-run without --yes.",
            file=sys.stderr,
        )
        return 2
    if not sys.stdin.isatty():
        print(
            "Refusing to approve without an interactive terminal.\n"
            "Run this command yourself in a terminal window.",
            file=sys.stderr,
        )
        return 2

    from knowledgeos import gate
    from knowledgeos.memory import MemoryAPI

    vault = resolve_vault_cli(args.vault)
    api = MemoryAPI(vault)
    raw = Path(args.proposal)
    candidate = raw if raw.is_absolute() else (vault / raw)
    if not candidate.exists() and not raw.is_absolute():
        candidate = api.proposals_dir / raw.name
        if not candidate.exists():
            matches = sorted(api.proposals_dir.glob(f"*{raw.name}*"))
            candidate = matches[0] if len(matches) == 1 else candidate
    if not candidate.exists():
        print(f"Proposal not found: {args.proposal}", file=sys.stderr)
        return 1

    # Everything below comes from the ledger row that `_apply` will act on. The screen
    # used to parse the section and mode out of the proposal file with a scan over the
    # first 30-40 lines, which meant a line the *agent* wrote inside `## Summary` could
    # name a different section or mode than the one applied: the human read a diff of
    # one section, pressed y, and a different one was replaced.
    described = gate.describe(vault, api.proposals_dir, str(candidate))
    if described.get("error"):
        print(described["error"], file=sys.stderr)
        hint = described.get("hint")
        if hint:
            print(hint, file=sys.stderr)
        return 1
    section = described["section"]
    mode = described["mode"]
    patch = described["patch"]
    candidate = described["path"]

    diff, removals, additions, _section = _preview_diff(
        api, candidate, patch, section=section, mode=mode
    )

    print(f"Proposal: {candidate.name}")
    print(f"Section : {section}")
    print(f"Changes : {mode}")
    if described.get("allow_destructive"):
        print()
        print("  DESTRUCTIVE: the agent waived the section-retention floor for this change.")
        print("  Read the '-' lines above carefully: most of this section may be deleted.")
    print()
    print("What this replaces in People/Self.md:")
    print("=" * 60)
    shown = 0
    for line in diff:
        print(f"  {line}")
        shown += 1
    if shown == 0:
        print("  (identical to the current section)")
    print("=" * 60)
    print()
    print("What it puts there instead:")
    print("=" * 60)
    for line in patch.splitlines():
        print(f"  {line}")
    print("=" * 60)
    if removals > additions:
        print()
        print(
            f"Note: this deletes {removals} line(s) and adds {additions} "
            f"(net {additions - removals:+d})."
        )
    # `input()` raises `EOFError` when stdin is closed or not connected — which is the
    # normal state of a CLI run from an agent, a CI job or a scheduled task. That reached
    # the human as a traceback from `_self_approve`. Not being able to ask is the same
    # answer as "no".
    # A destructive waiver changes what has to be typed. The flag is a tool argument the
    # *agent* supplies, and the screen would otherwise offer the same single `y` for a
    # replace that keeps every line and one that empties the section — the difference
    # living only in a JSON field the human never sees. Asking for a second, specific word
    # means a distracted `y` cannot authorise a wipe.
    if described.get("allow_destructive"):
        prompt = (
            "This was flagged destructive by the agent. Type yes-wipe to apply, "
            "anything else cancels: "
        )
        accepted = {"yes-wipe"}
    else:
        prompt = "Apply this to People/Self.md? [y/N] "
        accepted = {"y", "yes"}
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        print()
        print("No answer possible (stdin is closed); nothing applied.")
        return 1
    if answer not in accepted:
        print("Not applied.")
        return 1

    result = gate.approve_interactive(vault, api.self_path, api.proposals_dir, str(candidate))
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def _preview_diff(
    api,
    candidate: Path,
    patch: str,
    *,
    section: str | None = None,
    mode: str | None = None,
) -> tuple[list[str], int, int, str]:
    """A real unified diff of the section, so approving is not approving blind.

    Showing only the new text lets a proposal delete most of a section while the
    screen looks like an addition. Removals are the part a human actually needs.

    `section` and `mode` are passed in from the ledger rather than parsed out of the
    file. Parsing them here is how the screen and the apply path came to disagree.
    """
    import difflib

    from knowledgeos import gate

    if section is None or mode is None:
        ledger = gate.describe(api.vault, api.proposals_dir, str(candidate))
        section = section if section is not None else str(ledger.get("section") or "")
        mode = mode if mode is not None else str(ledger.get("mode") or "replace")
    before = ""
    after = patch
    try:

        self_text = api.self_path.read_text(encoding="utf-8", errors="replace")
        before = gate.section_body(self_text, section) or ""
        # Show the *merge*, not the patch pasted under the old text. Append mode keeps
        # only lines the section does not already contain and preserves existing bytes, so
        # `before + patch` displayed a line the human was about to "add" twice, and showed
        # text — a duplicate, or a line rewritten by the merge — that would never be
        # stored. What is on the screen is now literally `section_body` of the file that
        # would be written.
        merged, found = gate.replace_section(self_text, section, patch, mode=mode)
        if found:
            after = gate.section_body(merged, section) or patch
    except Exception:
        after = patch
    # Diff what the reader will see, not the source. A patch can be dominated by text
    # that never renders (comment markers, padding), and a source-line diff then shows a
    # cosmetically small change to a section that has actually been replaced.
    try:
        from knowledgeos import gate as _gate

        before_rendered = _gate.rendered_text(before)
        after_rendered = _gate.rendered_text(after)
    except Exception:
        before_rendered, after_rendered = before, after
    diff = [
        line
        for line in difflib.unified_diff(
            before_rendered.splitlines(), after_rendered.splitlines(), lineterm="", n=2
        )
        if not line.startswith(("---", "+++"))
    ]
    removals = sum(1 for line in diff if line.startswith("-"))
    additions = sum(1 for line in diff if line.startswith("+"))
    return diff, removals, additions, section



def _cmd_init(argv: list[str], root: Path) -> int:
    parser = argparse.ArgumentParser(prog="knowledgeos init")
    parser.add_argument("target", type=Path, help="Directory for the new vault")
    parser.add_argument("--name", default="", help="Owner name for Self.md")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Fill in missing files in a non-empty directory (never overwrites existing files)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created, change nothing")
    args = parser.parse_args(argv)

    from knowledgeos.init_vault import init_vault

    try:
        result = init_vault(
            args.target.resolve(),
            source_root=root,
            owner_name=args.name or "Self",
            non_interactive=args.non_interactive,
            force=args.force,
            dry_run=args.dry_run,
        )
    except Exception as e:
        print(f"init failed: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok", True) else 1


def _cmd_memory(argv: list[str], root: Path) -> int:
    from knowledgeos.memory import TOOL_SPECS, MemoryAPI, dispatch

    if not argv or argv[0] in {"-h", "--help", "list"}:
        print("Memory tools:")
        for t in TOOL_SPECS:
            print(f"  {t['name']}: {t['description']}")
        print("\nUsage:")
        print('  python -m knowledgeos memory memory_search --args "{\"query\":\"Self\"}"')
        print("  python -m knowledgeos memory memory_self_get")
        print("  python -m knowledgeos memory memory_bootstrap_context --args \"{\\\"task_hint\\\":\\\"MCP\\\"}\"")
        return 0

    parser = argparse.ArgumentParser(prog="knowledgeos memory")
    parser.add_argument("tool")
    parser.add_argument("--vault", type=Path, default=None)
    parser.add_argument("--args", default="{}", help="JSON object of tool arguments")
    parser.add_argument("--path", default="", help="Shorthand for accept_self_update proposal path")
    # convenience flags for common tools
    parser.add_argument("--query", default="")
    parser.add_argument("--title", default="")
    parser.add_argument("--content", default="")
    parser.add_argument("--task-hint", default="")
    parser.add_argument("--section", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--proposed-markdown", default="")
    parser.add_argument("--rationale", default="")
    parser.add_argument("--path-or-id", default="")
    parser.add_argument(
        "--mode",
        default="",
        choices=["", "replace", "append"],
        help="Self proposal mode (replace or append)",
    )
    parser.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Permit a proposal that deletes most of a Self section",
    )
    args = parser.parse_args(argv)

    try:
        payload = json.loads(args.args) if args.args else {}
    except json.JSONDecodeError as e:
        print(f"Invalid --args JSON: {e}", file=sys.stderr)
        return 1

    # Merge convenience flags
    if args.query:
        payload.setdefault("query", args.query)
    if args.title:
        payload.setdefault("title", args.title)
    if args.content:
        payload.setdefault("content", args.content)
    if args.task_hint:
        payload.setdefault("task_hint", args.task_hint)
    if args.section:
        payload.setdefault("section", args.section)
    if args.summary:
        payload.setdefault("summary", args.summary)
    if args.proposed_markdown:
        payload.setdefault("proposed_markdown", args.proposed_markdown)
    if args.rationale:
        payload.setdefault("rationale", args.rationale)
    if args.path_or_id:
        payload.setdefault("path_or_id", args.path_or_id)
    if args.mode:
        payload.setdefault("mode", args.mode)
    if args.allow_destructive:
        payload.setdefault("allow_destructive", True)
    if args.path:
        payload.setdefault("proposal_path", args.path)

    try:
        vault = require_vault(args.vault)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 1
    api = MemoryAPI(vault)
    result = dispatch(api, args.tool, payload)
    print(json.dumps(result, indent=2, default=str))
    return 1 if isinstance(result, dict) and result.get("error") else 0


def _cmd_breathe(argv: list[str], root: Path) -> int:
    parser = argparse.ArgumentParser(prog="knowledgeos breathe")
    parser.add_argument("--vault", type=Path, default=None)
    parser.add_argument("--task-hint", default="")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument(
        "--prewarm",
        action="store_true",
        help="Host hook warm-up: freshen the index but do not count as a user session",
    )
    args = parser.parse_args(argv)
    from knowledgeos.memory import MemoryAPI
    from knowledgeos.vault_resolve import resolve_vault

    api = MemoryAPI(resolve_vault(args.vault))
    result = api.session_start(
        args.task_hint,
        args.limit,
        source="prewarm" if args.prewarm else "agent",
    )
    print(json.dumps(result, indent=2, default=str))
    return 0


def _cmd_mcp(argv: list[str], root: Path) -> int:
    parser = argparse.ArgumentParser(prog="knowledgeos mcp", allow_abbrev=False)
    parser.add_argument("--vault", type=Path, default=None)
    parser.add_argument("--host-vault-id", default=None,
                        help="Complete discovery ID recorded by setup-host (MCP only)")
    parser.add_argument(
        "--framing",
        choices=["auto", "content-length", "ndjson"],
        default="auto",
        help="stdio framing (default: auto-detect per message; replies match the request)",
    )
    args = parser.parse_args(argv)
    from knowledgeos.vault_resolve import configured_host_vault_id, resolve_host_vault, resolve_vault
    try:
        binding = configured_host_vault_id(argv)
        vault = resolve_host_vault(binding, args.vault) if binding is not None else resolve_vault(args.vault)
    except (ValueError, OSError) as error:
        print(f"Memory startup refused: {error}", file=sys.stderr)
        return 2
    from knowledgeos.mcp_server import run_stdio, run_stdio_auto, run_stdio_content_length

    if args.framing == "ndjson":
        run_stdio(vault)
    elif args.framing == "content-length":
        run_stdio_content_length(vault)
    else:
        run_stdio_auto(vault)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
