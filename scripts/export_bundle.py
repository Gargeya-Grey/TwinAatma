#!/usr/bin/env python
"""Export a portable KnowledgeOS markdown bundle.

Examples:
  python scripts/export_bundle.py --project Example --out exports/example-bundle
  python scripts/export_bundle.py --paths Projects Research/example-concept.md --out exports/custom
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
if str(VAULT_DIR) not in sys.path:
    sys.path.insert(0, str(VAULT_DIR))

from knowledgeos.parser import parse_frontmatter  # noqa: E402
from knowledgeos.schema import SCHEMA_V02  # noqa: E402


def note_title(path: Path, text: str, fm: dict) -> str:
    if fm.get("title"):
        return fm["title"]
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def all_notes():
    for path in VAULT_DIR.rglob("*.md"):
        if ".git" in path.parts or "node_modules" in path.parts:
            continue
        yield path


def _tags_blob(tags) -> str:
    if isinstance(tags, list):
        return " ".join(str(t).lower() for t in tags)
    return str(tags or "").lower()


def select_notes(project: str | None, paths: list[str]):
    selected = set()
    if project:
        for p in all_notes():
            text = p.read_text(encoding="utf-8", errors="replace")
            fm = parse_frontmatter(text)
            proj = str(fm.get("project") or "").lower()
            if proj == project.lower() or project.lower() in _tags_blob(fm.get("tags")):
                selected.add(p)
    for item in paths:
        try:
            p = (VAULT_DIR / item).resolve()
            p.relative_to(VAULT_DIR)
            if p.is_dir():
                for md in p.rglob("*.md"):
                    selected.add(md)
            elif p.exists() and p.suffix.lower() == ".md":
                selected.add(p)
        except (ValueError, FileNotFoundError):
            print(f"[WARNING] Skipping invalid or traversal path: {item}", file=sys.stderr)
            continue
    return sorted(selected)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="Export notes whose frontmatter project matches this value")
    ap.add_argument("--paths", nargs="*", default=[], help="Additional vault-relative files/folders to include")
    ap.add_argument("--out", required=True, help="Output folder")
    args = ap.parse_args()

    if not args.project and not args.paths:
        ap.error("Provide --project and/or --paths")

    out = (VAULT_DIR / args.out).resolve()
    if out == VAULT_DIR or out in VAULT_DIR.parents or not str(out).startswith(str(VAULT_DIR)):
        print(
            "[ERROR] Destructive export target path: output folder cannot be the vault root, "
            "system folders, or outside the vault workspace.",
            file=sys.stderr,
        )
        sys.exit(1)

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "format": "KnowledgeOS portable markdown bundle",
        "schema": SCHEMA_V02,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_vault": str(VAULT_DIR),
        "selector": {"project": args.project, "paths": args.paths},
        "notes": [],
    }

    for src in select_notes(args.project, args.paths):
        rel = src.relative_to(VAULT_DIR)
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        text = src.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        manifest["notes"].append(
            {
                "path": rel.as_posix(),
                "title": note_title(src, text, fm),
                "type": fm.get("type", ""),
                "status": fm.get("status", ""),
                "description": fm.get("description", ""),
                "resource": fm.get("resource", ""),
                "tags": fm.get("tags", ""),
                "project": fm.get("project", ""),
                "id": fm.get("id", ""),
            }
        )

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Exported {len(manifest['notes'])} notes to {out}")
    print(f"Manifest: {out / 'manifest.json'}")


if __name__ == "__main__":
    main()
