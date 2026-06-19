#!/usr/bin/env python
"""Rebuild KnowledgeOS SQLite index without requiring sqlite3 CLI.

Indexes markdown notes, frontmatter, and wiki links. Link targets are stored in raw
form and normalized to best-effort vault-relative markdown paths when possible.
"""
from __future__ import annotations
import hashlib, os, re, sqlite3, sys, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
DB = VAULT_DIR / "knowledge_index.db"
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(((?:[^()]+|\([^()]*\))+)\)")

def parse_frontmatter(text: str) -> dict:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    data = {}
    lines = m.group(1).splitlines()
    current_key = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("-") and current_key:
            val = stripped[1:].strip().strip('"').strip("'")
            if current_key in data:
                if isinstance(data[current_key], list):
                    data[current_key].append(val)
                elif data[current_key] == "":
                    data[current_key] = [val]
                else:
                    data[current_key] = [data[current_key], val]
            else:
                data[current_key] = [val]
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip().lower()
            v = v.strip().strip('"').strip("'")
            if v.startswith("[") and v.endswith("]"):
                v = [item.strip().strip('"').strip("'") for item in v[1:-1].split(",") if item.strip()]
            data[k] = v
            current_key = k
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
    target = urllib.parse.unquote(raw.split("|", 1)[0].split("#", 1)[0].strip())
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

def process_file_worker(args):
    path, db_notes, lookup = args
    try:
        rel = path.relative_to(VAULT_DIR).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        file_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        
        # Cache hit check
        if rel in db_notes and db_notes[rel] == file_hash:
            return (rel, file_hash, True, None)
            
        # Parse note data
        fm = parse_frontmatter(text)
        title = title_from_note(path, text, fm)
        typ = fm.get("type") or "concept"
        status = fm.get("status") or "draft"
        tags = fm.get("tags") or ""
        if isinstance(tags, list):
            tags = ", ".join(tags)
        project = fm.get("project") or ""
        if isinstance(project, list):
            project = ", ".join(project)
        created = fm.get("created") or ""
        updated = fm.get("updated") or ""
        description = fm.get("description") or ""
        resource = fm.get("resource") or ""
        timestamp = fm.get("timestamp") or ""
        schema = fm.get("schema") or ""
        
        raw_links = []
        for raw in WIKILINK_RE.findall(text):
            raw_links.append(raw)
        for raw in MARKDOWN_LINK_RE.findall(text):
            if not raw.startswith(("http://", "https://", "mailto:", "ftp:", "#")):
                raw_links.append(raw)
                
        resolved_links = []
        for raw in sorted(set(raw_links)):
            dest = normalize_link(raw, rel, lookup)
            resolved_links.append((dest, raw))
            
        note_data = (title, rel, typ, tags, project, status, created, updated, description, resource, timestamp, schema, file_hash)
        return (rel, file_hash, False, (note_data, resolved_links))
    except Exception as e:
        return (str(path), "", False, e)

def main():
    md_files = [p for p in VAULT_DIR.rglob("*.md") if ".git" not in p.parts and "node_modules" not in p.parts]
    lookup = build_note_lookup(md_files)
    conn = sqlite3.connect(DB, timeout=30.0)
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
      schema TEXT,
      file_hash TEXT
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
    if "file_hash" not in note_cols:
        cur.execute("ALTER TABLE notes ADD COLUMN file_hash TEXT")

    # Load existing notes to perform incremental updates
    db_notes = {r[0]: r[1] for r in cur.execute("SELECT path, file_hash FROM notes").fetchall()}
    current_paths = {p.relative_to(VAULT_DIR).as_posix() for p in md_files}

    # Delete removed files from DB
    for path in list(db_notes.keys()):
        if path not in current_paths:
            cur.execute("DELETE FROM notes WHERE path = ?", (path,))
            cur.execute("DELETE FROM links WHERE source = ?", (path,))

    note_count = link_count = 0
    
    # Process files concurrently using a ThreadPoolExecutor
    worker_args = [(p, db_notes, lookup) for p in md_files]
    with ThreadPoolExecutor() as executor:
        results = list(executor.map(process_file_worker, worker_args))

    for rel, file_hash, is_cached, payload in results:
        if isinstance(payload, Exception):
            print(f"Error processing {rel}: {payload}", file=sys.stderr)
            continue
            
        if is_cached:
            note_count += 1
            existing_links = cur.execute("SELECT raw_destination, id FROM links WHERE source = ?", (rel,)).fetchall()
            for raw, link_id in existing_links:
                dest = normalize_link(raw, rel, lookup)
                cur.execute("UPDATE links SET destination = ? WHERE id = ?", (dest, link_id))
                link_count += 1
        else:
            note_data, resolved_links = payload
            cur.execute("DELETE FROM links WHERE source = ?", (rel,))
            cur.execute("""INSERT OR REPLACE INTO notes
              (title, path, type, tags, project, status, created, updated, description, resource, timestamp, schema, file_hash)
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", note_data)
            note_count += 1
            for dest, raw in resolved_links:
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
