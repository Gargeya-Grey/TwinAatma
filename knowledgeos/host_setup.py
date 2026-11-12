"""Generate MCP host configs pointing at a vault (no checked-in absolute paths)."""
from __future__ import annotations

import json
import hashlib
import os
import sys
from pathlib import Path

HOSTS = ("codex", "cursor", "claude-code", "claude-desktop", "windsurf", "vscode", "generic-stdio")
# Hosts with their own command that registers a server for every project of one person.
USER_LEVEL_HOSTS = {"claude-code": "claude", "codex": "codex"}


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
    if host == "claude-code":
        return vault / ".mcp.json"
    if host == "vscode":
        return vault / ".vscode" / "mcp.json"
    return None


def _generated_reconnect_plan(
    vault: Path, selected: Path, selected_payload: bytes,
) -> tuple[list[tuple[Path, bytes | None, bytes]], list[str]]:
    """Refresh only unchanged initializer output, never infer ownership from commands."""
    from knowledgeos.data_ops import plain_vault_path
    from knowledgeos.init_vault import _hooks_config
    from knowledgeos.resources import toolkit_root

    receipt = plain_vault_path(vault, vault / ".knowledgeos-init.json")
    receipt_before = receipt.read_bytes() if receipt.exists() else None
    report = json.loads(receipt_before) if receipt_before is not None else {}
    if not isinstance(report, dict):
        raise InvalidHostConfig(f"Preserved {receipt}: the init receipt must be a JSON object.")
    ownership = report.get("generated_host_files", {"version": 1, "files": {}})
    if (not isinstance(ownership, dict) or ownership.get("version") != 1
            or not isinstance(ownership.get("files"), dict)
            or any(not isinstance(value, str) or len(value) != 64
                   or any(char not in "0123456789abcdef" for char in value)
                   for value in ownership["files"].values())):
        raise InvalidHostConfig(f"Preserved {receipt}: unsupported generated-host ownership receipt.")
    recorded = dict(ownership["files"])
    cursor = (json.dumps(build_config("cursor", vault), indent=2) + "\n").encode("utf-8")
    generated = {".cursor/mcp.json": cursor, "mcp.cursor.json": cursor}
    hooks = plain_vault_path(vault, vault / ".cursor/hooks.json")
    if hooks.exists():
        source = toolkit_root()
        template = source / ".cursor/hooks.json"
        if not template.is_file():
            raise UnsupportedHost("The installed Cursor hook template is missing. Reinstall the toolkit and retry.")
        generated[".cursor/hooks.json"] = _hooks_config(template, vault, source).encode("utf-8")
    writes: list[tuple[Path, bytes | None, bytes]] = []
    preserved: list[str] = []
    for relative, payload in generated.items():
        target = plain_vault_path(vault, vault / relative)
        if not target.exists():
            continue
        original = target.read_bytes()
        try:
            data = json.loads(original)
        except (ValueError, UnicodeError) as exc:
            raise InvalidHostConfig(f"Preserved {target}: cannot read its JSON ({exc}). Repair it and retry.") from exc
        if not isinstance(data, dict):
            raise InvalidHostConfig(f"Preserved {target}: the config must be a JSON object.")
        if relative == ".cursor/hooks.json":
            groups = data.get("hooks")
            if (not isinstance(groups, dict)
                    or any(not isinstance(group, list) for group in groups.values())
                    or any(not isinstance(entry, dict) or not isinstance(entry.get("command"), str)
                           or not entry["command"].strip()
                           for group in groups.values() for entry in group)):
                raise InvalidHostConfig(f"Preserved {target}: hooks must contain lists of command objects.")
        else:
            servers = data.get("mcpServers", {})
            owned = servers.get("knowledgeos", {}) if isinstance(servers, dict) else None
            if (not isinstance(servers, dict) or not isinstance(owned, dict)
                    or not isinstance(owned.get("env", {}), dict)):
                raise InvalidHostConfig(f"Preserved {target}: mcpServers, knowledgeos and its env must be JSON objects.")
        if target == selected:
            if selected_payload == payload:
                recorded[relative] = hashlib.sha256(payload).hexdigest()
            continue
        if original == payload:
            recorded[relative] = hashlib.sha256(payload).hexdigest()
        elif ownership["files"].get(relative) == hashlib.sha256(original).hexdigest():
            writes.append((target, original, payload))
            recorded[relative] = hashlib.sha256(payload).hexdigest()
        elif relative == ".cursor/hooks.json":
            raise InvalidHostConfig(
                f"Preserved {target}: hooks were edited or have no matching generation receipt. "
                f"Run `twinaatma init {vault}` to prepare hooks.new.json, then review and merge "
                "your hooks before retrying setup-host. No host configuration was changed."
            )
        else:
            preserved.append(f"Preserved {target}: custom or unrecorded MCP config; reconnect that host separately if needed.")
    if receipt_before is not None and recorded != ownership["files"]:
        report["generated_host_files"] = {"version": 1, "files": recorded}
        writes.append((receipt, receipt_before, (json.dumps(report, indent=2) + "\n").encode("utf-8")))
    return writes, preserved


def write_config(host: str, vault: Path, transport: str = "stdio") -> Path:
    target = config_target(host, vault)
    if target is None:
        raise UnsupportedHost(
            f"{host} does not read a project-local MCP config. Use --print and paste the JSON "
            "into that host's MCP settings."
        )
    from knowledgeos.data_ops import plain_vault_path
    from knowledgeos.textio import atomic_create_bytes, atomic_write_bytes

    try:
        target = plain_vault_path(vault, target)
    except ValueError as exc:
        raise InvalidHostConfig(str(exc)) from exc
    original = target.read_bytes() if target.exists() else None
    payload = build_config(host, vault, transport)
    if host == "codex":
        from knowledgeos.codex_config import UnsafeToml, merge, render
        server = payload["mcp_servers"]["knowledgeos"]
        try:
            text = merge(original.decode("utf-8"), server,
                         remove_owned=("cwd",) if "cwd" not in server else ()) if original is not None else render(server)
        except (UnsafeToml, UnicodeError) as exc:
            raise InvalidHostConfig(f"Preserved {target}: {exc}") from exc
    else:
        existing: dict = {}
        if original is not None:
            try:
                existing = json.loads(original)
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
    contents = text.encode("utf-8")
    try:
        reconnect, preserved = _generated_reconnect_plan(vault, target, contents)
    except (ValueError, OSError) as exc:
        raise InvalidHostConfig(f"Cannot reconnect generated host files; existing configuration was preserved: {exc}") from exc
    writes = [(target, original, contents), *reconnect]
    for path, before, _ in writes:
        plain_vault_path(vault, path)
        if (path.read_bytes() if path.exists() else None) != before:
            raise InvalidHostConfig(f"Preserved {path}: configuration changed during setup. Retry.")
    for path, before, after in writes:
        if before == after:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        plain_vault_path(vault, path)
        if (path.read_bytes() if path.exists() else None) != before:
            raise InvalidHostConfig(f"Preserved {path}: configuration changed during setup. Retry.")
        if before is None:
            atomic_create_bytes(path, after)
        else:
            atomic_write_bytes(path, after)
    for message in preserved:
        print(message, file=sys.stderr)
    return target


def user_command(host: str, vault: Path, transport: str = "stdio") -> list[str]:
    """The host's own command that makes this vault available in every project.

    A project config only helps inside the vault folder, and people rarely work there.
    The host owns its user-level file and rewrites it while it runs, so this goes through
    the host's own command instead of editing that file.
    """
    if host not in USER_LEVEL_HOSTS:
        raise UnsupportedHost(
            f"{host} has no user-level setup in this build. Use --write for its project "
            "config, or --print and paste the result into that host's MCP settings."
        )
    key = "mcp_servers" if host == "codex" else "mcpServers"
    server = build_config(host, vault, transport)[key]["knowledgeos"]
    env = [part for name, value in server["env"].items() for part in ("--env", f"{name}={value}")]
    launch = [server["command"], *server["args"]]
    if host == "codex":
        return ["codex", "mcp", "add", "knowledgeos", *env, "--", *launch]
    # `--env` takes several pairs, so another option has to sit between it and the name.
    return ["claude", "mcp", "add", "--scope", "user", *env, "--transport", "stdio",
            "knowledgeos", "--", *launch]


def _shell_line(argv: list[str]) -> str:
    import shlex
    import subprocess

    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def install_user(host: str, vault: Path, transport: str = "stdio", *,
                 resolve=None, run=None) -> tuple[bool, str]:
    """Register the vault with the host for every project. ``(done, message)``.

    When the host's command cannot be started from here, nothing is changed and the
    message holds the exact line for the person to run.
    """
    import subprocess

    argv = user_command(host, vault, transport)
    line = _shell_line(argv)
    if resolve is None:
        from knowledgeos.safe_exec import resolve_executable

        def resolve(name: str) -> str | None:
            # A program inside the vault is never the host: notes must not start code.
            return resolve_executable(name, forbid_under=vault)

    program = resolve(argv[0])
    if program is None:
        return False, f"`{argv[0]}` was not found on PATH. Install {host}, then run:\n  {line}"
    if os.name == "nt" and Path(program).suffix.lower() != ".exe":
        # A .cmd or .bat wrapper re-parses its arguments through cmd.exe.
        return False, f"`{argv[0]}` is a script wrapper on this machine. Run this yourself:\n  {line}"
    try:
        done = (run or subprocess.run)(
            [program, *argv[1:]], capture_output=True, text=True, timeout=60,
            stdin=subprocess.DEVNULL, shell=False, cwd=str(Path.home()),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"`{argv[0]}` could not be started ({exc}). Run this yourself:\n  {line}"
    if done.returncode != 0:
        said = ((done.stderr or "").strip() or (done.stdout or "").strip()).splitlines()[-1:]
        remove = ("codex mcp remove knowledgeos" if host == "codex"
                  else "claude mcp remove knowledgeos --scope user")
        return False, (
            f"{host} did not accept the change: {said[0] if said else 'no reason given'}\n"
            f"If a server named knowledgeos is already registered, remove it with\n  {remove}\n"
            "and run this command again."
        )
    return True, (f"Registered vault {Path(vault).resolve()} with {host} for every project. "
                  f"Start a new {host} session to use it.")


# Claude Code has a memory of its own and prefers it. These two events put the person's
# vault in front of the model without a tool call. See knowledgeos/claude_hook.py.
CLAUDE_HOOK_TIMEOUTS = {"SessionStart": 60, "UserPromptSubmit": 20}
_CLAUDE_HOOK_MARK = ["hook", "claude-code"]


def claude_settings_path() -> Path:
    """The Claude Code settings file of this person."""
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base).expanduser() if base else Path.home() / ".claude") / "settings.json"


def claude_hook_groups(vault: Path) -> dict[str, dict]:
    """One hook group per event. Each starts this installation directly, with no shell."""
    command, base_args, extra_env = _binary_command()
    if extra_env:
        # A hook entry cannot carry the import path a source checkout needs.
        raise UnsupportedHost(
            "The Claude Code hooks need the installed `twinaatma` command. Install the "
            "package with pip, then run this command again."
        )
    args = [*base_args, *_CLAUDE_HOOK_MARK, "--vault", str(Path(vault).resolve())]
    return {event: {"hooks": [{"type": "command", "command": command, "args": args, "timeout": timeout}]}
            for event, timeout in CLAUDE_HOOK_TIMEOUTS.items()}


def _is_claude_hook(handler: object) -> bool:
    args = handler.get("args") if isinstance(handler, dict) else None
    return isinstance(args, list) and any(
        args[index:index + 2] == _CLAUDE_HOOK_MARK for index in range(len(args)))


def merge_claude_hooks(settings: dict, groups: dict[str, dict]) -> dict:
    """A copy of ``settings`` with this toolkit's hooks set to ``groups``. All else is kept."""
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        raise InvalidHostConfig("'hooks' must be a JSON object")
    merged = dict(hooks)
    for event, group in groups.items():
        existing = merged.get(event, [])
        if not isinstance(existing, list):
            raise InvalidHostConfig(f"'hooks.{event}' must be a list")
        kept = []
        for other in existing:
            handlers = other.get("hooks") if isinstance(other, dict) else None
            if not isinstance(handlers, list):
                kept.append(other)
                continue
            foreign = [handler for handler in handlers if not _is_claude_hook(handler)]
            if len(foreign) == len(handlers):
                kept.append(other)
            elif foreign:
                kept.append({**other, "hooks": foreign})
        merged[event] = [*kept, group]
    return {**settings, "hooks": merged}


def claude_hooks_snippet(vault: Path) -> str:
    return json.dumps({"hooks": {event: [group] for event, group in claude_hook_groups(vault).items()}},
                      indent=2)


def install_claude_hooks(vault: Path, settings_path: Path | None = None) -> tuple[bool, str]:
    """Add the two hooks to the person's Claude Code settings. ``(done, message)``.

    Everything else in the file is kept. A file this cannot read safely is left as it
    is, and the message holds the entries for the person to add.
    """
    from knowledgeos.textio import atomic_create_bytes, atomic_write_bytes

    path = Path(settings_path) if settings_path is not None else claude_settings_path()
    groups = claude_hook_groups(vault)

    def by_hand(reason: str) -> tuple[bool, str]:
        return False, (f"Left {path} unchanged: {reason}. To let Claude Code read this vault "
                       f"before each answer, add these entries to it yourself:\n{claude_hooks_snippet(vault)}")

    if path.is_symlink():
        return by_hand("it is a link, and a rewrite would replace the link with a file")
    try:
        original = path.read_bytes() if path.exists() else None
        settings = json.loads(original.decode("utf-8-sig")) if original is not None else {}
    except (OSError, ValueError, UnicodeError) as exc:
        return by_hand(f"it cannot be read as JSON ({exc})")
    if not isinstance(settings, dict):
        return by_hand("it does not hold a JSON object")
    try:
        merged = merge_claude_hooks(settings, groups)
    except InvalidHostConfig as exc:
        return by_hand(str(exc))
    if merged == settings:
        return True, f"Claude Code already reads this vault before each answer ({path})."
    payload = (json.dumps(merged, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if (path.read_bytes() if path.exists() else None) != original:
            return by_hand("it changed during setup")
        if original is None:
            atomic_create_bytes(path, payload)
        else:
            mode = path.stat().st_mode & 0o777
            atomic_write_bytes(path, payload)
            if os.name != "nt":
                os.chmod(path, mode)
    except OSError as exc:
        return by_hand(f"it could not be written ({exc})")
    return True, (f"Claude Code now reads this vault before each answer. Changed {path}: two "
                  "entries under \"hooks\" run `hook claude-code`. Remove them to undo, or use "
                  "--no-hooks to skip this step.")


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
        help="Write the host's project config and reconnect unchanged generated Cursor files to this installation",
    )
    parser.add_argument("--print", dest="do_print", action="store_true")
    parser.add_argument(
        "--global", dest="user_level", action="store_true",
        help="Register the vault for every project of this person, through the host's own "
             "command (claude-code, codex). With --print, only show that command.",
    )
    parser.add_argument(
        "--no-hooks", dest="no_hooks", action="store_true",
        help="With --global for claude-code: do not add the two hooks that put this vault "
             "in front of Claude Code before each answer.",
    )
    args = parser.parse_args(argv)
    if args.user_level and (args.out or args.write):
        print("--global cannot be combined with --write or --out.", file=sys.stderr)
        return 2

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
        if args.user_level:
            hooks = args.host == "claude-code" and not args.no_hooks
            if args.do_print:
                print(_shell_line(user_command(args.host, vault, args.transport)))
                if hooks:
                    try:
                        snippet = claude_hooks_snippet(vault)
                    except UnsupportedHost as exc:
                        print(str(exc), file=sys.stderr)
                    else:
                        print(f"\nAnd these entries in {claude_settings_path()}:\n{snippet}")
                return 0
            done, message = install_user(args.host, vault, args.transport)
            print(message, file=sys.stdout if done else sys.stderr)
            # A registration the host refused may already exist, so the hooks are still
            # set. A machine that never ran Claude Code gets no settings file from here.
            if hooks and (done or claude_settings_path().parent.is_dir()):
                try:
                    hooked, note = install_claude_hooks(vault)
                except UnsupportedHost as exc:
                    hooked, note = False, str(exc)
                print(note, file=sys.stdout if hooked else sys.stderr)
            return 0 if done else 1
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
