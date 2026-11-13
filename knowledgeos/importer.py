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
import os
import re
import stat
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

    What this defends against is an accident: a person who points the import at their
    own vault, or at a folder with a link into it. The vault's notes are already
    memory, and some are excluded, superseded or undecided on purpose. It does not
    defend against a second program that changes files while the import runs; such a
    program can read the vault directly. `docs/threat-model.md` states this.

    A source inside the vault, or one that holds it, is refused. In a folder, a link, a
    file that resolves into the vault and a file with a second name (a hard link) are
    skipped, and each one is named in the problems. Every file is read through one open
    handle, and the checks are made on that handle, so the file that was checked is the
    file that was read.

    A folder with more than ``MAX_FILES`` text files is refused whole unless
    ``many_files`` is set. Part of a folder is never read in silence.
    """
    from knowledgeos.indexer import _is_link

    path = Path(path).expanduser()
    if not path.exists() or _is_link(path):
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
        files = []
        for candidate in _plain_files(resolved, problems):
            if candidate.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            if _within(candidate.resolve(), home):
                problems.append(f"is a file of the vault, skipped: {candidate.relative_to(resolved).as_posix()}")
            else:
                files.append(candidate)
        if len(files) > MAX_FILES and not many_files:
            return [], [f"the folder holds {len(files)} text files, more than {MAX_FILES}, so nothing was "
                        "read. Import a smaller folder, or pass --many-files to read them all"]
    documents: list[Document] = []
    for file in files:
        name = file.relative_to(resolved).as_posix() if resolved.is_dir() else ""
        shown = name or file.name
        try:
            data, skipped = _read_plain_file(file)
            if skipped:
                problems.append(f"{skipped}, skipped: {shown}")
                continue
            documents.append(Document(name, data.decode("utf-8-sig", errors="strict")))
        except (OSError, UnicodeError):
            problems.append(f"unreadable, skipped: {shown}")
    if not documents and not problems:
        problems.append("no markdown or text files found")
    return documents, problems


def _plain_files(folder: Path, problems: list[str]) -> list[Path]:
    """Every plain file below ``folder``. A linked folder is not entered.

    A Windows junction is a link too, and a walk that follows one reads another folder
    under this folder's name. Each link that is skipped is named in ``problems``.
    """
    from knowledgeos.indexer import _is_link

    found: list[Path] = []
    pending = [folder]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            problems.append(f"unreadable folder, skipped: {current.relative_to(folder).as_posix()}")
            continue
        for entry in entries:
            shown = entry.relative_to(folder).as_posix()
            if _is_link(entry):
                if entry.is_dir():
                    problems.append(f"is a linked folder, skipped: {shown}")
                elif entry.suffix.lower() in SOURCE_SUFFIXES:
                    problems.append(f"is a link, skipped: {shown}")
            elif entry.is_dir():
                pending.append(entry)
            elif entry.is_file():
                found.append(entry)
    return sorted(found)


def _read_plain_file(file: Path) -> tuple[bytes, str | None]:
    """``(bytes, None)`` for a plain file with one name, or ``(b"", reason)``.

    One handle: the file is opened first, and its kind, its number of names and its
    size are asked of the open handle. The name is looked at before and after the open,
    so a name that was swapped for another file in between is noticed.
    """
    before = os.lstat(file)
    if not stat.S_ISREG(before.st_mode):
        return b"", "is not a plain file"
    with open(file, "rb") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            return b"", "changed while it was read"
        if opened.st_nlink > 1:
            return b"", "has a second name (a hard link)"
        if opened.st_size > MAX_FILE_BYTES:
            return b"", "too large"
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        return b"", "too large"
    return data, None


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40] or "import"


# A draft in one of these states has put its rules in front of the person. A superseded
# draft was closed before they decided, so its rules may be offered again.
_ASKED = {"draft", "applied", "rejected"}


def _asked_by_an_older_row(api: Any, row: dict[str, Any]) -> set[str] | None:
    """The lines of a draft whose signed row holds no line digests (made before 0.5).

    The draft file is trusted only while its body still has the digest the row signed.
    ``None`` means the file is gone or was changed, so nobody can say what it asked.
    """
    from knowledgeos import gate

    try:
        text = (Path(api.vault) / str(row.get("proposal") or "")).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    body = gate.extract_proposed(text)
    if body is None or hashlib.sha256(body.strip().encode("utf-8")).hexdigest() != row.get("body_sha256"):
        return None
    return set(gate.asked_lines(body))


def _undrafted(api: Any, rules: list[str]) -> tuple[list[str], str | None, int]:
    """The rules the person has not been asked about yet.

    A rule is left out when it is a whole line of the profile, or of a profile draft
    that waits or that the person decided. So a rejected rule is not offered again, and
    a rule that is only part of another line still counts as new. What a draft asked is
    read from its signed row outside the vault, not from the draft file, so an edited or
    deleted draft file changes nothing.

    Returns the rules, the path of a waiting draft that already holds some of them, and
    the number of older drafts that could not be checked.
    """
    from knowledgeos import gate

    wanted = {gate.line_digest(rule) for rule in rules}
    held = set(gate.asked_lines((api.self_get().get("sections") or {}).get("heuristics") or ""))
    waiting: str | None = None
    unchecked = 0
    for row in gate.read_ledger(api.vault)[0]:
        if row.get("section") != "heuristics" or row.get("status") not in _ASKED:
            continue
        signed = row.get("asked_lines")
        asked = set(map(str, signed)) if isinstance(signed, list) else _asked_by_an_older_row(api, row)
        if asked is None:
            unchecked += 1
            continue
        if row.get("status") == "draft" and waiting is None and asked & wanted:
            waiting = str(row.get("proposal") or "")
        held |= asked
    # A draft file with no signed row (the signing state was lost, or the vault was
    # restored without it) is history nobody can check. It is counted, never trusted.
    unchecked += len(gate.untrusted_proposals(api.vault, api.proposals_dir))
    return [rule for rule in rules if gate.line_digest(rule) not in held], waiting, unchecked


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
                              "drafts_not_checked": 0, "dry_run": dry_run}
    rules: list[str] = []
    seen: set[str] = set()
    for item in items:
        # The exact label and the exact text: `Chat GPT` and `chat-gpt` are two sources,
        # and two lines that differ only in spacing can be two facts.
        identity = [label, *([item.source] if item.source else []), item.text]
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
        rules, waiting, report["drafts_not_checked"] = _undrafted(api, rules)
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
    from knowledgeos.remembering import marked_excluded

    return marked_excluded(text)


def import_path(api: Any, path: Path, label: str | None = None, *, dry_run: bool = False,
                draft_profile: bool = True, many_files: bool = False) -> dict[str, Any]:
    documents, problems = read_source(Path(path), api.vault, many_files=many_files)
    label = label or Path(path).expanduser().name
    items = [item for document in documents
             for item in split_items(document.text, document.name, _marked_excluded(api, document.text))]
    report = import_items(api, items, label, dry_run=dry_run, draft_profile=draft_profile)
    report["files"] = len(documents)
    if report["drafts_not_checked"]:
        problems.append(f"{report['drafts_not_checked']} earlier profile draft(s) could not be checked: the "
                        "draft file is gone or was changed, or the draft is not in the signed record. A rule "
                        "you already decided can be drafted again; reject it again in `twinaatma self review`")
    report["problems"] = problems
    return report
