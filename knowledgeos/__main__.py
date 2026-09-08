"""CLI entry: python -m knowledgeos <command>"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_vault() -> Path:
    from knowledgeos.vault_resolve import resolve_vault

    return resolve_vault()


def resolve_vault_cli(explicit: Path | None) -> Path:
    from knowledgeos.vault_resolve import resolve_vault

    return resolve_vault(explicit)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help", "help"}:
        from knowledgeos import __version__

        print(
            f"KnowledgeOS CLI (v{__version__})\n\n"
            "Commands:\n"
            "  doctor                Run environment diagnostics\n"
            "  validate              Validate vault schema\n"
            "  ids assign [--write]  Assign kos:<type>:<slug> IDs (dry-run default)\n"
            "  self summary          Parse People/Self.md ego node\n"
            "  init <path>           Create a starter vault\n"
            "  memory <tool>         Call Memory API tools (CLI fallback for MCP)\n"
            "  breathe               Autopilot tick (freshen + load + soft prompts)\n"
            "  mcp                   Start MCP Memory server (stdio)\n"
            "  setup-host            Generate MCP host config for a vault\n"
            "  version               Print package version\n"
        )
        return 0

    cmd = argv[0]
    root = _root()
    scripts = root / "scripts"

    if cmd == "version":
        from knowledgeos import __version__

        print(__version__)
        return 0

    if cmd == "doctor":
        import os
        import runpy

        rest = argv[1:]
        vault = _default_vault()
        if "--vault" in rest:
            idx = rest.index("--vault")
            if idx + 1 < len(rest):
                vault = Path(rest[idx + 1]).expanduser().resolve()
        os.environ["KNOWLEDGEOS_VAULT"] = str(vault)
        runpy.run_path(str(scripts / "doctor.py"), run_name="__main__")
        return 0

    if cmd == "validate":
        import os
        import runpy

        rest = argv[1:]
        vault = _default_vault()
        if "--vault" in rest:
            idx = rest.index("--vault")
            if idx + 1 < len(rest):
                vault = Path(rest[idx + 1]).expanduser().resolve()
        os.environ["KNOWLEDGEOS_VAULT"] = str(vault)
        runpy.run_path(str(scripts / "validate_schema.py"), run_name="__main__")
        return 0

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
    if not argv or argv[0] != "summary":
        print("Usage: python -m knowledgeos self summary [--path People/Self.md]", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(prog="knowledgeos self summary")
    parser.add_argument("--path", type=Path, default=None)
    parser.add_argument("--vault", type=Path, default=None)
    args = parser.parse_args(argv[1:])
    if args.path:
        path = args.path if args.path.is_absolute() else (resolve_vault_cli(args.vault) / args.path)
    else:
        path = resolve_vault_cli(args.vault) / "People" / "Self.md"
    if not path.exists():
        print(f"Self note not found: {path}", file=sys.stderr)
        return 1
    from knowledgeos.self_model import load_self

    model = load_self(path)
    print(json.dumps(model.summary(), indent=2))
    return 0


def _cmd_init(argv: list[str], root: Path) -> int:
    parser = argparse.ArgumentParser(prog="knowledgeos init")
    parser.add_argument("target", type=Path, help="Directory for the new vault")
    parser.add_argument("--name", default="", help="Owner name for Self.md")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--force", action="store_true", help="Allow non-empty target if only minor files exist")
    args = parser.parse_args(argv)

    from knowledgeos.init_vault import init_vault

    try:
        result = init_vault(
            args.target.resolve(),
            source_root=root,
            owner_name=args.name or "Self",
            non_interactive=args.non_interactive,
            force=args.force,
        )
    except Exception as e:
        print(f"init failed: {e}", file=sys.stderr)
        return 1
    # Append MCP snippet (dynamic, no hardcoded paths)
    from knowledgeos.host_setup import build_config

    result["mcp_cursor_config"] = build_config("cursor", Path(result["vault"]))
    print(json.dumps(result, indent=2))
    return 0


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
    if args.path:
        payload.setdefault("proposal_path", args.path)

    api = MemoryAPI(resolve_vault_cli(args.vault))
    result = dispatch(api, args.tool, payload)
    print(json.dumps(result, indent=2, default=str))
    return 1 if isinstance(result, dict) and result.get("error") else 0


def _cmd_breathe(argv: list[str], root: Path) -> int:
    parser = argparse.ArgumentParser(prog="knowledgeos breathe")
    parser.add_argument("--vault", type=Path, default=None)
    parser.add_argument("--task-hint", default="")
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args(argv)
    from knowledgeos.memory import MemoryAPI
    from knowledgeos.vault_resolve import resolve_vault

    api = MemoryAPI(resolve_vault(args.vault))
    result = api.session_start(args.task_hint, args.limit)
    print(json.dumps(result, indent=2, default=str))
    return 0


def _cmd_mcp(argv: list[str], root: Path) -> int:
    parser = argparse.ArgumentParser(prog="knowledgeos mcp")
    parser.add_argument("--vault", type=Path, default=None)
    parser.add_argument(
        "--framing",
        choices=["content-length", "ndjson"],
        default="content-length",
        help="stdio framing (default: content-length for Cursor/Claude Desktop)",
    )
    args = parser.parse_args(argv)
    from knowledgeos.vault_resolve import resolve_vault

    vault = resolve_vault(args.vault)
    from knowledgeos.mcp_server import run_stdio, run_stdio_content_length

    if args.framing == "ndjson":
        run_stdio(vault)
    else:
        run_stdio_content_length(vault)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
