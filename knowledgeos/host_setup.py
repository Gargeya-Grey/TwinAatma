"""Generate MCP host configs pointing at a vault (no checked-in absolute paths)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HOSTS = ("cursor", "claude-desktop", "windsurf", "vscode", "generic-stdio", "generic-http")


def _binary_command() -> tuple[str, list[str]]:
    exe = Path(sys.argv[0]).resolve()
    name = exe.name.lower()
    if name.startswith("twinaatma") and exe.exists():
        return str(exe), []
    if name.startswith("knowledgeos") and exe.suffix.lower() == ".exe" and exe.exists():
        return str(exe), []
    return "python", ["-m", "knowledgeos"]


def build_config(host: str, vault: Path, transport: str = "stdio") -> dict:
    vault = vault.resolve()
    if host in ("generic-http",) or transport == "http":
        return {
            "mcpServers": {
                "knowledgeos": {
                    "url": "http://127.0.0.1:8765/mcp",
                    "env": {"KNOWLEDGEOS_VAULT": str(vault)},
                    "note": "Requires: twinaatma serve --vault <vault> (Phase C HTTP server)",
                }
            }
        }
    cmd, base_args = _binary_command()
    args = [*base_args, "mcp", "--vault", str(vault)]
    server = {
        "command": cmd,
        "args": args,
        "cwd": str(vault),
        "env": {"KNOWLEDGEOS_VAULT": str(vault)},
    }
    if host == "vscode":
        return {"servers": {"knowledgeos": {**server, "type": "stdio"}}}
    return {"mcpServers": {"knowledgeos": server}}


def main(argv: list[str] | None = None, source_root: Path | None = None) -> int:
    import argparse

    from knowledgeos.vault_resolve import resolve_vault

    parser = argparse.ArgumentParser(prog="knowledgeos setup-host")
    parser.add_argument("--host", choices=HOSTS, default="cursor")
    parser.add_argument("--vault", type=Path, default=None)
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--print", dest="do_print", action="store_true")
    args = parser.parse_args(argv)

    vault = resolve_vault(args.vault) if args.vault else resolve_vault()
    cfg = build_config(args.host, vault, args.transport)
    text = json.dumps(cfg, indent=2)
    if args.out:
        args.out.expanduser().resolve().write_text(text, encoding="utf-8")
        print(f"Wrote {args.host} ({args.transport}) config for vault {vault} -> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
