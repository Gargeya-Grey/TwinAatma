"""Native Codex TOML with conservative, text-preserving owned-table updates."""
from __future__ import annotations

import json
import re


class UnsafeToml(ValueError):
    pass


def _parser():
    try:
        import tomllib
    except ImportError as exc:
        raise UnsafeToml("Merging an existing Codex config requires Python 3.11+; preserved its bytes.") from exc
    return tomllib.loads


def _value(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(json.dumps(key) + " = " + _value(item) for key, item in value.items()) + " }"
    raise UnsafeToml("Unsupported existing value in the owned Codex table; preserved its bytes.")


def render(server):
    lines = ["[mcp_servers.knowledgeos]"]
    lines.extend(f"{key} = {_value(value)}" for key, value in server.items() if key != "env")
    lines.extend(["", "[mcp_servers.knowledgeos.env]"])
    lines.extend(f"{json.dumps(key)} = {_value(value)}" for key, value in server["env"].items())
    return "\n".join(lines) + "\n"


def _header_path(text, parse):
    tree = parse(text)
    path = []
    while isinstance(tree, dict) and len(tree) == 1:
        key, tree = next(iter(tree.items()))
        path.append(key)
    return tuple(path) if tree == {} else None


def _patch_body(body, updates, parse, removals=()):
    """Keep complete foreign assignments and comments byte-for-byte."""
    lines = body.splitlines(keepends=True)
    output = []
    seen = set()
    offset = 0
    while offset < len(lines):
        if not lines[offset].strip() or lines[offset].lstrip().startswith("#"):
            output.append(lines[offset])
            offset += 1
            continue
        end = offset + 1
        while True:
            chunk = "".join(lines[offset:end])
            try:
                parsed = parse(chunk)
                break
            except ValueError:
                if end == len(lines):
                    raise UnsafeToml("Unsupported owned table layout; preserved its bytes.")
                end += 1
        keys = set(parsed) & (set(updates) | set(removals))
        if keys:
            if len(parsed) != 1 or len(keys) != 1:
                raise UnsafeToml("Unsupported owned assignment layout; preserved its bytes.")
            key = next(iter(keys))
            direct = r"^\s*(?:" + re.escape(key) + "|\"" + re.escape(key) + "\"|'" + re.escape(key) + r"')\s*="
            if not re.match(direct, chunk):
                raise UnsafeToml("Dotted owned assignments cannot be safely merged; preserved its bytes.")
            ending = "\r\n" if chunk.endswith("\r\n") else "\n"
            if key not in removals:
                replacement = f"{json.dumps(key)} = {_value(updates[key])}{ending}"
                # Repeated setup must preserve the first generated representation.
                output.append(chunk if parsed[key] == updates[key] else replacement)
            seen.add(key)
        else:
            output.append(chunk)
        offset = end
    text = "".join(output)
    missing = [key for key in updates if key not in seen]
    if missing and text and not text.endswith(("\n", "\r")):
        text += "\n"
    for key in missing:
        text += f"{key} = {_value(updates[key])}\n"
    return text


def merge(original, server, *, remove_owned=()):
    parse = _parser()
    try:
        data = parse(original)
    except ValueError as exc:
        raise UnsafeToml(f"Invalid Codex TOML; preserved its bytes ({exc}).") from exc
    servers = data.get("mcp_servers", {})
    if not isinstance(servers, dict):
        raise UnsafeToml("Codex mcp_servers must be a table; preserved its bytes.")
    existing = servers.get("knowledgeos", {})
    if not isinstance(existing, dict):
        raise UnsafeToml("Codex knowledgeos must be a table; preserved its bytes.")
    from knowledgeos.vault_resolve import check_host_binding_migration, HostVaultError
    try:
        check_host_binding_migration(existing.get("args", []), server.get("args", []))
    except HostVaultError as error:
        raise UnsafeToml(str(error)) from error
    env = existing.get("env", {})
    if not isinstance(env, dict) or any(not isinstance(value, str) for value in env.values()):
        raise UnsafeToml("Codex knowledgeos env must contain strings; preserved its bytes.")
    merged_env = {**env, **server["env"]}
    lines = original.splitlines(keepends=True)
    headers = []
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("["):
            continue
        try:
            parse("".join(lines[:index]))
            path = _header_path(line, parse)
        except ValueError:
            continue
        headers.append((index, path))
    owner = ("mcp_servers", "knowledgeos")
    positions = {path: index for index, path in headers if path in (owner, owner + ("env",))}
    if "knowledgeos" in servers and owner not in positions:
        raise UnsafeToml("Existing Codex server needs an explicit [mcp_servers.knowledgeos] table; preserved its bytes.")
    if owner not in positions:
        candidate = original + ("\n" if original and not original.endswith("\n") else "") + "\n" + render(server)
    else:
        updates = {key: value for key, value in server.items() if key != "env"}
        if "env" in existing and owner + ("env",) not in positions:
            updates["env"] = merged_env
        pieces = []
        cursor = 0
        for number, (start, path) in enumerate(headers):
            end = headers[number + 1][0] if number + 1 < len(headers) else len(lines)
            pieces.extend(lines[cursor:start + 1])
            body = "".join(lines[start + 1:end])
            if path == owner:
                body = _patch_body(body, updates, parse, remove_owned)
            elif path == owner + ("env",):
                body = _patch_body(body, server["env"], parse)
            pieces.append(body)
            cursor = end
        pieces.extend(lines[cursor:])
        candidate = "".join(pieces)
        if "env" not in existing:
            candidate += ("\n" if not candidate.endswith("\n") else "") + "\n[mcp_servers.knowledgeos.env]\n"
            candidate += "".join(f"{json.dumps(key)} = {_value(value)}\n" for key, value in server["env"].items())
    try:
        result = parse(candidate)
    except ValueError as exc:
        raise UnsafeToml(f"Codex merge could not preserve the existing layout; preserved its bytes ({exc}).") from exc
    expected = {**{key: value for key, value in existing.items() if key not in remove_owned},
                **server, "env": merged_env}
    if result["mcp_servers"]["knowledgeos"] != expected:
        raise UnsafeToml("Codex merge changed an unexpected setting; preserved its bytes.")
    return candidate
