#!/usr/bin/env python
"""Rebuild the KnowledgeOS SQLite index. Thin wrapper over knowledgeos.indexer."""
from __future__ import annotations

import sys
from pathlib import Path

TOOLKIT_DIR = Path(__file__).resolve().parent.parent
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

from knowledgeos.indexer import DB_NAME, rebuild_index  # noqa: E402
from knowledgeos.vault_resolve import resolve_vault  # noqa: E402


def _explicit_vault() -> Path | None:
    if "--vault" in sys.argv:
        idx = sys.argv.index("--vault")
        if idx + 1 < len(sys.argv):
            return Path(sys.argv[idx + 1])
    return None


def main() -> int:
    vault = resolve_vault(_explicit_vault(), cwd=TOOLKIT_DIR)
    print("Rebuilding KnowledgeOS index...")
    print(f"Vault: {vault}")
    print(f"DB: {vault / DB_NAME}")
    counts = rebuild_index(vault)
    print("Done.")
    print(f"Notes: {counts['notes']}")
    print(f"Links: {counts['links']}")
    print(f"FTS updates: {counts['fts_updates']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
