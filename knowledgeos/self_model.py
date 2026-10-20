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
    """Use the writer's canonical markers, aliases, and ambiguity checks."""
    from knowledgeos.gate import section_body

    sections: dict[str, str] = {}
    for key in SECTION_ALIASES:
        content = section_body(body, key)
        if content is not None:
            sections[key] = content.strip()
    return sections


def _name_key(text: str) -> str:
    """Normalised comparison key: letters/digits only, collapsed.

    Identical to ``gate._name_key`` on purpose — two different notions of "same heading"
    is how a section becomes visible to one path and invisible to the other.
    """
    cleaned = "".join(ch for ch in text.lower() if ch.isalnum() or ch in {" ", "-", "_"})
    return " ".join(cleaned.replace("_", " ").replace("-", " ").split())


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
