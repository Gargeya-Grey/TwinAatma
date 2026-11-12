"""Bring memory in from other assistants and agent files.

A person's first day should not start from an empty profile. This module turns text they
already own (an assistant's memory export, a ``CLAUDE.md``, an ``AGENTS.md``, a folder of
agent memory files) into ordinary captures, and drafts one profile change for them to
review in a terminal.

It adds no new write path. Every item goes through :meth:`MemoryAPI.capture`, so the
remembering policy decides what is kept, and the profile draft goes through
:meth:`MemoryAPI.propose_self_update`, so nothing reaches ``People/Self.md`` without the
person's own approval. Imported text is evidence about the person, never instructions.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_FILES = 200
MAX_ITEMS = 500
MAX_ITEM_CHARS = 2000
MAX_RULES = 12
MAX_RULE_CHARS = 200
SOURCE_SUFFIXES = {".md", ".mdc", ".txt", ".markdown"}

_BULLET = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$")
_HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
_RULE = re.compile(
    r"\b(always|never|prefers?|preferred|avoids?|don't|do not|doesn't|does not|must|should|"
    r"likes?|dislikes?|hates?|wants?|rather|instead of|keep|use|write|no)\b",
    re.IGNORECASE,
)
_MARKUP = re.compile(r"[<>`#|\[\]{}]")


@dataclass(frozen=True)
class Item:
    text: str
    heading: str

    @property
    def title(self) -> str:
        from knowledgeos.memory import title_from_text

        return title_from_text(self.text) or "Imported memory"


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[text.find("\n", end + 1) + 1:]
    return text


def split_items(text: str) -> list[Item]:
    """One item per top-level bullet or paragraph, with the heading it sat under."""
    items: list[Item] = []
    heading = ""
    current: list[str] = []
    in_bullet = False
    in_fence = False

    def flush() -> None:
        nonlocal current, in_bullet
        body = "\n".join(current).strip()
        current, in_bullet = [], False
        if len(body.split()) >= 3:
            items.append(Item(body[:MAX_ITEM_CHARS], heading))

    for line in _strip_frontmatter(text.replace("\r\n", "\n")).split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            current.append(line)
            continue
        if in_fence:
            current.append(line)
            continue
        found = _HEADING.match(line)
        if found:
            flush()
            heading = found.group(1).strip()
            continue
        if not line.strip():
            flush()
            continue
        bullet = _BULLET.match(line)
        if bullet and not bullet.group(1):
            flush()
            current.append(bullet.group(2))
            in_bullet = True
        elif bullet and in_bullet:
            current.append("  - " + bullet.group(2))
        else:
            current.append(line.strip())
    flush()
    return items


def _rule_line(item: Item) -> str | None:
    """A single plain line that reads like a standing rule or preference, or nothing."""
    line = " ".join(item.text.split("\n", 1)[0].split())
    if not 3 <= len(line.split()) <= 40 or len(line) > MAX_RULE_CHARS:
        return None
    if not _RULE.search(line):
        return None
    return _MARKUP.sub("", line).strip() or None


def _source_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    found = sorted(candidate for candidate in path.rglob("*")
                   if candidate.suffix.lower() in SOURCE_SUFFIXES and candidate.is_file()
                   and not candidate.is_symlink())
    return found[:MAX_FILES]


def read_source(path: Path, vault: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """``([(name, text)], [problem])`` for a file or folder outside the vault. Read only."""
    path = Path(path).expanduser()
    problems: list[str] = []
    if path.is_symlink() or not path.exists():
        return [], [f"not found or a link: {path.name}"]
    resolved = path.resolve()
    try:
        resolved.relative_to(Path(vault).resolve())
    except ValueError:
        pass
    else:
        return [], ["the source is inside the vault; those notes are already memory"]
    documents: list[tuple[str, str]] = []
    for file in _source_files(resolved):
        try:
            if file.stat().st_size > MAX_FILE_BYTES:
                problems.append(f"too large, skipped: {file.name}")
                continue
            documents.append((file.name, file.read_bytes().decode("utf-8", errors="strict")))
        except (OSError, UnicodeError):
            problems.append(f"unreadable, skipped: {file.name}")
    if not documents and not problems:
        problems.append("no markdown or text files found")
    return documents, problems


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40] or "import"


def import_items(api: Any, items: Iterable[Item], label: str, *, dry_run: bool = False,
                 draft_profile: bool = True) -> dict[str, Any]:
    """Capture each item once, then draft one profile change from the rule-like lines.

    Re-running the same import changes nothing: each capture is keyed by its source label
    and text. The report counts what the remembering policy withheld without repeating it.
    """
    slug = _slug(label)
    report: dict[str, Any] = {"label": label, "found": 0, "imported": 0, "already_present": 0,
                              "withheld_by_policy": 0, "failed": 0, "truncated": False,
                              "paths": [], "profile_draft": None, "dry_run": dry_run}
    rules: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = hashlib.sha256((slug + "\0" + " ".join(item.text.split())).encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        if report["found"] >= MAX_ITEMS:
            report["truncated"] = True
            break
        report["found"] += 1
        rule = _rule_line(item)
        if dry_run:
            if rule:
                rules.append(rule)
            continue
        context = f" ({item.heading})" if item.heading else ""
        content = f"{item.text}\n\nImported from {label}{context}."
        target = api.inbox / ("capture-" + hashlib.sha256(("import:" + key).encode()).hexdigest() + ".md")
        existed = target.exists()
        result = api.capture(item.title, content, ["imported", "from-" + slug], "import:" + key)
        if result.get("ok") is True:
            report["already_present" if existed else "imported"] += 1
            report["paths"].append(result["path"])
            if rule:
                rules.append(rule)
        elif result.get("policy") and result.get("ok") is False:
            report["withheld_by_policy"] += 1
        else:
            report["failed"] += 1
    rules = list(dict.fromkeys(rules))[:MAX_RULES]
    report["rule_like_lines"] = len(rules)
    if rules and draft_profile and not dry_run:
        rules, waiting = _undrafted(api, rules)
        if not rules:
            # Importing the same source again must not stack a second draft.
            report["profile_draft"] = waiting
            report["rule_like_lines"] = 0
    if rules and draft_profile and not dry_run:
        drafted = api.propose_self_update(
            f"Rules and preferences imported from {label}",
            "heuristics",
            "\n".join(f"* {rule}" for rule in rules),
            f"Drafted from {len(rules)} imported lines that read like standing rules. "
            "Approve only the ones that are yours.",
            "append",
        )
        if drafted.get("proposal_path"):
            report["profile_draft"] = drafted["proposal_path"]
        else:
            report["profile_draft_error"] = str(drafted.get("error") or "the draft was refused")
    return report


def _undrafted(api: Any, rules: list[str]) -> tuple[list[str], str | None]:
    """The rules that are neither in the profile nor in a draft that still waits.

    Returns them with the path of a waiting draft that already holds some, if any.
    """
    from knowledgeos import gate

    current = api.self_get()
    held = str((current.get("sections") or {}).get("heuristics") or "")
    waiting: str | None = None
    for draft in gate.list_open(api.vault):
        if draft.get("section") != "heuristics":
            continue
        described = gate.describe(api.vault, api.proposals_dir, draft["path"])
        patch = str(described.get("patch") or "")
        if any(rule in patch for rule in rules):
            waiting = waiting or draft["path"]
            held += "\n" + patch
    return [rule for rule in rules if rule not in held], waiting


def import_path(api: Any, path: Path, label: str | None = None, *, dry_run: bool = False,
                draft_profile: bool = True) -> dict[str, Any]:
    documents, problems = read_source(Path(path), api.vault)
    label = label or Path(path).expanduser().name
    items = [item for _name, text in documents for item in split_items(text)]
    report = import_items(api, items, label, dry_run=dry_run, draft_profile=draft_profile)
    report["files"] = len(documents)
    report["problems"] = problems
    return report
