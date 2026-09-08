"""Link extraction helpers."""
from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(((?:[^()]+|\([^()]*\))+)\)")


def extract_raw_links(text: str) -> list[str]:
    links: list[str] = []
    for raw in WIKILINK_RE.findall(text):
        links.append(raw)
    for raw in MARKDOWN_LINK_RE.findall(text):
        if not raw.startswith(("http://", "https://", "mailto:", "ftp:", "#", "obsidian:")):
            links.append(urllib.parse.unquote(raw))
    return links


def build_note_lookup(md_files: list[Path], vault_dir: Path) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for path in md_files:
        rel = path.relative_to(vault_dir).as_posix()
        stem = path.stem
        lookup[rel.lower()] = rel
        lookup[rel[:-3].lower()] = rel
        lookup[stem.lower()] = rel
    return lookup


def normalize_link(raw: str, source_rel: str, lookup: dict[str, str]) -> str:
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
        hit = lookup.get(norm.lower()) or lookup.get(
            norm[:-3].lower() if norm.endswith(".md") else norm.lower()
        )
        if hit:
            return hit
    return target
