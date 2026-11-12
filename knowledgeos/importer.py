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
# New notes written by one run. A larger source continues on the next run, because a
# note that is already present does not count.
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
    # The file inside an imported folder; empty for a single file.
    source: str = ""
    # The source file marked itself as not to be remembered.
    excluded: bool = False

    @property
    def title(self) -> str:
        from knowledgeos.memory import title_from_text

        return title_from_text(self.text) or "Imported memory"


@dataclass(frozen=True)
class Document:
    name: str
    text: str


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[text.find("\n", end + 1) + 1:]
    return text


def split_items(text: str, source: str = "", excluded: bool = False) -> list[Item]:
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
            items.append(Item(body[:MAX_ITEM_CHARS], heading, source, excluded))

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


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def read_source(path: Path, vault: Path, *, many_files: bool = False) -> tuple[list[Document], list[str]]:
    """``([Document], [problem])`` for a file or folder apart from the vault. Read only.

    The vault's own notes are already memory, and some of them are excluded, superseded
    or undecided on purpose. A source that is inside the vault, or that holds it, is
    refused, and a file that resolves into the vault is skipped. A file with a second
    name (a hard link) is skipped too, because no path can show that it is not a vault
    file.

    A folder with more than ``MAX_FILES`` text files is refused whole unless
    ``many_files`` is set. Part of a folder is never read in silence.
    """
    path = Path(path).expanduser()
    if path.is_symlink() or not path.exists():
        return [], [f"not found or a link: {path.name}"]
    resolved, home = path.resolve(), Path(vault).resolve()
    if _within(resolved, home):
        return [], ["the source is inside the vault; those notes are already memory"]
    if _within(home, resolved):
        return [], ["the source folder holds the vault; import only the other assistant's folder"]
    problems: list[str] = []
    if resolved.is_file():
        files = [resolved]
    else:
        files = sorted(candidate for candidate in resolved.rglob("*")
                       if candidate.suffix.lower() in SOURCE_SUFFIXES and candidate.is_file()
                       and not candidate.is_symlink() and not _within(candidate.resolve(), home))
        if len(files) > MAX_FILES and not many_files:
            return [], [f"the folder holds {len(files)} text files, more than {MAX_FILES}, so nothing was "
                        "read. Import a smaller folder, or pass --many-files to read them all"]
    documents: list[Document] = []
    for file in files:
        name = file.relative_to(resolved).as_posix() if resolved.is_dir() else ""
        shown = name or file.name
        try:
            info = file.stat()
            if info.st_nlink > 1:
                problems.append(f"has a second name (a hard link), skipped: {shown}")
                continue
            if info.st_size > MAX_FILE_BYTES:
                problems.append(f"too large, skipped: {shown}")
                continue
            documents.append(Document(name, file.read_bytes().decode("utf-8-sig", errors="strict")))
        except (OSError, UnicodeError):
            problems.append(f"unreadable, skipped: {shown}")
    if not documents and not problems:
        problems.append("no markdown or text files found")
    return documents, problems


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40] or "import"


_LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
# A draft in one of these states has put its rules in front of the person. A superseded
# draft was closed before they decided, so its rules may be offered again.
_ASKED = {"draft", "applied", "rejected"}


def _rule_key(line: str) -> str:
    """One rule as it is compared: without the list mark, with single spaces."""
    return " ".join(_LIST_MARK.sub("", line).split())


def _rule_keys(text: Any) -> set[str]:
    return {key for key in map(_rule_key, str(text or "").splitlines()) if key}


def _undrafted(api: Any, rules: list[str]) -> tuple[list[str], str | None]:
    """The rules the person has not been asked about yet.

    A rule is left out when it is a whole line of the profile, or of a profile draft
    that waits or that the person decided. So a rejected rule is not offered again, and
    a rule that is only part of another line still counts as new. Returns the rules with
    the path of a waiting draft that already holds some of them, if any.
    """
    from knowledgeos import gate

    wanted = {_rule_key(rule) for rule in rules}
    held = _rule_keys((api.self_get().get("sections") or {}).get("heuristics"))
    waiting: str | None = None
    for row in gate.read_ledger(api.vault)[0]:
        if row.get("section") != "heuristics" or row.get("status") not in _ASKED:
            continue
        relative = str(row.get("proposal") or "")
        try:
            asked = _rule_keys(gate.extract_proposed(
                (Path(api.vault) / relative).read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
        if row.get("status") == "draft" and waiting is None and asked & wanted:
            waiting = relative
        held |= asked
    return [rule for rule in rules if _rule_key(rule) not in held], waiting


def import_items(api: Any, items: Iterable[Item], label: str, *, dry_run: bool = False,
                 draft_profile: bool = True) -> dict[str, Any]:
    """Capture each item once, then draft one profile change from the rule-like lines.

    Re-running the same import changes nothing: each capture is keyed by its source and
    its exact text. One run writes at most ``MAX_ITEMS`` new notes and drafts at most ``MAX_RULES``
    lines. The report counts what is left, and the next run continues from there. The
    report counts what the remembering policy withheld without repeating it.
    """
    slug = _slug(label)
    report: dict[str, Any] = {"label": label, "found": 0, "imported": 0, "already_present": 0,
                              "withheld_by_policy": 0, "failed": 0, "left_for_next_run": 0,
                              "paths": [], "profile_draft": None, "rules_left_for_next_run": 0,
                              "dry_run": dry_run}
    rules: list[str] = []
    seen: set[str] = set()
    for item in items:
        # The exact text: two lines that differ only in spacing can be two facts.
        identity = [slug, *([item.source] if item.source else []), item.text]
        key = hashlib.sha256("\0".join(identity).encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        report["found"] += 1
        if item.excluded:
            report["withheld_by_policy"] += 1
            continue
        rule = _rule_line(item)
        if dry_run:
            if rule:
                rules.append(rule)
            continue
        target = api.inbox / ("capture-" + hashlib.sha256(("import:" + key).encode()).hexdigest() + ".md")
        if target.exists():
            report["already_present"] += 1
            report["paths"].append(target.relative_to(api.vault).as_posix())
            if rule:
                rules.append(rule)
            continue
        if report["imported"] >= MAX_ITEMS:
            report["left_for_next_run"] += 1
            continue
        origin = f"{label}, file {item.source}" if item.source else label
        context = f" ({item.heading})" if item.heading else ""
        content = f"{item.text}\n\nImported from {origin}{context}."
        result = api.capture(item.title, content, ["imported", "from-" + slug], "import:" + key)
        if result.get("ok") is True:
            report["imported"] += 1
            report["paths"].append(result["path"])
            if rule:
                rules.append(rule)
        elif result.get("policy") and result.get("ok") is False:
            report["withheld_by_policy"] += 1
        else:
            report["failed"] += 1
    rules = list(dict.fromkeys(rules))
    report["rule_like_lines"] = len(rules)
    if rules and draft_profile and not dry_run:
        rules, waiting = _undrafted(api, rules)
        report["rule_like_lines"] = min(len(rules), MAX_RULES)
        report["rules_left_for_next_run"] = max(0, len(rules) - MAX_RULES)
        rules = rules[:MAX_RULES]
        if not rules:
            # Importing the same source again must not stack a second draft.
            report["profile_draft"] = waiting
        else:
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


def _marked_excluded(api: Any, text: str) -> bool:
    """True when the source file's own metadata says it is not to be remembered.

    Only the metadata is asked here. A credential inside one line is still judged line by
    line at capture, so one secret does not withhold the rest of a file.
    """
    from knowledgeos.parser import split_frontmatter
    from knowledgeos.remembering import RememberingPolicy

    metadata = split_frontmatter(text.replace("\r\n", "\n"))[0]
    return bool(metadata) and RememberingPolicy(api.vault).text_reason("", metadata) is not None


def import_path(api: Any, path: Path, label: str | None = None, *, dry_run: bool = False,
                draft_profile: bool = True, many_files: bool = False) -> dict[str, Any]:
    documents, problems = read_source(Path(path), api.vault, many_files=many_files)
    label = label or Path(path).expanduser().name
    items = [item for document in documents
             for item in split_items(document.text, document.name, _marked_excluded(api, document.text))]
    report = import_items(api, items, label, dry_run=dry_run, draft_profile=draft_profile)
    report["files"] = len(documents)
    report["problems"] = problems
    return report
