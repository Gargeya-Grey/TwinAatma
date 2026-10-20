"""Blended metadata + FTS5 search for KnowledgeOS."""
from __future__ import annotations

import sqlite3
import unicodedata
from pathlib import Path
from typing import Any

from knowledgeos.database import connect_database

_QUESTION_STARTS = {"what", "which", "who", "where", "when", "why", "how", "help", "remind", "please", "can", "could", "would"}
_QUESTION_STOP_WORDS = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "with", "about", "from",
    "i", "me", "my", "we", "our", "you", "your", "it", "this", "that", "do", "does", "did",
    "is", "are", "was", "were", "be", "have", "has", "had", "can", "could", "would", "should",
    "what", "which", "who", "where", "when", "why", "how", "help", "remind", "please", "tell",
    "choose", "find", "remember", "know", "need", "want", "prefer", "preferred",
}


def _tokens(raw: str) -> list[str]:
    """Letters/marks/digits of any script, so "café" and "नमस्ते" stay whole.

    ``\\w`` alone drops combining marks (Devanagari virama, vowel signs), which
    split a single word into fragments that no longer match the index.
    """
    out: list[str] = []
    buf: list[str] = []
    for ch in raw or "":
        category = unicodedata.category(ch)
        if category[0] in {"L", "M", "N"} or ch == "_":
            buf.append(ch)
        elif buf:
            out.append("".join(buf))
            buf = []
    if buf:
        out.append("".join(buf))
    return out


def _fts_query(raw: str) -> str:
    """Build a safe AND query, removing conversational scaffolding from questions.

    Uses Unicode letter/number categories so accented and non-Latin scripts
    survive; ASCII-only tokenising silently returned nothing for "café".
    """
    tokens = _tokens(raw)
    if len(tokens) >= 4 and tokens[0].lower() in _QUESTION_STARTS:
        tokens = [token for token in tokens if token.lower() not in _QUESTION_STOP_WORDS]
    if not tokens:
        return '""'
    cleaned = [t.replace('"', "") for t in tokens if t.replace('"', "")]
    if not cleaned:
        return '""'
    return " AND ".join(f'"{t}"' for t in cleaned[:12])


def _context_query(raw: str) -> str:
    """Find candidate memories for a task, rather than require its every word."""
    scaffolding = _QUESTION_STOP_WORDS | {
        "s", "am", "as", "but", "by", "if", "then", "than", "into", "up", "out",
        "its", "there", "some", "any", "all", "more", "most", "very", "only",
        "each", "such", "these", "those", "their", "them", "also", "just", "so",
    }
    terms = dict.fromkeys(token.lower() for token in _tokens(raw)
                          if token.lower() not in scaffolding)
    return " OR ".join(f'"{term}"' for term in list(terms)[:24]) or '""'


def _like(raw: str) -> str:
    """Escape LIKE wildcards so a literal '%' searches for '%'."""
    escaped = raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _needs_substring_fallback(query: str) -> bool:
    """True when FTS tokenising is unlikely to represent this query faithfully.

    ``unicode61`` splits CJK into per-character tokens and drops emoji entirely,
    so a two-character CJK query becomes an AND of single characters that does not
    behave like a word search. A substring scan is the honest answer there.
    """
    for ch in query:
        code = ord(ch)
        if 0x3040 <= code <= 0x30FF:  # kana
            return True
        if 0x3400 <= code <= 0x9FFF:  # CJK
            return True
        if 0xAC00 <= code <= 0xD7AF:  # hangul
            return True
        if 0xF900 <= code <= 0xFAFF:
            return True
        if 0x1F000 <= code <= 0x1FAFF:  # emoji
            return True
    return False


def blended_search(db_path: Path, query: str, limit: int = 20, *, context: bool = False) -> dict[str, Any]:
    from knowledgeos.remembering import RememberingPolicy, PolicyError, refusal
    from knowledgeos.database import checked_database_path

    db_path = checked_database_path(db_path)
    try:
        RememberingPolicy(db_path.parent).require_text(query)
    except PolicyError as error:
        return refusal(error)
    query = (query or "").strip()
    if not query:
        return {"error": "query required"}
    if not db_path.exists():
        return {"error": f"index missing: {db_path}"}

    limit = max(1, min(int(limit or 20), 200))
    # Short busy timeout on purpose. A search that hangs for thirty seconds behind
    # another process's write is worse than one that says "busy": the caller is an agent
    # answering a question mid-conversation, and a 30s stall reads as a broken product.
    # The caller can retry, and a stale row is filtered out against the filesystem.
    conn = connect_database(db_path, timeout=2.0)
    conn.row_factory = sqlite3.Row
    like = _like(query)
    results: dict[str, Any] = {"query": query, "mode": "metadata+fts5"}

    meta_sections = {
        "title": (
            "SELECT title, path, type, status, entity_id, 3 AS score FROM notes "
            "WHERE title LIKE ? ESCAPE '\\' ORDER BY updated DESC LIMIT ?"
        ),
        "tags": (
            "SELECT title, path, tags, type, entity_id, 2 AS score FROM notes "
            "WHERE tags LIKE ? ESCAPE '\\' ORDER BY title LIMIT ?"
        ),
        "project": (
            "SELECT title, path, project, type, entity_id, 2 AS score FROM notes "
            "WHERE project LIKE ? ESCAPE '\\' ORDER BY title LIMIT ?"
        ),
        "description": (
            "SELECT title, path, type, description, entity_id, 2 AS score FROM notes "
            "WHERE description LIKE ? ESCAPE '\\' ORDER BY updated DESC LIMIT ?"
        ),
    }
    for name, sql in meta_sections.items():
        try:
            results[name] = [dict(r) for r in conn.execute(sql, (like, limit)).fetchall()]
        except sqlite3.OperationalError:
            results[name] = []

    if context:
        results["mode"] = "task-context"
    fts_hits: list[dict[str, Any]] = []
    fts_available = True
    try:
        conn.execute("SELECT rowid FROM notes_fts WHERE notes_fts MATCH ? LIMIT 1", ("schema_probe",)).fetchone()
    except sqlite3.OperationalError as exc:
        fts_available = False
        results["fts_error"] = str(exc)

    if fts_available:
        fts_q = _context_query(query) if context else _fts_query(query)
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

    # Scripts FTS cannot tokenise (CJK, emoji) fall back to a substring scan of the
    # indexed body. Only on demand: it is a full scan, and only a miss pays for it.
    if not fts_hits and _needs_substring_fallback(query):
        try:
            rows = conn.execute(
                """
                SELECT f.path, f.title,
                       substr(f.body, max(1, instr(f.body, ?) - 60), 160) AS snippet
                FROM notes_fts f
                WHERE f.body LIKE ? ESCAPE '\\' OR f.title LIKE ? ESCAPE '\\'
                LIMIT ?
                """,
                (query, _like(query), _like(query), limit),
            ).fetchall()
            for r in rows:
                fts_hits.append(
                    {
                        "title": r["title"],
                        "path": r["path"],
                        "snippet": r["snippet"],
                        "rank": 0.0,
                        "type": "",
                        "status": "",
                        "entity_id": "",
                        "score": 3,
                        "match": "substring",
                    }
                )
            results["substring_fallback"] = True
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
                    "snippet": (row.get("snippet") or row.get("description") or "")[:400],
                    "score": score,
                    "source": bucket,
                    "rank": row.get("rank", 0.0),
                }
    ranked = sorted(blended.values(), key=lambda x: (-x["score"], x["rank"], x.get("title") or "", x["path"]))
    results["ranked"] = ranked[:limit]
    conn.close()
    try:
        from knowledgeos.memory import MemoryAPI

        api = MemoryAPI(db_path.parent)
        for key, rows in list(results.items()):
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                results[key] = api._refresh_rows(rows, query, context=context)
        return RememberingPolicy(db_path.parent).release(results)
    except PolicyError as error:
        return refusal(error)
