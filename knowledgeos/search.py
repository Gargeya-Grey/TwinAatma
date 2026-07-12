"""Blended metadata + FTS5 search for KnowledgeOS."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any


def _fts_query(raw: str) -> str:
    """Build a safe FTS5 query from user text (AND of quoted tokens)."""
    tokens = re.findall(r"[A-Za-z0-9_]+", raw)
    if not tokens:
        return '""'
    # Quote each token to reduce syntax errors; AND them
    return " AND ".join(f'"{t}"' for t in tokens[:12])


def blended_search(db_path: Path, query: str, limit: int = 20) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"error": "query required"}
    if not db_path.exists():
        return {"error": f"index missing: {db_path}"}

    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    like = f"%{query}%"
    results: dict[str, Any] = {"query": query, "mode": "metadata+fts5"}

    meta_sections = {
        "title": "SELECT title, path, type, status, entity_id, 3 AS score FROM notes WHERE title LIKE ? ORDER BY updated DESC LIMIT ?",
        "tags": "SELECT title, path, tags, type, entity_id, 2 AS score FROM notes WHERE tags LIKE ? ORDER BY title LIMIT ?",
        "project": "SELECT title, path, project, type, entity_id, 2 AS score FROM notes WHERE project LIKE ? ORDER BY title LIMIT ?",
        "description": "SELECT title, path, type, description, entity_id, 2 AS score FROM notes WHERE description LIKE ? ORDER BY updated DESC LIMIT ?",
    }
    for name, sql in meta_sections.items():
        results[name] = [dict(r) for r in conn.execute(sql, (like, limit)).fetchall()]

    fts_hits: list[dict[str, Any]] = []
    fts_available = True
    try:
        conn.execute("SELECT 1 FROM notes_fts LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        fts_available = False

    if fts_available:
        fts_q = _fts_query(query)
        try:
            rows = conn.execute(
                """
                SELECT path, title,
                       snippet(notes_fts, 2, '«', '»', '…', 16) AS snippet,
                       bm25(notes_fts) AS rank
                FROM notes_fts
                WHERE notes_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_q, limit),
            ).fetchall()
            for r in rows:
                meta = conn.execute(
                    "SELECT type, status, entity_id FROM notes WHERE path = ?",
                    (r["path"],),
                ).fetchone()
                fts_hits.append(
                    {
                        "title": r["title"],
                        "path": r["path"],
                        "snippet": r["snippet"],
                        "rank": r["rank"],
                        "type": (meta["type"] if meta else ""),
                        "status": (meta["status"] if meta else ""),
                        "entity_id": (meta["entity_id"] if meta else ""),
                        "score": 4,
                    }
                )
        except sqlite3.OperationalError as e:
            results["fts_error"] = str(e)

    results["fts"] = fts_hits
    results["fts_available"] = fts_available

    # Ranked blend: path -> best score
    blended: dict[str, dict[str, Any]] = {}
    for bucket in ("fts", "title", "tags", "project", "description"):
        for row in results.get(bucket) or []:
            path = row.get("path")
            if not path:
                continue
            score = int(row.get("score") or 1)
            prev = blended.get(path)
            if not prev or score > prev.get("score", 0):
                blended[path] = {
                    "title": row.get("title"),
                    "path": path,
                    "type": row.get("type", ""),
                    "status": row.get("status", ""),
                    "entity_id": row.get("entity_id", ""),
                    "snippet": row.get("snippet") or row.get("description") or "",
                    "score": score,
                    "source": bucket,
                }
    ranked = sorted(blended.values(), key=lambda x: (-x["score"], x.get("title") or ""))
    results["ranked"] = ranked[:limit]
    conn.close()
    return results
