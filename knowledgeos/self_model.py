"""Self.md (Ego Node) parse helpers for write-back proposals."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from knowledgeos.parser import split_frontmatter

# Canonical section anchors (match with or without emoji prefixes)
SECTION_ALIASES = {
    "heuristics": [
        "operating heuristics",
        "operating heuristics & rules of thumb",
        "heuristics",
        "rules of thumb",
    ],
    "values": ["values hierarchy", "values", "core values"],
    "mental_models": ["mental models"],
    "anti_goals": ["anti-goals", "anti goals"],
    "active_bets": ["active bets", "current bets"],
    "drift_log": ["semantic drift", "semantic drift tracking", "drift log", "drift"],
}


@dataclass
class SelfModel:
    path: Path
    frontmatter: dict
    body: str
    sections: dict[str, str] = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "path": str(self.path),
            "title": self.frontmatter.get("title", "Self"),
            "sections_present": sorted(self.sections.keys()),
            "heuristics_excerpt": (self.sections.get("heuristics") or "")[:400],
            "values_excerpt": (self.sections.get("values") or "")[:400],
            "anti_goals_excerpt": (self.sections.get("anti_goals") or "")[:400],
            "active_bets_excerpt": (self.sections.get("active_bets") or "")[:400],
        }


def _normalize_heading(text: str) -> str:
    # Strip markdown heading markers and leading emoji/symbols
    t = text.strip()
    t = re.sub(r"^#+\s*", "", t)
    t = re.sub(r"^[^\w]+", "", t, flags=re.UNICODE)
    return t.strip().lower()


def _split_sections(body: str) -> dict[str, str]:
    """Split body on ## headings into canonical Self section keys."""
    lines = body.splitlines()
    headings: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            headings.append((i, _normalize_heading(line)))

    raw: dict[str, str] = {}
    for idx, (start, heading) in enumerate(headings):
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        content = "\n".join(lines[start + 1 : end]).strip()
        raw[heading] = content

    sections: dict[str, str] = {}
    for key, aliases in SECTION_ALIASES.items():
        for heading, content in raw.items():
            if any(alias in heading for alias in aliases):
                sections[key] = content
                break
    return sections


def load_self(path: Path) -> SelfModel:
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body = split_frontmatter(text)
    return SelfModel(path=path, frontmatter=fm, body=body, sections=_split_sections(body))


CANONICAL_SELF_SECTIONS = """
## Operating Heuristics & Rules of Thumb
<!-- kos:section=heuristics -->

## Values Hierarchy
<!-- kos:section=values -->

## Mental Models
<!-- kos:section=mental_models -->

## Anti-Goals
<!-- kos:section=anti_goals -->

## Active Bets
<!-- kos:section=active_bets -->
*Current strategic bets / commitments the agent should treat as live context.*

## Drift Log
<!-- kos:section=drift_log -->
| Topic | Shift Observed | Date Flagged | Evidence |
|---|---|---|---|
""".strip()
