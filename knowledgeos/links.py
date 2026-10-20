"""Link extraction helpers."""
from __future__ import annotations

import posixpath
import re
import urllib.parse
from pathlib import Path

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(((?:[^()]+|\([^()]*\))+)\)")


class LinkTarget(str):
    """A raw link that retains Markdown's relative-path semantics."""

    def __new__(cls, value: str, *, markdown: bool = False):
        target = super().__new__(cls, value)
        target.markdown = markdown
        return target


class NoteLookup(dict[str, str]):
    def __init__(self):
        super().__init__()
        self.basenames: dict[str, list[str]] = {}


def _without_fences(text: str) -> str:
    lines: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is None and match:
            fence = match[1]
        elif fence is not None:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
        else:
            lines.append(line)
    return "".join(lines)


def extract_raw_links(text: str) -> list[str]:
    text = _without_fences(text)
    links: list[str] = []
    for raw in WIKILINK_RE.findall(text):
        if not raw.strip().startswith("#"):
            links.append(LinkTarget(raw))
    for raw in MARKDOWN_LINK_RE.findall(text):
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw) and not raw.startswith("#"):
            links.append(LinkTarget(urllib.parse.unquote(raw.strip().strip("<>")), markdown=True))
    return links


def build_note_lookup(md_files: list[Path], vault_dir: Path) -> dict[str, str]:
    lookup = NoteLookup()
    for path in sorted(md_files):
        rel = path.relative_to(vault_dir).as_posix()
        lookup[rel.lower()] = rel
        lookup[rel[:-3].lower()] = rel
        for name in (path.stem.lower(), path.name.lower()):
            lookup.basenames.setdefault(name, []).append(rel)
    return lookup


def link_candidates(raw: str, source_rel: str, lookup: dict[str, str]) -> list[str]:
    target = urllib.parse.unquote(raw.split("|", 1)[0].split("#", 1)[0].strip())
    if not target:
        return []
    target = target.replace("\\", "/")
    markdown = getattr(raw, "markdown", False)
    if not markdown and "/" not in target and isinstance(lookup, NoteLookup):
        return sorted(lookup.basenames.get(target.lower(), []))
    root_target = target.lstrip("/")
    relative = posixpath.join(posixpath.dirname(source_rel), target)
    candidates = [relative, root_target] if markdown and not target.startswith("/") else [root_target]
    for candidate in candidates:
        norm = posixpath.normpath(candidate).lower()
        hit = lookup.get(norm) or lookup.get(norm + ".md")
        if hit:
            return [hit]
    return []


def normalize_link(raw: str, source_rel: str, lookup: dict[str, str]) -> str:
    matches = link_candidates(raw, source_rel, lookup)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return ""
    target = urllib.parse.unquote(raw.split("|", 1)[0].split("#", 1)[0].strip())
    return target
