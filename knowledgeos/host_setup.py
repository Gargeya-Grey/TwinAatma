"""Generate MCP host configs pointing at a vault (no checked-in absolute paths)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HOSTS = ("codex", "cursor", "claude-desktop", "windsurf", "vscode", "generic-stdio")


class UnsupportedHost(Exception):
    """Raised for transports this build does not implement."""


class InvalidHostConfig(ValueError):
    """An existing host document cannot be safely merged."""


def _binary_command() -> tuple[str, list[str], dict[str, str]]:
    """(command, base args, extra env) that starts the MCP server on this machine."""
    exe = Path(sys.argv[0]).resolve()
    if getattr(sys, "frozen", False):
        return str(exe), [], {}
    name = exe.name.lower()
    if name in ("twinaatma", "knowledgeos", "twinaatma.exe", "knowledgeos.exe"):
        # Setuptools removes .exe from argv[0] on Windows. POSIX console
        # scripts already have no suffix; neither needs PATH activation.
        entry = exe if exe.is_file() else exe.with_suffix(".exe")
        if entry.is_file():
            return str(entry), [], {}

    found = _which_trusted("twinaatma") or _which_trusted("twinaatma.exe")
    if found:
        return found, [], {}

    if sys.version_info < (3, 11):
        raise UnsupportedHost(
            "Running the server from a source checkout needs Python 3.11+ (for `-P`) "
            "or an installed console script. Install with `pip install -e .`, "
            "or use the packaged binary."
        )

    # Source checkout: import the package from the toolkit root only. `-P` keeps the
    # workspace off sys.path so a `knowledgeos/` folder dropped into the vault cannot
    # be imported and executed by the agent's own MCP server.
    from knowledgeos.resources import import_root

    root = import_root()
    return sys.executable, ["-P", "-m", "knowledgeos"], {"PYTHONPATH": str(root)}


def _which_trusted(name: str) -> str | None:
    """Locate an executable without trusting the working directory.

    ``shutil.which`` on Windows searches the CWD first, so a file named
    ``twinaatma.EXE`` dropped into the vault would be launched on every chat once
    ``setup-host`` recorded it. Only absolute PATH/PATHEXT entries are accepted.

    Delegates to :func:`knowledgeos.safe_exec.resolve_executable`, which the drift pass
    and `doctor` also use. Two resolvers meant two chances for them to drift apart, and
    the second one is exactly what let a planted `git.exe` run.
    """
    from knowledgeos.safe_exec import resolve_executable

    return resolve_executable(name)


def build_config(host: str, vault: Path, transport: str = "stdio") -> dict:
    from knowledgeos.vault_resolve import read_vault_id
    vault_id = read_vault_id(vault)
    vault = vault.resolve()
    if transport != "stdio" or host == "generic-http":
        raise UnsupportedHost(
            "HTTP transport is not implemented in this build. Use the default stdio transport."
        )
    cmd, base_args, extra_env = _binary_command()
    binding = ["--host-vault-id", vault_id] if vault_id is not None else []
    args = [*base_args, "mcp", *binding, "--vault", str(vault)]
    env = {"KNOWLEDGEOS_VAULT": str(vault), **extra_env}
    server = {
        "command": cmd,
        "args": args,
        "env": env,
    }
    if vault_id is None:
        server["cwd"] = str(vault)
    if host == "codex":
        return {"mcp_servers": {"knowledgeos": {**server, "required": True, "default_tools_approval_mode": "approve"}}}
    if host == "vscode":
        return {"servers": {"knowledgeos": {**server, "type": "stdio"}}}
    return {"mcpServers": {"knowledgeos": server}}


def config_target(host: str, vault: Path) -> Path | None:
    """Where a host reads its project-local config, when it supports one."""
    if host == "codex":
        return vault / ".codex" / "config.toml"
    if host == "cursor":
        return vault / ".cursor" / "mcp.json"
    if host == "vscode":
        return vault / ".vscode" / "mcp.json"
    return None


def write_config(host: str, vault: Path, transport: str = "stdio") -> Path:
    target = config_target(host, vault)
    if target is None:
        raise UnsupportedHost(
            f"{host} does not read a project-local MCP config. Use --print and paste the JSON "
            "into that host's MCP settings."
        )
    from knowledgeos.data_ops import plain_vault_path
    from knowledgeos.textio import atomic_write_bytes

    try:
        target = plain_vault_path(vault, target)
    except ValueError as exc:
        raise InvalidHostConfig(str(exc)) from exc
    payload = build_config(host, vault, transport)
    if host == "codex":
        from knowledgeos.codex_config import UnsafeToml, merge, render
        server = payload["mcp_servers"]["knowledgeos"]
        try:
            text = merge(target.read_bytes().decode("utf-8"), server,
                         remove_owned=("cwd",) if "cwd" not in server else ()) if target.exists() else render(server)
        except (UnsafeToml, UnicodeError) as exc:
            raise InvalidHostConfig(f"Preserved {target}: {exc}") from exc
    else:
        existing: dict = {}
        if target.exists():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise InvalidHostConfig(f"Preserved {target}: cannot read its JSON ({exc}). Repair the existing config and retry.") from exc
            if not isinstance(existing, dict):
                raise InvalidHostConfig(f"Preserved {target}: the config must be a JSON object. Repair it and retry.")
        key = "servers" if host == "vscode" else "mcpServers"
        servers = existing.get(key, {})
        if not isinstance(servers, dict):
            raise InvalidHostConfig(f"Preserved {target}: '{key}' must be a JSON object. Repair it and retry.")
        owned = servers.get("knowledgeos", {})
        if not isinstance(owned, dict) or not isinstance(owned.get("env", {}), dict):
            raise InvalidHostConfig(f"Preserved {target}: knowledgeos and its env must be JSON objects.")
        generated = payload[key]["knowledgeos"]
        from knowledgeos.vault_resolve import check_host_binding_migration, HostVaultError
        try:
            check_host_binding_migration(owned.get("args", []), generated["args"])
        except HostVaultError as exc:
            raise InvalidHostConfig(f"Preserved {target}: {exc}") from exc
        if "cwd" not in generated:
            owned = {name: value for name, value in owned.items() if name != "cwd"}
        servers["knowledgeos"] = {**owned, **generated, "env": {**owned.get("env", {}), **generated["env"]}}
        existing[key] = servers
        text = json.dumps(existing, indent=2) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    plain_vault_path(vault, target)
    atomic_write_bytes(target, text.encode("utf-8"))
    return target


def render_codex_config(config: dict) -> str:
    """Render a Codex MCP configuration in its native TOML format."""
    from knowledgeos.codex_config import render
    return render(config["mcp_servers"]["knowledgeos"])


def _render_config(host: str, config: dict) -> str:
    if host == "codex":
        return render_codex_config(config)
    return json.dumps(config, indent=2) + "\n"


def main(argv: list[str] | None = None, source_root: Path | None = None) -> int:
    import argparse

    from knowledgeos.vault_resolve import resolve_vault

    parser = argparse.ArgumentParser(prog="knowledgeos setup-host")
    parser.add_argument("--host", choices=HOSTS, default="cursor")
    parser.add_argument("--vault", type=Path, default=None)
    parser.add_argument("--transport", choices=["stdio"], default="stdio")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write into the host's project config (e.g. <vault>/.codex/config.toml)",
    )
    parser.add_argument("--print", dest="do_print", action="store_true")
    args = parser.parse_args(argv)

    try:
        from knowledgeos.vault_resolve import read_vault_id
        if args.vault is not None:
            read_vault_id(args.vault)
            if not args.vault.expanduser().exists():
                read_vault_id(Path.cwd())
        else:
            read_vault_id(Path.cwd())
            if os.environ.get("KNOWLEDGEOS_VAULT"):
                read_vault_id(os.environ["KNOWLEDGEOS_VAULT"])
        vault = resolve_vault(args.vault) if args.vault else resolve_vault()
        if args.out:
            cfg = build_config(args.host, vault, args.transport)
            from knowledgeos.data_ops import plain_vault_path
            text = _render_config(args.host, cfg)
            target = Path(os.path.abspath(args.out.expanduser()))
            try:
                target = plain_vault_path(Path(target.anchor), target)
            except ValueError as exc:
                raise InvalidHostConfig(str(exc)) from exc
            if target.exists():
                raise InvalidHostConfig(f"Preserved {target}: --out requires a new file.")
            target.parent.mkdir(parents=True, exist_ok=True)
            plain_vault_path(Path(target.anchor), target)
            with target.open("xb") as handle:
                handle.write(text.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            print(f"Wrote {args.host} config for vault {vault} -> {target}")
            return 0
        if args.write:
            target = write_config(args.host, vault, args.transport)
            print(f"Wrote {args.host} config for vault {vault} -> {target}")
            return 0
        print(_render_config(args.host, build_config(args.host, vault, args.transport)), end="")
        return 0
    except (UnsupportedHost, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
