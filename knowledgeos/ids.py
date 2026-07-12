"""Stable KnowledgeOS entity ID helpers (`kos:<type>:<slug>`)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from knowledgeos.parser import parse_frontmatter, split_frontmatter
from knowledgeos.schema import ID_PATTERN, NOTE_TYPES_V03

ID_RE = re.compile(ID_PATTERN)
SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(title: str, max_len: int = 48) -> str:
    raw = (title or "").strip().lower()
    slug = SLUG_RE.sub("-", raw).strip("-")
    if not slug:
        slug = "untitled"
    return slug[:max_len].rstrip("-")


def make_id(note_type: str, title: str) -> str:
    ntype = (note_type or "concept").strip().lower().replace(" ", "_")
    if ntype not in NOTE_TYPES_V03:
        ntype = "concept"
    return f"kos:{ntype}:{slugify(title)}"


def is_valid_id(value: str) -> bool:
    return bool(ID_RE.match(value or ""))


def _inject_id_into_frontmatter(text: str, entity_id: str) -> str:
    """Insert or replace `id:` in frontmatter; bump schema toward v0.3 if missing/old."""
    fm, body = split_frontmatter(text)
    if not fm and not text.startswith("---"):
        # No frontmatter — wrap minimally is too invasive; skip
        raise ValueError("note has no frontmatter")

    m = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not m:
        raise ValueError("could not locate frontmatter block")

    yaml_block = m.group(1)
    lines = yaml_block.splitlines()
    out_lines: list[str] = []
    saw_id = False
    saw_schema = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("id:"):
            out_lines.append(f"id: {entity_id}")
            saw_id = True
            continue
        if stripped.startswith("schema:"):
            # Keep existing schema unless empty
            val = stripped.split(":", 1)[1].strip()
            if not val or val == "knowledgeos-v0.2":
                # Additive IDs are valid on v0.2 notes; leave schema unless user opts in.
                out_lines.append(line)
            else:
                out_lines.append(line)
            saw_schema = True
            continue
        out_lines.append(line)

    if not saw_id:
        # Place id after type if present, else at top
        inserted = False
        new_lines: list[str] = []
        for line in out_lines:
            new_lines.append(line)
            if not inserted and line.strip().startswith("type:"):
                new_lines.append(f"id: {entity_id}")
                inserted = True
        if not inserted:
            new_lines.insert(0, f"id: {entity_id}")
        out_lines = new_lines

    if not saw_schema:
        out_lines.append("schema: knowledgeos-v0.2")

    new_yaml = "\n".join(out_lines)
    return f"---\n{new_yaml}\n---\n{body}" if body is not None else f"---\n{new_yaml}\n---\n"


def collect_existing_ids(paths: Iterable[Path]) -> dict[str, str]:
    """Map entity id → relative path string for collision detection."""
    found: dict[str, str] = {}
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        eid = fm.get("id")
        if eid:
            found[str(eid)] = str(path)
    return found


def assign_ids_for_vault(
    vault_root: Path,
    *,
    write: bool = False,
    only_missing: bool = True,
) -> list[dict]:
    """Assign kos IDs to notes. Returns change records. Dry-run unless write=True."""
    skip = {".git", "node_modules", "__pycache__", "Templates", "Archive"}
    md_files = [
        p
        for p in vault_root.rglob("*.md")
        if not any(part in skip for part in p.parts)
        and not (p.name.lower() == "readme.md" and p.parent == vault_root)
    ]

    existing = collect_existing_ids(md_files)
    used = set(existing.keys())
    changes: list[dict] = []

    for path in sorted(md_files):
        rel = path.relative_to(vault_root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        if not fm:
            continue

        current = fm.get("id")
        if current and only_missing:
            continue
        if current and is_valid_id(str(current)) and not only_missing:
            # keep unless forced regenerate — skip for safety
            continue

        title = str(fm.get("title") or path.stem)
        note_type = str(fm.get("type") or "concept")
        candidate = make_id(note_type, title)
        base = candidate
        n = 2
        while candidate in used and existing.get(candidate) != str(path):
            candidate = f"{base}-{n}"
            n += 1

        used.add(candidate)
        existing[candidate] = str(path)
        record = {
            "path": rel,
            "old_id": current or "",
            "new_id": candidate,
            "written": False,
        }
        if write:
            new_text = _inject_id_into_frontmatter(text, candidate)
            path.write_text(new_text, encoding="utf-8")
            record["written"] = True
        changes.append(record)

    return changes
