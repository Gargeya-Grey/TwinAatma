#!/usr/bin/env python
"""KnowledgeOS Link Refactoring Utility.

Scans the vault for broken internal Markdown and wikilinks. Resolves them
against known file stems from the SQLite index and automatically updates
links in raw Markdown files to prevent link rot.
"""
from __future__ import annotations
import os, re, sqlite3, sys
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
DB = VAULT_DIR / "knowledge_index.db"
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

def build_lookup_table(md_files):
    lookup = {}
    for path in md_files:
        rel = path.relative_to(VAULT_DIR).as_posix()
        stem = path.stem.lower()
        lookup[stem] = rel
        lookup[rel.lower()] = rel
    return lookup

def get_relative_path(source_rel: str, dest_rel: str) -> str:
    source_path = Path(source_rel)
    try:
        rel = os.path.relpath(dest_rel, start=str(source_path.parent)).replace("\\", "/")
        return rel
    except Exception:
        return dest_rel

def main():
    if not DB.exists():
        print(f"Error: Database index not found at {DB}. Please run 'python scripts/rebuild_index.py' first.", file=sys.stderr)
        sys.exit(1)

    print("=== KnowledgeOS Link Refactoring Utility ===")
    print(f"Vault: {VAULT_DIR}")

    md_files = [p for p in VAULT_DIR.rglob("*.md") if ".git" not in p.parts and "node_modules" not in p.parts]
    lookup = build_lookup_table(md_files)

    changes_count = 0
    files_modified = 0

    for path in md_files:
        rel_source = path.relative_to(VAULT_DIR).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        modified = False

        # 1. Process standard Markdown links: [text](path.md)
        def md_replacer(match):
            nonlocal modified, changes_count
            link_text = match.group(1)
            raw_dest = match.group(2)

            if raw_dest.startswith(("http://", "https://", "mailto:", "ftp:", "#")):
                return match.group(0)

            source_dir = path.parent
            dest_candidate = (source_dir / raw_dest).resolve()
            if dest_candidate.exists() and dest_candidate.is_file():
                return match.group(0)

            clean_dest = raw_dest.split("#", 1)[0].split("?", 1)[0].replace("\\", "/")
            dest_stem = Path(clean_dest).stem.lower()

            hit = lookup.get(dest_stem) or lookup.get(clean_dest.lower())
            if hit:
                new_rel = get_relative_path(rel_source, hit)
                if "#" in raw_dest:
                    new_rel += "#" + raw_dest.split("#", 1)[1]
                if new_rel != raw_dest:
                    print(f"[REFACTORED] {rel_source}: [{link_text}]({raw_dest}) -> ({new_rel})")
                    changes_count += 1
                    modified = True
                    return f"[{link_text}]({new_rel})"
            return match.group(0)

        new_text = MARKDOWN_LINK_RE.sub(md_replacer, text)

        # 2. Process Wikilinks: [[link_name]] (migrates them to Markdown standard)
        def wiki_replacer(match):
            nonlocal modified, changes_count
            raw_target = match.group(1)
            clean_target = raw_target.split("|", 1)[0].split("#", 1)[0].strip()
            display_text = raw_target.split("|", 1)[1].strip() if "|" in raw_target else clean_target
            dest_stem = Path(clean_target).stem.lower()

            hit = lookup.get(dest_stem) or lookup.get(clean_target.lower())
            if hit:
                new_rel = get_relative_path(rel_source, hit)
                if "#" in raw_target:
                    new_rel += "#" + raw_target.split("#", 1)[1]
                print(f"[MIGRATED WIKILINK] {rel_source}: [[{raw_target}]] -> [{display_text}]({new_rel})")
                changes_count += 1
                modified = True
                return f"[{display_text}]({new_rel})"
            return match.group(0)

        new_text = WIKILINK_RE.sub(wiki_replacer, new_text)

        if modified:
            path.write_text(new_text, encoding="utf-8")
            files_modified += 1

    print("\n--- Summary ---")
    print(f"Files Modified: {files_modified}")
    print(f"Links Refactored/Migrated: {changes_count}")
    print("Done.")

if __name__ == "__main__":
    main()
