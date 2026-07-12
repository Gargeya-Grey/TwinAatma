#!/usr/bin/env python
"""KnowledgeOS search — metadata + FTS5 body index (blended ranking)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
if str(VAULT_DIR) not in sys.path:
    sys.path.insert(0, str(VAULT_DIR))

from knowledgeos.search import blended_search  # noqa: E402

DB = VAULT_DIR / "knowledge_index.db"


def main() -> int:
    query = " ".join(sys.argv[1:]).strip()
    if not query:
        print("Usage: python scripts/search.py <search query>")
        return 1
    result = blended_search(DB, query, limit=20)
    if result.get("error"):
        print(result["error"], file=sys.stderr)
        return 1

    print("=== KnowledgeOS Search ===")
    print(f"Query: {query}")
    print(f"Mode: {result.get('mode')} | FTS available: {result.get('fts_available')}\n")

    print("--- Ranked (blended) ---")
    ranked = result.get("ranked") or []
    if not ranked:
        print("(none)")
    for row in ranked:
        snip = (row.get("snippet") or "").replace("\n", " ")[:120]
        line = f"{row.get('score')} | {row.get('title')} | {row.get('path')} | {row.get('source')} | {snip}"
        print(line.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))

    print("\n--- FTS body hits ---")
    fts = result.get("fts") or []
    if not fts:
        print("(none)" if result.get("fts_available") else "(FTS index missing — run rebuild_index.py)")
    for row in fts:
        line = f"{row.get('title')} | {row.get('path')} | {row.get('snippet')}"
        print(line.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace"))

    if "--json" in sys.argv:
        print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
