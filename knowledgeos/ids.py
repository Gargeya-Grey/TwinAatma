"""Stable KnowledgeOS entity ID helpers (`kos:<type>:<slug>`)."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from knowledgeos.parser import FRONTMATTER_RE, parse_frontmatter
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
    """Edit top-level metadata without reconstructing the delimiter or body."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("could not locate frontmatter block")

    yaml_block = m.group(1)
    lines = yaml_block.splitlines()
    out_lines: list[str] = []
    saw_id = False
    saw_schema = False
    for line in lines:
        if re.match(r"^id\s*:", line, re.I):
            out_lines.append(f"id: {entity_id}")
            saw_id = True
            continue
        if re.match(r"^schema\s*:", line, re.I):
            # IDs are additive on v0.2; retain declared versions.
            val = line.split(":", 1)[1].strip()
            out_lines.append(line if val else "schema: knowledgeos-v0.2")
            saw_schema = True
            continue
        out_lines.append(line)

    if not saw_id:
        # Place id after type if present, else at top
        inserted = False
        new_lines: list[str] = []
        for line in out_lines:
            new_lines.append(line)
            if not inserted and re.match(r"^type\s*:", line, re.I):
                new_lines.append(f"id: {entity_id}")
                inserted = True
        if not inserted:
            new_lines.insert(0, f"id: {entity_id}")
        out_lines = new_lines

    if not saw_schema:
        out_lines.append("schema: knowledgeos-v0.2")

    new_yaml = "\n".join(out_lines)
    return text[:m.start(1)] + new_yaml + text[m.end(1):]


def collect_existing_ids(paths: Iterable[Path]) -> dict[str, str]:
    """Map entity id → relative path string for collision detection."""
    found: dict[str, str] = {}
    for path in paths:
        text = path.read_bytes().decode("utf-8")
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
    """Assign kos IDs to notes. Returns change records. Dry-run unless write=True.

    ``People/Self.md`` and proposals are never touched: identity changes go through
    the Self gate only, so no other command may rewrite that file.
    """
    vault_root = Path(os.path.abspath(vault_root))
    skip = {
        ".git",
        ".knowledgeos",
        ".trash",
        "node_modules",
        "__pycache__",
        "Templates",
        "Archive",
        "People",
    }
    # `rglob` follows directory junctions, so a junction inside the vault pointing
    # elsewhere made `ids assign --write` rewrite files *outside* the vault — the one
    # promise the tool surface makes. `iter_markdown` already walks without following
    # links and confirms every file resolves inside the vault; use it, then keep the
    # older filters on top.
    from knowledgeos.indexer import iter_markdown

    all_files = iter_markdown(vault_root)
    skipped = {name.casefold() for name in skip}
    md_files = [
        p
        for p in all_files
        if not any(part.casefold() in skipped for part in p.relative_to(vault_root).parts)
        and not (p.name.lower() == "readme.md" and p.parent == vault_root)
    ]

    # Protected notes reserve their IDs even though they are never write targets.
    existing = collect_existing_ids(all_files)
    used = set(existing.keys())
    changes: list[dict] = []

    for path in sorted(md_files):
        if write:
            from knowledgeos.data_ops import plain_vault_path
            plain_vault_path(vault_root, path)
        rel = path.relative_to(vault_root).as_posix()
        text = path.read_bytes().decode("utf-8")
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
            from knowledgeos.textio import write_preserving_endings

            plain_vault_path(vault_root, path)
            write_preserving_endings(path, new_text)
            record["written"] = True
        changes.append(record)

    return changes
