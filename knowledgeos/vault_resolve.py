"""Vault resolution: --vault > KNOWLEDGEOS_VAULT > walk-up from cwd."""
from __future__ import annotations

import os
from pathlib import Path

MARKER_FILES = (".knowledgeos-vault.json", "knowledgeos.config.json")
SELF_REL = Path("People") / "Self.md"


def is_vault_root(path: Path) -> bool:
    try:
        if not path.is_dir():
            return False
        if (path / SELF_REL).exists():
            return True
        return any((path / m).exists() for m in MARKER_FILES)
    except OSError:
        return False


def walk_up(start: Path) -> Path | None:
    cur = start.resolve()
    while True:
        if is_vault_root(cur):
            return cur
        parent = cur.parent
        if parent == cur:
            return None
        cur = parent


def resolve_vault(explicit: Path | str | None = None, cwd: Path | str | None = None) -> Path:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        return p
    env = os.environ.get("KNOWLEDGEOS_VAULT")
    if env:
        return Path(env).expanduser().resolve()
    base = Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()
    found = walk_up(base)
    if found:
        return found
    return base
