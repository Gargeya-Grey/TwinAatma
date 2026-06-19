#!/usr/bin/env python
"""KnowledgeOS agentic search using the SQLite index plus direct content search."""
from __future__ import annotations
import sqlite3, sys
from pathlib import Path
VAULT_DIR = Path(__file__).resolve().parent.parent
DB = VAULT_DIR / "knowledge_index.db"
query = " ".join(sys.argv[1:]).strip()
if not query:
    print("Usage: python scripts/search.py <search query>")
    raise SystemExit(1)
conn = sqlite3.connect(DB)
cur = conn.cursor()
like = f"%{query}%"
print("=== KnowledgeOS Search ===")
print(f"Query: {query}\n")
sections = [
    ("Direct Title Matches", "SELECT title, path, type, status FROM notes WHERE title LIKE ? ORDER BY type, title", (like,)),
    ("Tag Matches", "SELECT title, path, tags FROM notes WHERE tags LIKE ? ORDER BY title", (like,)),
    ("Project Matches", "SELECT title, path, project FROM notes WHERE project LIKE ? ORDER BY title", (like,)),
    ("Linked Notes", """
        SELECT DISTINCT n.title, n.path, n.type, n.status
        FROM notes n JOIN links l ON n.path = l.destination
        WHERE l.source IN (SELECT path FROM notes WHERE title LIKE ? OR tags LIKE ? OR project LIKE ?)
        ORDER BY n.type, n.title LIMIT 30
    """, (like, like, like)),
    ("Recent Related Activity", "SELECT title, path, updated FROM notes WHERE (title LIKE ? OR tags LIKE ? OR project LIKE ?) AND updated != '' ORDER BY updated DESC LIMIT 10", (like, like, like)),
]
for title, sql, params in sections:
    print(f"--- {title} ---")
    rows = cur.execute(sql, params).fetchall()
    if rows:
        for row in rows:
            print(" | ".join(str(x) for x in row))
    else:
        print("(none)")
    print()
