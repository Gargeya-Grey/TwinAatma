"""Link extraction helpers."""
from __future__ import annotations

import re
import urllib.parse

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
