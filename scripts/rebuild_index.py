#!/usr/bin/env python
"""Rebuild KnowledgeOS SQLite index without requiring sqlite3 CLI.

Indexes markdown notes, frontmatter, and wiki links. Link targets are stored in raw
form and normalized to best-effort vault-relative markdown paths when possible.
"""
from __future__ import annotations
import os, re, sqlite3, sys
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
DB = VAULT_DIR / "knowledge_index.db"
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

def parse_frontmatter(text: str) -> dict:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    data = {}
    for raw in m.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        val = val.strip().strip('"').strip("'")
        data[key.strip().lower()] = val
    return data

def title_from_note(path: Path, text: str, fm: dict) -> str:
    if fm.get("title"):
        return fm["title"]
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem

def build_note_lookup(md_files):
    lookup = {}
    for path in md_files:
        rel = path.relative_to(VAULT_DIR).as_posix()
        stem = path.stem
        lookup[rel.lower()] = rel
        lookup[rel[:-3].lower()] = rel
        lookup[stem.lower()] = rel
        # Also allow folder/name without .md and aliases based on headings later if needed.
    return lookup

def normalize_link(raw: str, source_rel: str, lookup: dict) -> str:
    target = raw.split("|", 1)[0].split("#", 1)[0].strip()
    if not target:
        return raw.strip()
    target = target.replace("\\", "/")
    source_dir = str(Path(source_rel).parent).replace("\\", "/")
    candidates = []
    if target.endswith(".md"):
        candidates.append(target)
    else:
        candidates.extend([target, target + ".md"])
    if source_dir and source_dir != ".":
        candidates.extend([f"{source_dir}/{c}" for c in list(candidates)])
    for c in candidates:
        norm = os.path.normpath(c).replace("\\", "/")
        hit = lookup.get(norm.lower()) or lookup.get(norm[:-3].lower() if norm.endswith('.md') else norm.lower())
        if hit:
            return hit
    return target

def main():
    md_files = [p for p in VAULT_DIR.rglob("*.md") if ".git" not in p.parts and "node_modules" not in p.parts]
    lookup = build_note_lookup(md_files)
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS notes (
      id INTEGER PRIMARY KEY,
      title TEXT NOT NULL,
      path TEXT UNIQUE NOT NULL,
      type TEXT NOT NULL DEFAULT 'concept',
      tags TEXT,
      project TEXT,
      status TEXT NOT NULL DEFAULT 'draft',
      created TEXT,
      updated TEXT,
      description TEXT,
      resource TEXT,
      timestamp TEXT,
      schema TEXT
    );
    CREATE TABLE IF NOT EXISTS links (
      id INTEGER PRIMARY KEY,
      source TEXT NOT NULL,
      destination TEXT NOT NULL,
      raw_destination TEXT,
      FOREIGN KEY (source) REFERENCES notes(path)
    );
    CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
    """)
    # Add columns for old DBs.
    link_cols = [r[1] for r in cur.execute("PRAGMA table_info(links)")]
    if "raw_destination" not in link_cols:
        cur.execute("ALTER TABLE links ADD COLUMN raw_destination TEXT")
    note_cols = [r[1] for r in cur.execute("PRAGMA table_info(notes)")]
    for col in ["description", "resource", "timestamp", "schema"]:
        if col not in note_cols:
            cur.execute(f"ALTER TABLE notes ADD COLUMN {col} TEXT")
    cur.execute("DELETE FROM links")
    cur.execute("DELETE FROM notes")
    note_count = link_count = 0
    for path in md_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        rel = path.relative_to(VAULT_DIR).as_posix()
        title = title_from_note(path, text, fm)
        typ = fm.get("type") or "concept"
        status = fm.get("status") or "draft"
        tags = fm.get("tags") or ""
        project = fm.get("project") or ""
        created = fm.get("created") or ""
        updated = fm.get("updated") or ""
        description = fm.get("description") or ""
        resource = fm.get("resource") or ""
        timestamp = fm.get("timestamp") or ""
        schema = fm.get("schema") or ""
        cur.execute("""INSERT OR REPLACE INTO notes
          (title, path, type, tags, project, status, created, updated, description, resource, timestamp, schema)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
          (title, rel, typ, tags, project, status, created, updated, description, resource, timestamp, schema))
        note_count += 1
        for raw in sorted(set(WIKILINK_RE.findall(text))):
            dest = normalize_link(raw, rel, lookup)
            cur.execute("INSERT INTO links (source, destination, raw_destination) VALUES (?, ?, ?)", (rel, dest, raw))
            link_count += 1
    cur.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES ('last_rebuild_note_count', ?)", (str(note_count),))
    cur.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES ('last_rebuild_link_count', ?)", (str(link_count),))
    conn.commit()
    print("Rebuilding KnowledgeOS index...")
    print(f"Vault: {VAULT_DIR}")
    print(f"DB: {DB}")
    print("Done.")
    print(f"Notes: {note_count}")
    print(f"Links: {link_count}")

if __name__ == "__main__":
    main()
