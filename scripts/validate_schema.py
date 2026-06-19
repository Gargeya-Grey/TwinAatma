#!/usr/bin/env python
"""Validate KnowledgeOS notes against the portable metadata schema.

This is intentionally lightweight: no external YAML dependency, no Obsidian
plugin requirement. It checks the markdown/frontmatter contract that makes the
vault portable and agent-readable.
"""
from __future__ import annotations
import json
import re
import urllib.parse
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(((?:[^()]+|\([^()]*\))+)\)")

REQUIRED = ["type", "title", "description", "status", "schema", "created", "updated", "tags"]
RECOMMENDED_FOR_SOURCE = ["resource", "timestamp", "source_type"]
SKIP_DIRS = {".git", "node_modules", "Archive"}


def parse_frontmatter(text: str) -> dict:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    data = {}
    for raw in m.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def is_template(path: Path) -> bool:
    return "Templates" in path.parts


def is_index_or_moc(fm: dict) -> bool:
    return fm.get("type") in {"index", "moc"}


def main() -> int:
    notes = []
    warnings = []
    errors = []
    for path in VAULT_DIR.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name.lower() == "readme.md" and path.parent == VAULT_DIR:
            continue
        rel = path.relative_to(VAULT_DIR).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        
        links = []
        for raw in WIKILINK_RE.findall(text):
            links.append(raw)
        for raw in MARKDOWN_LINK_RE.findall(text):
            if not raw.startswith(("http://", "https://", "mailto:", "ftp:", "#")):
                links.append(urllib.parse.unquote(raw))
                
        if not fm:
            errors.append({"path": rel, "issue": "missing_frontmatter"})
            continue
        missing = [k for k in REQUIRED if not fm.get(k)]
        # Templates are allowed to have blank description/resource placeholders, but should carry the keys.
        if is_template(path):
            missing = [k for k in missing if k not in {"description"}]
        if missing:
            errors.append({"path": rel, "issue": "missing_required_fields", "fields": missing})
        if not links and not is_index_or_moc(fm) and not is_template(path):
            warnings.append({"path": rel, "issue": "no_links"})
        sourceish = bool(fm.get("source_type") or fm.get("resource"))
        if sourceish and not is_template(path):
            missing_source = [k for k in RECOMMENDED_FOR_SOURCE if not fm.get(k)]
            if missing_source:
                warnings.append({"path": rel, "issue": "missing_source_provenance", "fields": missing_source})
        notes.append(rel)

    result = {
        "schema": "knowledgeos-v0.2",
        "notes_checked": len(notes),
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
        },
    }
    print(json.dumps(result, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
