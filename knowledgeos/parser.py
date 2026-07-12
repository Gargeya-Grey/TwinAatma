"""Shared frontmatter parser for KnowledgeOS (stdlib only).

KnowledgeOS-flavored YAML subset:
- key: value
- key: [a, b]
- key:\\n  - item
- booleans: true/false
- keys are normalized to lowercase
"""
from __future__ import annotations

import re
from typing import Any

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.S)


def _parse_scalar(raw: str) -> Any:
    val = raw.strip().strip('"').strip("'")
    low = val.lower()
    if low in {"true", "yes", "on"}:
        return True
    if low in {"false", "no", "off"}:
        return False
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip('"').strip("'") for item in inner.split(",") if item.strip()]
    return val


def parse_frontmatter_block(yaml_text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key: str | None = None
    for line in yaml_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("-") and current_key:
            val = stripped[1:].strip().strip('"').strip("'")
            existing = data.get(current_key)
            if isinstance(existing, list):
                existing.append(val)
            elif existing in ("", None):
                data[current_key] = [val]
            else:
                data[current_key] = [existing, val]
            continue
        if ":" in line:
            key, _, rest = line.partition(":")
            key = key.strip().lower()
            data[key] = _parse_scalar(rest)
            current_key = key
    return data


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body). Empty dict if no frontmatter."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm = parse_frontmatter_block(m.group(1))
    body = text[m.end() :]
    return fm, body


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse YAML frontmatter from a markdown note. Keys are lowercased."""
    fm, _ = split_frontmatter(text)
    return fm
