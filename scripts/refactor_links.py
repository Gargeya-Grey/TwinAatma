#!/usr/bin/env python
"""KnowledgeOS Link Refactoring Utility.

Scans the shared note corpus for broken internal Markdown and wikilinks.
Resolves only unique targets, preserving identity evidence and code examples.
"""
from __future__ import annotations
import os, re, sys
from pathlib import Path
import urllib.parse

VAULT_DIR = Path(__file__).resolve().parent.parent
DB = VAULT_DIR / "knowledge_index.db"
sys.path.insert(0, str(VAULT_DIR))
from knowledgeos.data_ops import plain_vault_path
from knowledgeos.links import LinkTarget, build_note_lookup, link_candidates
from knowledgeos.textio import write_preserving_endings
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

def build_lookup_table(md_files):
    return build_note_lookup(md_files, VAULT_DIR)


def protected_example_spans(text):
    spans = []
    offset = 0
    fence = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            spans.append((offset, offset + len(line)))
            if (marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence)
                    and not line[marker.end():].strip()):
                fence = None
        elif marker:
            fence = marker[1]
            spans.append((offset, offset + len(line)))
        else:
            for match in re.finditer(r"(`+)(.*?)(?<!`)\1(?!`)", line):
                spans.append((offset + match.start(), offset + match.end()))
        offset += len(line)
    return spans

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

    from knowledgeos.indexer import iter_markdown
    md_files = list(iter_markdown(VAULT_DIR))
    lookup = build_lookup_table(md_files)

    changes_count = 0
    files_modified = 0

    for path in md_files:
        rel_source = path.relative_to(VAULT_DIR).as_posix()
        if rel_source.lower() == "people/self.md" or rel_source.lower().startswith("people/self-proposals/"):
            continue
        plain_vault_path(VAULT_DIR, path)
        text = path.read_text(encoding="utf-8")
        modified = False

        def resolve_target(target, markdown=False):
            target = target.replace("\\", "/")
            matches = link_candidates(LinkTarget(target, markdown=markdown), rel_source, lookup)
            if not matches:
                matches = link_candidates(Path(target).stem, rel_source, lookup)
            return matches[0] if len(matches) == 1 else None

        spans = protected_example_spans(text)

        def example(match):
            return any(start <= match.start() < end for start, end in spans)

        # 1. Process standard Markdown links: [text](path.md)
        def md_replacer(match):
            nonlocal modified, changes_count
            link_text = match.group(1)
            raw_dest = match.group(2)

            if example(match):
                return match.group(0)

            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw_dest) or raw_dest.startswith(("#", "//")):
                return match.group(0)

            source_dir = path.parent
            clean_dest = raw_dest.split("#", 1)[0].split("?", 1)[0].replace("\\", "/")
            dest_candidate = (source_dir / urllib.parse.unquote(clean_dest)).resolve()
            if dest_candidate.exists() and dest_candidate.is_file():
                return match.group(0)

            hit = resolve_target(clean_dest, markdown=True)
            if hit:
                new_rel = get_relative_path(rel_source, hit)
                new_rel += raw_dest[len(raw_dest.split("#", 1)[0].split("?", 1)[0]):]
                if new_rel != raw_dest:
                    print(f"[REFACTORED] {rel_source}: [{link_text}]({raw_dest}) -> ({new_rel})")
                    changes_count += 1
                    modified = True
                    return f"[{link_text}]({new_rel})"
            return match.group(0)

        new_text = MARKDOWN_LINK_RE.sub(md_replacer, text)
        spans = protected_example_spans(new_text)

        # 2. Process Wikilinks: [[link_name]] (migrates them to Markdown standard)
        def wiki_replacer(match):
            nonlocal modified, changes_count
            raw_target = match.group(1)
            if example(match):
                return match.group(0)
            clean_target = raw_target.split("|", 1)[0].split("#", 1)[0].strip()
            display_text = raw_target.split("|", 1)[1].strip() if "|" in raw_target else clean_target
            hit = resolve_target(clean_target)
            if hit:
                new_rel = get_relative_path(rel_source, hit)
                if "#" in raw_target:
                    new_rel += "#" + raw_target.split("|", 1)[0].split("#", 1)[1]
                print(f"[MIGRATED WIKILINK] {rel_source}: [[{raw_target}]] -> [{display_text}]({new_rel})")
                changes_count += 1
                modified = True
                return f"[{display_text}]({new_rel})"
            return match.group(0)

        new_text = WIKILINK_RE.sub(wiki_replacer, new_text)

        if modified:
            plain_vault_path(VAULT_DIR, path)
            write_preserving_endings(path, new_text)
            files_modified += 1

    print("\n--- Summary ---")
    print(f"Files Modified: {files_modified}")
    print(f"Links Refactored/Migrated: {changes_count}")
    print("Done.")

if __name__ == "__main__":
    main()
