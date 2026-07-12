#!/usr/bin/env python
"""KnowledgeOS smoke test for parser, Self model, index columns, and ids dry-run."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from knowledgeos.ids import assign_ids_for_vault
from knowledgeos.parser import parse_frontmatter
from knowledgeos.self_model import load_self


def main() -> int:
    fm = parse_frontmatter("---\npublish_to_notion: true\ntags: [a, b]\n---\n")
    assert fm["publish_to_notion"] is True
    assert fm["tags"] == ["a", "b"]

    db = ROOT / "knowledge_index.db"
    if not db.exists():
        print("MISSING_INDEX: run python scripts/rebuild_index.py", file=sys.stderr)
        return 1
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(notes)")}
    for required in ("entity_id", "confidence", "last_reviewed", "outcome_status"):
        assert required in cols, required
    self_id = conn.execute(
        "SELECT entity_id FROM notes WHERE path = ?", ("People/Self.md",)
    ).fetchone()
    assert self_id and self_id[0] == "kos:person:self", self_id

    model = load_self(ROOT / "People" / "Self.md")
    for key in ("heuristics", "values", "mental_models", "anti_goals", "active_bets", "drift_log"):
        assert key in model.sections, key

    missing = assign_ids_for_vault(ROOT, write=False, only_missing=True)
    print(
        json.dumps(
            {
                "ok": True,
                "index_columns": sorted(cols),
                "self_sections": sorted(model.sections),
                "ids_missing": len(missing),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
