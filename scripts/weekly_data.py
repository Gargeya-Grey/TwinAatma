#!/usr/bin/env python
"""Collect weekly KnowledgeOS metrics as JSON without sqlite3 CLI."""
from __future__ import annotations
import json, sqlite3
from datetime import date, timedelta
from pathlib import Path
VAULT_DIR = Path(__file__).resolve().parent.parent
DB = VAULT_DIR / "knowledge_index.db"
since = (date.today() - timedelta(days=7)).isoformat()
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
def one(sql, params=()): return cur.execute(sql, params).fetchone()[0]
def rows(sql, params=()): return [dict(r) for r in cur.execute(sql, params).fetchall()]
content_filter = "path NOT LIKE 'Templates/%'"
out = {
  "vault": str(VAULT_DIR),
  "since": since,
  "notes_created_7d": one(f"SELECT COUNT(*) FROM notes WHERE {content_filter} AND (created >= ? OR updated >= ?)", (since, since)),
  "decisions_7d": one(f"SELECT COUNT(*) FROM notes WHERE {content_filter} AND type='decision' AND (created >= ? OR updated >= ?)", (since, since)),
  "projects_active": one(f"SELECT COUNT(*) FROM notes WHERE {content_filter} AND type='project' AND status='active'"),
  "total_notes": one(f"SELECT COUNT(*) FROM notes WHERE {content_filter}"),
  "total_links": one("SELECT COUNT(*) FROM links"),
  "recent_notes": rows(f"SELECT title, path, type, status, tags, created, updated FROM notes WHERE {content_filter} AND (created >= ? OR updated >= ?) ORDER BY updated DESC LIMIT 20", (since, since)),
  "recent_decisions": rows(f"SELECT title, path, status, created FROM notes WHERE {content_filter} AND type='decision' AND (created >= ? OR updated >= ?) ORDER BY created DESC LIMIT 10", (since, since)),
}
print(json.dumps(out, indent=2))
