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
from knowledgeos.data_ops import plain_vault_path  # noqa: E402
from knowledgeos.indexer import iter_markdown  # noqa: E402
from knowledgeos.remembering import RememberingPolicy, PolicyError  # noqa: E402


def note_title(path: Path, text: str, fm: dict) -> str:
    if fm.get("title"):
        return fm["title"]
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def all_notes():
    for path in iter_markdown(VAULT_DIR):
        yield plain_vault_path(VAULT_DIR, path)


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
            p = plain_vault_path(VAULT_DIR, VAULT_DIR / item)
            if p.is_dir():
                for md in p.rglob("*.md"):
                    selected.add(plain_vault_path(VAULT_DIR, md))
            elif p.exists() and p.suffix.lower() == ".md":
                selected.add(p)
        except (ValueError, FileNotFoundError) as error:
            raise ValueError(f"Invalid export source: {item}: {error}") from error
    return sorted(selected)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="Export notes whose frontmatter project matches this value")
    ap.add_argument("--paths", nargs="*", default=[], help="Additional vault-relative files/folders to include")
    ap.add_argument("--out", required=True, help="Output folder")
    args = ap.parse_args()

    if not args.project and not args.paths:
        ap.error("Provide --project and/or --paths")

    try:
        with RememberingPolicy(VAULT_DIR).lock() as policy:
            return export(args, policy)
    except (OSError, PolicyError):
        print("[ERROR] Export could not apply the remembering policy safely.", file=sys.stderr)
        return 1


def export(args, policy):
    try:
        policy.release({"project": args.project, "paths": args.paths, "out": args.out})
        out = plain_vault_path(VAULT_DIR, VAULT_DIR / args.out)
        if out == VAULT_DIR or out.exists():
            raise ValueError("Export output must be a fresh directory beneath the vault")
        for item in args.paths:
            source = plain_vault_path(VAULT_DIR, VAULT_DIR / item)
            if out == source or source in out.parents or out in source.parents:
                raise ValueError(f"Export output overlaps selected source: {item}")
        selected = [plain_vault_path(VAULT_DIR, p) for p in select_notes(args.project, args.paths)]
        if any(out == source or out in source.parents for source in selected):
            raise ValueError("Export output overlaps selected notes")
        permitted = []
        for source in selected:
            text = policy.read(source)
            if text is not None:
                permitted.append((source, text))
    except (OSError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=False)

    manifest = {
        "format": "KnowledgeOS portable markdown bundle",
        "schema": SCHEMA_V02,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_vault": str(VAULT_DIR),
        "selector": {"project": args.project, "paths": args.paths},
        "dependency_policy": "Selected Markdown notes only; linked notes and attachments are not automatically included.",
        "remembering_policy": "Excluded notes are omitted. Historical sources retain explicit attribution in this manifest.",
        "excluded_count": len(selected) - len(permitted),
        "notes": [],
    }

    for src, text in permitted:
        rel = src.relative_to(VAULT_DIR)
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(text.encode("utf-8"))
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
                **policy.attribution(src),
            }
        )

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Exported {len(manifest['notes'])} notes to {out}")
    print(f"Manifest: {out / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
