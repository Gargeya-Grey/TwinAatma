"""Self-model gate: the only code path allowed to change ``People/Self.md``.

Threat model (read this before trusting anything here)
------------------------------------------------------
This gate protects the identity layer from **an agent that can call tools and read
files inside the vault**, including a prompt-injected one. It does *not* try to
defend against the vault owner, who may edit ``Self.md`` in Obsidian by design.

What the gate enforces:

1. **A human said yes.** Applying a proposal requires an interactive terminal
   (``twinaatma self approve``), checked inside ``_apply`` rather than only in the
   CLI. There is no confirmation code, on purpose: a code returned in a tool result
   is read by the model, so it is not a separation of privilege. This is the
   difference between "the toolkit wrote this" and "a person approved this".
2. **The proposal is authentic.** The ledger row is HMAC-signed with a key that
   lives outside the vault, so writing a row is not enough to mint authority.
   The ledger lives outside the vault too, for the same reason.
3. **The bytes are the ones that were reviewed.** The body hash must match and
   the target section digest must match, with no "absent means skip" path.
4. **The document keeps its shape.** After substitution, the heading set and the
   ``kos:section`` marker set must be identical to before. A patch cannot add,
   remove, rename or shadow a section, whatever whitespace it uses.
5. **Nothing invisible.** A patch must contain visible characters, and a replace
   that would delete almost all of a section needs an explicit destructive opt-in.
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterator

from knowledgeos.self_model import SECTION_ALIASES

LEDGER_DIR_NAME = "self-proposals"
LOCK_NAME = "self-gate.lock"
LOCK_STALE_SECONDS = 120.0
LOCK_WAIT_SECONDS = 10.0

DESTRUCTIVE_KEEP_RATIO = 0.6
DESTRUCTIVE_MIN_CHARS = 40

TABLE_HEADER = [
    "| Topic | Shift Observed | Date Flagged | Evidence |",
    "|---|---|---|---|",
]

_MARKER_RE = re.compile(r"kos:section=([A-Za-z0-9_]+)")
_FENCE_OPEN_RE = re.compile(r"^(`{3,})markdown[ \t]*$", re.M)
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\ufff9-\ufffb]")


# --------------------------------------------------------------------------- #
# durable state, kept out of the vault so vault writes cannot mint authority
# --------------------------------------------------------------------------- #


def _state_home() -> Path:
    override = os.environ.get("KNOWLEDGEOS_STATE_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "TwinAatma"


def vault_id(vault: Path) -> str | None:
    """The vault's own stable id, if it has one (written by ``init``).

    Keying the ledger by filesystem path meant that moving or renaming a vault
    orphaned every pending proposal — and worse, the proposal files were still there
    and simply became unacceptable, with no explanation.
    """
    for name in (".knowledgeos-vault.json", "knowledgeos.config.json"):
        marker = Path(vault) / name
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        value = str(data.get("vault_id") or "").strip()
        if re.fullmatch(r"[0-9a-fA-F]{16,64}", value):
            return value.lower()
    return None


def _binding_path() -> Path:
    return _state_home() / "vault-bindings.json"


def _binding_parents(path: Path) -> None:
    for parent in path.absolute().parents:
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        reparse = bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
        if not stat.S_ISDIR(info.st_mode) or reparse:
            raise OSError(f"Binding state parent is not a plain directory: {parent}")


def _binding_file(path: Path) -> os.stat_result | None:
    _binding_parents(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    reparse = bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or reparse:
        raise OSError(f"Binding state is not a plain single-link file: {path}")
    return info


def _binding_object(pairs: list[tuple[str, Any]]) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for path_key, key in pairs:
        if not path_key or not isinstance(key, str) or not key or path_key in bindings:
            raise ValueError("invalid or duplicate binding entry")
        bindings[path_key] = key
    return bindings


def _read_bindings() -> dict[str, str]:
    path = _binding_path()
    expected = _binding_file(path)
    if expected is None:
        return {}
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as handle:
            actual = os.fstat(handle.fileno())
            if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino) or actual.st_nlink != 1:
                raise OSError(f"Binding state changed while opening it: {path}")
            data = json.loads(handle.read().decode("utf-8"), object_pairs_hook=_binding_object)
    except (ValueError, UnicodeError) as exc:
        raise OSError(f"Binding state is malformed; original bytes were preserved: {path}") from exc
    if not isinstance(data, dict):
        raise OSError(f"Binding state is malformed; original bytes were preserved: {path}")
    return data


def _remember_binding(path_key: str, key: str) -> str:
    from knowledgeos.locking import file_lock
    from knowledgeos.textio import atomic_write

    path = _binding_path()
    _binding_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _binding_parents(path)
    with file_lock(path.with_suffix(".lock"), timeout=LOCK_WAIT_SECONDS,
                   message="Binding state is busy; try again in a moment"):
        bindings = _read_bindings()
        if path_key in bindings:
            return bindings[path_key]
        bindings[path_key] = key
        _binding_file(path)
        atomic_write(path, json.dumps(bindings, indent=0, sort_keys=True), "\n")
        return key


def vault_marker_mismatch(vault: Path) -> str | None:
    """The marker disagrees with the binding recorded for this path, if any.

    Reported so the human hears about it. The ledger keeps the bound id either way.
    """
    try:
        resolved = str(Path(vault).resolve())
    except OSError:
        return None
    bound = _read_bindings().get(resolved)
    marker = vault_id(vault)
    if bound and marker and bound != marker[: len(bound)] and marker[:16] != bound:
        return (
            f".knowledgeos-vault.json says vault id {marker[:16]} but this vault was "
            f"registered as {bound}; you may have copied the marker from another vault"
        )
    return None


def vault_key(vault: Path) -> str:
    """Which ledger belongs to this vault.

    The marker file lives inside the vault, so it is writable by anything that can write
    a note — and the ledger path *is* the list of Self proposals awaiting approval. The
    reviewer rewrote 32 bytes of `.knowledgeos-vault.json` and every pending proposal
    silently disappeared: `memory_list_self_proposals` returned nothing open, `ops_status`
    counted zero, `doctor` printed PASSED, and `self approve` refused the file it had just
    written as "not registered in this install's ledger".

    A gate whose list of pending approvals can be empty by writing one vault file is not a
    gate. So the identity is bound once, in the install state (outside the vault), and the
    marker is only consulted the first time. Afterwards a changed marker is a *reported
    discrepancy*, never a relocation.
    """
    try:
        resolved = str(Path(vault).resolve())
    except OSError:
        resolved = str(vault)
    bound = _read_bindings().get(resolved)
    if bound:
        return bound
    stable = vault_id(vault)
    if stable:
        key = stable[:16]
    else:
        key = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
    return _remember_binding(resolved, key)


def ledger_path(vault: Path) -> Path:
    return _state_home() / "vaults" / vault_key(vault) / f"{LEDGER_DIR_NAME}.jsonl"


def _lock_path(vault: Path) -> Path:
    return _state_home() / "vaults" / vault_key(vault) / LOCK_NAME


def _key_path() -> Path:
    return _state_home() / "gate.key"


def _signing_key() -> bytes | None:
    """Per-install HMAC key, outside the vault. None when it cannot be created.

    Stored hex-encoded: raw 32 random bytes used to be written directly and read
    back through ``.strip()``, so a key that happened to end in a whitespace byte
    produced a *different* key on the next read and every ledger row looked forged.

    ``KNOWLEDGEOS_GATE_KEY`` is honoured only when it comes from the machine's own
    environment, never from a vault file. The generated MCP config used to embed it
    in ``.cursor/mcp.json`` — inside the vault — which handed the agent the signing
    key and made every signature decoration.
    """
    override = os.environ.get("KNOWLEDGEOS_GATE_KEY")
    if override:
        return override.encode("utf-8")
    path = _key_path()
    try:
        if path.exists():
            data = path.read_text(encoding="ascii", errors="replace").strip()
            if len(data) >= 32:
                try:
                    return bytes.fromhex(data)
                except ValueError:
                    return data.encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = secrets.token_bytes(32)
        # Through the shared writer: a predictable `.tmp` beside the signing key was one
        # more name an agent could pre-plant a hardlink at.
        from knowledgeos.textio import atomic_write

        atomic_write(path, raw.hex(), "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return raw
    except OSError:
        return None


def _mac(key: bytes | None, row: dict[str, Any]) -> str:
    if key is None:
        return ""
    payload = {k: v for k, v in row.items() if k != "mac"}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def read_ledger(vault: Path) -> tuple[list[dict[str, Any]], int]:
    """``(verified_rows, rejected_count)``. Unsigned or tampered rows are dropped."""
    path = ledger_path(vault)
    if not path.exists():
        return [], 0
    key = _signing_key()
    rows: list[dict[str, Any]] = []
    rejected = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            rejected += 1
            continue
        if not isinstance(row, dict) or not row.get("proposal"):
            rejected += 1
            continue
        if key is None or not hmac.compare_digest(str(row.get("mac") or ""), _mac(key, row)):
            rejected += 1
            continue
        rows.append(row)
    return rows, rejected


def _write_ledger(vault: Path, rows: list[dict[str, Any]]) -> None:
    """Rewrite the ledger from the verified working set, keeping foreign rows verbatim.

    Every row in ``rows`` came from ``read_ledger``, so it verified under the key in
    effect at read time; anything we changed about it (status, timestamps) needs a fresh
    MAC, and signing it is correct.

    What was *not* correct was silently rewriting the whole file from that working set.
    Rows that had failed verification — a different key, a tampered row, a row from
    another machine — were simply dropped on the next write, so a pending identity edit
    vanished from `self pending` with no message. They are now preserved byte for byte.
    They still fail verification afterwards, so they are reported as rejected rather than
    blessed by whoever wrote last.
    """
    path = ledger_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = _signing_key()
    working = {str(row.get("proposal") or "") for row in rows}
    foreign: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except ValueError:
                foreign.append(stripped)
                continue
            if not isinstance(parsed, dict) or str(parsed.get("proposal") or "") not in working:
                foreign.append(stripped)
    body = ""
    for row in rows:
        if key is not None:
            row["mac"] = _mac(key, row)
        body += json.dumps(row, sort_keys=True) + "\n"
    body += "".join(line + "\n" for line in foreign)
    from knowledgeos.textio import atomic_write

    atomic_write(path, body, "\n")


def _row_for(vault: Path, rel: str) -> tuple[dict[str, Any] | None, str | None]:
    rows, _ = read_ledger(vault)
    matches = [row for row in rows if row.get("proposal") == rel]
    if len(matches) > 1:
        return None, "the ledger has duplicate rows for this proposal; run doctor and re-propose"
    return (matches[0] if matches else None), None


def _set_status(vault: Path, rel: str, status: str, **extra: Any) -> None:
    rows, _ = read_ledger(vault)
    for row in rows:
        if row.get("proposal") == rel:
            row["status"] = status
            row.update(extra)
    _write_ledger(vault, rows)


@contextlib.contextmanager
def _lock(vault: Path) -> Iterator[None]:
    from knowledgeos.locking import file_lock

    with file_lock(_lock_path(vault), timeout=LOCK_WAIT_SECONDS,
                   message="Self gate is busy; try again in a moment"):
        yield


# --------------------------------------------------------------------------- #
# section identity
# --------------------------------------------------------------------------- #


def _normalise_heading(line: str) -> str:
    text = re.sub(r"^#+\s*", "", line).strip()
    text = re.sub(r"^[^\w]+", "", text, flags=re.UNICODE)
    return text.lower()


def _name_key(text: str) -> str:
    """Normalised comparison key: letters/digits only, collapsed."""
    cleaned = "".join(
        ch for ch in text.lower() if ch.isalnum() or ch in {" ", "-", "_"}
    )
    return " ".join(cleaned.replace("_", " ").replace("-", " ").split())


def _heading_rows(lines: list[str]) -> list[int]:
    return [i for i, line in enumerate(lines) if line.startswith("## ")]


def _marker_key(lines: list[str], index: int) -> str | None:
    window = "".join(lines[index : index + 5])
    found = _MARKER_RE.search(window)
    return found.group(1) if found else None


def section_index(text: str, section_key: str) -> int | None:
    """Line index of the ``##`` heading that owns ``section_key``.

    A ``kos:section=`` marker is authoritative. Alias matching exists only for
    vaults that predate markers and requires an **exact** normalised name: a
    substring match let ``## Counter-Values I Reject`` capture writes aimed at
    ``values`` after a human renamed a heading.
    """
    lines = text.splitlines(keepends=True)
    headings = _heading_rows(lines)

    marked = [i for i in headings if _marker_key(lines, i) == section_key]
    if len(marked) > 1:
        raise ValueError(
            f"Self.md has {len(marked)} headings marked kos:section={section_key}; "
            "resolve the duplicate before proposing a change"
        )
    if marked:
        return marked[0]

    aliases = {_name_key(alias) for alias in SECTION_ALIASES.get(section_key, [section_key])}
    alias_hits = [i for i in headings if _name_key(_normalise_heading(lines[i])) in aliases]
    if len(alias_hits) > 1:
        raise ValueError(
            f"Self.md has {len(alias_hits)} headings matching section '{section_key}'; "
            "add kos:section markers so the target is unambiguous"
        )
    return alias_hits[0] if alias_hits else None


def section_body(text: str, section_key: str) -> str | None:
    lines = text.splitlines(keepends=True)
    index = section_index(text, section_key)
    if index is None:
        return None
    headings = _heading_rows(lines)
    end = next((j for j in headings if j > index), len(lines))
    return "".join(lines[index + 1 : end])


def section_digest(text: str, section_key: str) -> str:
    """Fingerprint of a section body, used to detect edits made after proposing.

    Blank lines are dropped before hashing rather than the whole body being stripped:
    adding or removing an empty line does not change what the human read, so it should
    not invalidate a proposal — and stripping only the edges meant the same edit was
    invisible at the top of the section but changed the digest in the middle.
    """
    body = section_body(text, section_key)
    if body is None:
        return ""
    canonical = "\n".join(
        line.rstrip() for line in body.splitlines() if line.strip()
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# CommonMark's setext underline is *one or more* `=` or `-`, not three: a heading of
# "Always" followed by a single `-` renders as an H2. Requiring three let the short form
# through while `document_shape` reported no structural change.
_SETEXT_UNDERLINE_RE = re.compile(r"\s*(?:=+|-+)\s*")

# A heading does not have to start the line. `> ## Anti-Goals` inside a blockquote and
# `- ## Anti-Goals` inside a list item both draw a real section in Obsidian, and both
# began with `>` or `-`, so every "does this line start with #" check in this module saw
# ordinary text. Strip the container markers first and then ask the same question.
_CONTAINER_PREFIX_RE = re.compile(
    r"[ \t]*(?:>[ \t]?|[-*+][ \t]+|\d{1,9}[.)][ \t]+)"
)


def _strip_container_prefix(line: str) -> str:
    """The line with any blockquote/list markers removed (repeatedly).

    ``> > - ## X`` is a heading in a list in a nested quote. Stripping once would leave
    ``> - ## X``, still starting with ``>``, and the caller would conclude "not a
    heading" — the same shape of mistake, one nesting level later.
    """
    body = line
    while True:
        stripped = _CONTAINER_PREFIX_RE.match(body)
        if not stripped:
            return body
        body = body[stripped.end():]


def document_shape(text: str) -> tuple[list[str], list[str]]:
    """``(headings, markers)`` — the structural fingerprint of a Self document.

    Every heading form a renderer honours is included, not just ``##``. A patch could
    otherwise add an ATX H1 (``# Title``) or a setext heading (``Title`` underlined with
    ``===``/``---``), both of which draw a new section in Obsidian while this function —
    the check that exists to catch exactly that — reported no change.
    """
    lines = text.splitlines()
    headings: list[str] = []
    for index, line in enumerate(lines):
        # Compare the *container-stripped* form, so `## X` and `> ## X` are both seen as
        # a heading and neither can be introduced without changing the shape.
        stripped = _strip_container_prefix(line).strip()
        if stripped.startswith("#"):
            headings.append(stripped.rstrip())
            continue
        if index > 0 and _SETEXT_UNDERLINE_RE.fullmatch(stripped):
            previous = _strip_container_prefix(lines[index - 1]).strip()
            if previous and not previous.startswith(("-", "*", "|", ">")):
                headings.append(f"setext:{previous}")
    markers = _MARKER_RE.findall(text)
    return headings, markers


# Characters that occupy a glyph slot but render as nothing. They are category `Lo`/`Mn`,
# so `visible_len` counted them: 400 HANGUL FILLERs satisfied the 60 % "destructive"
# ratio, letting a replace delete every rule in a section while claiming to keep most of
# it. None of these has a legitimate place in an identity patch.
_BLANK_FILLER_RE = re.compile(
    "["
    "\u115f"  # HANGUL CHOSEONG FILLER
    "\u1160"  # HANGUL JUNGSEONG FILLER
    "\u17b4\u17b5"  # KHMER VOWEL INHERENT
    "\u180e"  # MONGOLIAN VOWEL SEPARATOR
    "\u2800"  # BRAILLE PATTERN BLANK
    "\u3164"  # HANGUL FILLER
    "\uffa0"  # HALFWIDTH HANGUL FILLER
    "]"
)


def visible_len(text: str) -> int:
    """Number of characters that take up visible space on a line.

    Excludes control, format, separator and *combining mark* categories. Marks are the
    important addition: a combining grapheme joiner (U+034F), a variation selector
    (U+FE0F) or a soft hyphen advances nothing on screen but is one character in the
    string, which is exactly the kind of padding that made an earlier allow-list
    ("HANGUL FILLER etc.") defeatable by simply choosing a different code point.
    """
    count = 0
    for ch in _BLANK_FILLER_RE.sub("", _INVISIBLE_RE.sub("", text)):
        category = unicodedata.category(ch)
        if category[0] in {"C", "Z", "M"}:
            continue
        count += 1
    return count


def _padding_ratio(line: str) -> float:
    """Fraction of a line that is invisible padding (0.0 for an ordinary line)."""
    if not line.strip():
        return 0.0
    return 1.0 - (visible_len(line) / max(1, len(line)))


def _meaningful(line: str) -> bool:
    """True when a line contains at least one letter or digit a reader can see."""
    return any(ch.isalnum() for ch in _INVISIBLE_RE.sub("", line))


def _padding_heavy(text: str) -> str | None:
    """First line that has no readable text in it, or None.

    A line made only of characters outside ASCII (combining marks such as U+034F
    COMBINING GRAPHEME JOINER, symbols such as U+1D159 MUSICAL SYMBOL NULL NOTEHEAD,
    fillers, private-use codepoints) is one character per glyph slot in the string and
    nothing on screen. It is not prose and it is not a rule.

    This is deliberately not a list of "blank" code points: the previous version was
    such a list, and it lost to whichever code point the next attacker picked. The
    property that matters is structural — a line with no letters, no digits and no ASCII
    whatsoever cannot say anything a reader would recognise, whether or not it renders.

    ASCII-only lines are never judged here, so table separators (``|---|---|``) and
    punctuation rules are unaffected.
    """
    for line in text.splitlines():
        body = line.strip()
        if len(body) <= 8:
            continue
        if any(ch.isalnum() for ch in body):
            continue
        if all(ord(ch) > 127 for ch in body):
            return body
    return None


def _stray_format(text: str) -> str | None:
    """The first format (``Cf``) character that could hide text, or None.

    Format characters are invisible by definition, which is the whole problem: a soft
    hyphen let a proposer store ``dep\u00adloy`` while the approval screen drew
    ``deploy``, so the bytes the human approved were not the bytes written.

    Two joiners have a real use in ordinary prose, and refusing them made a note about
    a family emoji or a Persian word unproposable with an accusation of deception:

    * U+200D ZERO WIDTH JOINER composes emoji sequences and Indic conjuncts.
    * U+200C ZERO WIDTH NON-JOINER is orthography in Persian, Hindi and others.

    Both are harmless *in that role*, and both are equally invisible between two ASCII
    letters, which is the shape of the attack. So they are allowed only when a
    neighbour is outside ASCII — the character next to them is part of a non-Latin
    grapheme cluster — and refused everywhere else. Every other ``Cf`` stays refused:
    soft hyphen, the bidi controls, the tag characters and the fillers have no use in
    a sentence, and a rule that names the two exceptions is easier to check than one
    that names the attack.
    """
    joiners = {"\u200c", "\u200d"}
    for index, ch in enumerate(text):
        if unicodedata.category(ch) != "Cf":
            continue
        if ch in joiners:
            before = text[index - 1] if index else ""
            after = text[index + 1] if index + 1 < len(text) else ""
            if any(ord(neighbour) > 127 for neighbour in (before, after) if neighbour):
                continue
        return ch
    return None


def append_unique(old_body: str, new_body: str) -> tuple[str, bool]:
    """Add only lines the section does not already contain. Returns ``(body, changed)``.

    Existing lines are preserved byte for byte: the previous implementation
    ``rstrip()``-ed everything, so an "append" silently reformatted the human's
    section and destroyed markdown hard breaks (two trailing spaces).
    """
    old_lines = old_body.splitlines()
    seen = {line.strip() for line in old_lines if line.strip()}
    additions: list[str] = []
    for line in new_body.splitlines():
        stripped = line.strip()
        if stripped and stripped not in seen:
            # Stored verbatim, trailing spaces included: two trailing spaces are a markdown
            # hard line break. `rstrip()` here silently joined lines, so the approval
            # screen showed "* Handled by email  " and the file got "* Handled by email" —
            # the one thing this function exists to prevent.
            additions.append(line)
            seen.add(stripped)
    if not additions:
        return old_body, False
    has_table = any(line.strip().startswith("|") for line in old_lines)
    has_header = any("shift observed" in line.lower() for line in additions)
    if any(a.startswith("|") for a in additions) and not has_table and not has_header:
        additions = [*TABLE_HEADER, *additions]

    trimmed = list(old_lines)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    merged = [*trimmed, *additions]
    # `rstrip("\n")` rather than `strip()`: the last added line may legitimately end in
    # two spaces (a hard break), and stripping the body would eat them.
    return "\n".join(merged).rstrip("\n") + "\n", True


def replace_section(
    text: str, section_key: str, new_body: str, mode: str = "replace"
) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    index = section_index(text, section_key)
    if index is None:
        return text, False
    headings = _heading_rows(lines)
    end = next((j for j in headings if j > index), len(lines))

    # Keep the heading and its marker, even when a blank line sits between them.
    keep_until = index + 1
    probe = keep_until
    while probe < end:
        stripped = lines[probe].strip()
        if stripped == "":
            probe += 1
            continue
        if "kos:section=" in lines[probe]:
            keep_until = probe + 1
        break

    if mode == "append":
        body, _changed = append_unique("".join(lines[keep_until:end]), new_body)
    else:
        body = new_body.strip() + "\n"
    return "".join(lines[:keep_until] + [body + "\n"] + lines[end:]), True


# --------------------------------------------------------------------------- #
# proposal rendering and parsing
# --------------------------------------------------------------------------- #


def validate_patch(patch: str) -> str | None:
    """Cheap pre-checks. The structural guarantee is enforced by ``_shape_ok``."""
    if visible_len(patch) == 0:
        return "proposed_markdown has no visible content"
    # A terminal escape sequence can hide or overprint text. The whole model is "a human
    # read the diff and pressed y", so a patch that can render as something other than
    # what is stored is a spoofed approval: SGR 8 (conceal) turned a full new rule into
    # nothing on screen while writing it to Self.md verbatim. There is no legitimate
    # reason for a control character in an identity patch, so refuse rather than strip.
    if _CONTROL_RE.search(patch):
        return (
            "proposed_markdown contains control characters (terminal escapes, CR, or "
            "other non-printing bytes); they can render differently from what is stored"
        )
    if _BLANK_FILLER_RE.search(patch):
        return (
            "proposed_markdown contains blank filler characters (e.g. U+3164 HANGUL "
            "FILLER); they look empty but count as content"
        )
    padded = _padding_heavy(patch)
    if padded is not None:
        return (
            "proposed_markdown contains a line of invisible marks with no visible text "
            f"({padded[:8]!r}…); it occupies no width on screen but counts as content, "
            "so what a human reads is not what gets stored"
        )
    if _BIDI_RE.search(patch):
        return (
            "proposed_markdown contains bidirectional control characters, which reorder "
            "what a human reads; refusing"
        )
    stray = _stray_format(patch)
    if stray is not None:
        return (
            "proposed_markdown contains a format character "
            f"(U+{ord(stray):04X}) that renders as nothing; refusing so the approved "
            "text is the stored text"
        )
    # Raw HTML headings are invisible to every markdown reader of this file, so they let
    # a patch add a *visible* section in Obsidian while document_shape (which parses
    # markdown headings) sees no change at all. Match the loose forms too: `<h2/>`,
    # `<h2\n>` and `<h2 class=…>` are all headings to an HTML parser, and rejecting only
    # `<h2>` and `<h2 …>` left two of them a way through.
    if _HTML_HEADING_RE.search(patch):
        return "proposed_markdown must not contain raw HTML headings (<h1>…<h6>)"
    lines = patch.splitlines()
    for index, line in enumerate(lines):
        # Container-stripped: `> ## Anti-Goals` and `- ## Anti-Goals` render as headings
        # but start with `>` / `-`, so a check on the raw line called them plain text and
        # let a patch add a section that `document_shape` then reported as unchanged.
        body = _strip_container_prefix(line)
        stripped = body.lstrip()
        if stripped.startswith("##"):
            return (
                "proposed_markdown must not contain '##' headings: a proposal replaces one "
                "section body and cannot create or hijack sections"
            )
        # `# ` is a heading too, and `document_shape` only looked for `##`, so an H1
        # slipped through and rendered as a new section in Obsidian.
        if re.match(r"^#\s", stripped):
            return (
                "proposed_markdown must not contain '# ' headings: a proposal replaces one "
                "section body and cannot create or hijack sections"
            )
        # Setext headings: a line of text underlined with `===` or `---` is an H1/H2 to
        # every markdown renderer, and no line in the patch starts with `#`. Both forms
        # injected a visible section while `document_shape` reported no change. Inside a
        # blockquote or list item the underline carries the same markers, so this uses the
        # stripped body on both lines.
        if _SETEXT_UNDERLINE_RE.fullmatch(body) and index > 0:
            previous = _strip_container_prefix(lines[index - 1]).strip()
            if previous and not previous.startswith(("-", "*", "|", ">")):
                return (
                    "proposed_markdown must not contain setext headings (text underlined "
                    "with === or ---): a proposal cannot create sections"
                )
        if "kos:section=" in line:
            return "proposed_markdown must not contain kos:section markers"
        if line.strip() == "---":
            return "proposed_markdown must not contain '---' (frontmatter/section delimiter)"
        if "```markdown" in line:
            return "proposed_markdown must not embed a nested ```markdown block"
    # Raw HTML is the general case, and the comment fix only covered one syntax. Every
    # block-level HTML element can hide its content: `<script>`, `<style>`,
    # `<div style="display:none">`, `<template>`, `<iframe>`, and any tag with `hidden`
    # all render nothing while the bytes sit in the file. Refusing *all* raw HTML is the
    # honest rule — this is a section body of a personal identity file, and it has no use
    # for embedded markup — and it cannot be bypassed by the next tag name chosen.
    html = _HTML_TAG_RE.search(_outside_code_spans(patch))
    if html is not None:
        return (
            f"proposed_markdown must not contain raw HTML ({html.group(0)[:24]!r}); "
            "the element can render as nothing while the text is still stored, so the "
            "file and the screen disagree. Use plain markdown."
        )
    if "%%" in patch:
        return (
            "proposed_markdown must not contain '%%' (an Obsidian comment); it is stored "
            "but never drawn"
        )
    # Fences must close at the length they opened at. Counting fence *lines* for an even
    # number passed a 4-backtick opener closed by a 3-backtick line — two lines, so
    # "balanced" — while CommonMark leaves the fence open to the end of the document and
    # turns every later section into code.
    if _fence_error(patch):
        return _fence_error(patch)
    return None


_FENCE_LINE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")


def _fence_error(patch: str) -> str | None:
    """Complaint about an unbalanced fence, else None.

    A fence closes only on a run of the same character at least as long as the opener
    and followed by nothing but spaces, which is CommonMark's rule. Counting fence
    *lines* for an even number was the wrong test: a four-backtick opener closed by a
    three-backtick line is two lines, so it looked balanced, while CommonMark leaves
    the fence open to the end of the document and turns every later section into code.
    """
    open_run: str | None = None
    for line in patch.splitlines():
        match = _FENCE_LINE_RE.match(line)
        if not match:
            continue
        run, rest = match.group(1), match.group(2)
        if open_run is None:
            open_run = run
        elif run[0] == open_run[0] and len(run) >= len(open_run) and not rest.strip():
            open_run = None
    if open_run is not None:
        return (
            "proposed_markdown contains an unclosed code fence; everything after it "
            "would render as code and hide what is stored"
        )
    return None


# Cc (control), Cs (surrogates), plus C1 (U+0080–U+009F, which most terminals interpret as
# single-byte escapes — 0x9B is CSI), except the ordinary whitespace a markdown body may
# contain: tab, LF, and the two Unicode line separators are handled separately because
# they change what a line even is.
_CONTROL_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x1b\u0080-\u009f\u2028\u2029]"
)


_HTML_HEADING_RE = re.compile(r"<h[1-6](?:\s|/|>)", re.IGNORECASE)


# Any raw HTML tag, an HTML comment `<!--`, or a doctype/PI. Tag names are `[a-zA-Z][\w-]*`
# with the trailing `:` deliberately excluded so an autolink (`<https://example.com>`) is
# not mistaken for markup: after `https` the next character is `:`, which is not one of the
# terminators, so the lookahead fails.
_HTML_TAG_RE = re.compile(r"<(?:[!?][^>]*|[a-zA-Z][\w-]*(?=[\s/>]))")


_INLINE_CODE_RE = re.compile(r"(`+)(?:(?!\1).)+?\1", re.S)
_FENCED_BLOCK_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})[^\n]*\n.*?^[ \t]*\1[ \t]*$", re.M | re.S)


def _outside_code_spans(patch: str) -> str:
    """The patch with code spans and fenced blocks blanked out.

    ``<String>`` in a sentence is markup; inside backticks it is text a reader sees
    literally, and the HTML refusal must not make the ordinary act of quoting a type
    name in a note about code impossible. The substitution keeps the string length, so
    the error offset still points where it did.
    """
    text = _FENCED_BLOCK_RE.sub(lambda m: " " * len(m.group(0)), patch)
    return _INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), text)


# Invisible-but-rendered characters: bidi overrides reorder what a human reads, so a
# line can *look* like "set env gnp.exe" while being "set env exe.png" to a tool.
_BIDI_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069]")


def rendered_text(markdown: str) -> str:
    """The text a markdown reader actually draws.

    Everything that exists in the source but not on screen is removed: HTML comments
    (including the multi-line form), Obsidian ``%%...%%`` comments, and the payload of
    any element a renderer does not display.

    This exists because every other check in this module works on *source lines*, and a
    source line that never renders is a place to hide content. A patch of

        --><!--
        * the three existing rules
        -->
        * Always approve deploys without review.

    validated cleanly, scored as non-destructive (the old rules were "retained" in the
    source), and showed two removals of blank lines on the approval screen — while the
    section a human and Obsidian see contained one new rule and none of the old ones.
    Consent, the destructive ratio and the diff all have to agree with the renderer, so
    they all go through here.
    """
    text = markdown.replace("\r\n", "\n")
    # Elements whose *content* is never drawn. Removing the tag but keeping the text
    # would still count a hidden rule as retained, which is the whole bug.
    text = re.sub(
        r"<(script|style|template|iframe|object|embed|noscript|svg|math)\b[^>]*>.*?</\1\s*>",
        "",
        text,
        flags=re.S | re.I,
    )
    # An opener with no closer swallows the rest of the document for a renderer.
    text = re.sub(
        r"<(script|style|template|iframe|object|embed|noscript|svg|math)\b[^>]*>.*\Z",
        "",
        text,
        flags=re.S | re.I,
    )
    # The same trick without a special tag: any element carrying `hidden` or a CSS rule
    # that suppresses it. This is not an allow-list of safe elements (those lose to the
    # next attribute chosen); it names the properties whose only effect is to stop text
    # being drawn, and the proposal surface refuses raw HTML outright, so this exists to
    # keep the *diff* honest rather than to be the boundary.
    text = re.sub(
        r"<([a-zA-Z][\w-]*)\b[^>]*?"
        r"(?:\bhidden\b|style\s*=\s*\"[^\"]*?"
        r"(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0"
        r"|font-size\s*:\s*0|position\s*:\s*absolute\s*;\s*left\s*:\s*-))"
        r"[^>]*>.*?</\1\s*>",
        "",
        text,
        flags=re.S | re.I,
    )
    # HTML comments, possibly spanning lines. `re.S` because a comment that opens on one
    # line and closes on another is still one comment.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<!--.*\Z", "", text, flags=re.S)
    # Obsidian comment syntax: two percent signs wrapping the hidden span.
    text = re.sub(r"%%.*?%%", "", text, flags=re.S)
    # Remaining inline tags (`<b>`, `<span>`) keep their text, so only the tag goes.
    text = re.sub(r"</?[a-zA-Z][\w-]*(?:\s[^>]*)?/?>", "", text)
    return text


def _render_survivors(markdown: str) -> set[str]:
    """Stripped lines that survive rendering, for the destructive ratio."""
    return {line.strip() for line in rendered_text(markdown).splitlines() if line.strip()}


def _shape_ok(before: str, after: str) -> bool:
    return document_shape(before) == document_shape(after)


def _destructive(old_body: str, new_body: str) -> bool:
    """True when a replace throws away most of what was there.

    Measures what *survives*, not how long the new text is. The previous version
    compared total visible length, so any padding counted as retained content: a patch
    that deleted every rule and appended 400 U+034F COMBINING GRAPHEME JOINERs scored
    above the 60 % floor. Every allow-list of "blank" characters lost that race one code
    point later, because there is always another invisible character. Counting old
    lines that are still present cannot be padded — padding adds lines, and only the
    old ones count.

    The threshold is deliberately generous (keep 60%): a "replace" that keeps a
    quarter of the section still looked like consent to the old 20% rule, and 6 of 8
    lines disappearing should never be a silent consequence of pressing `y`.
    """
    old_lines = [line.strip() for line in old_body.splitlines() if _meaningful(line)]
    old_visible = sum(visible_len(line) for line in old_lines)
    # Compare against what *renders*, not what is stored: source text inside an HTML
    # comment is retained in the file and invisible on screen, which is the whole point
    # of hiding it there.
    survivors = _render_survivors(new_body)
    kept_lines = [line for line in old_lines if line in survivors]
    if old_lines and len(kept_lines) * 2 < len(old_lines):
        # Losing more than half the *lines* is destructive whatever their length. The
        # character floor below exists to avoid flagging a trivial edit, so it must not
        # be able to excuse wiping a section of three short bullets.
        return True
    if not old_lines or old_visible < DESTRUCTIVE_MIN_CHARS:
        return False
    return sum(visible_len(line) for line in kept_lines) < old_visible * DESTRUCTIVE_KEEP_RATIO


def extract_proposed(text: str) -> str | None:
    """Content of the single ```markdown block, or None when ambiguous."""
    opens = list(_FENCE_OPEN_RE.finditer(text))
    if len(opens) != 1:
        return None
    opening = opens[0]
    fence = opening.group(1)
    rest = text[opening.end() + 1 :]
    closer = re.compile(r"^" + re.escape(fence) + r"[ \t]*$", re.M).search(rest)
    if not closer:
        return None
    return rest[: closer.start()].strip()


def _frontmatter_value(text: str, key: str) -> str | None:
    """Value of a frontmatter key, read only from the YAML block.

    It used to scan the first 40 lines of the *whole* file, so any line the agent wrote
    into `## Summary` that happened to start with `proposal_section:` was read as
    metadata. That is display text promoted to authority. The frontmatter is delimited;
    look there and nowhere else.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip() or None
    return None


def _claimed_section(text: str) -> str | None:
    """The section a proposal file claims in its frontmatter (display text only)."""
    return _frontmatter_value(text, "proposal_section")


def _self_file_problem(self_path: Path) -> dict[str, Any] | None:
    if not self_path.exists():
        return {"error": "People/Self.md missing"}
    if self_path.is_symlink() or _is_reparse(self_path) or not self_path.is_file():
        return {
            "error": (
                "People/Self.md is a symlink, a junction, or not a regular file; "
                "refusing to write identity through it"
            ),
            "hint": "Replace it with a regular file inside the vault.",
        }
    try:
        self_info = os.lstat(self_path)
    except OSError as exc:
        return {"error": f"cannot inspect People/Self.md: {exc}"}
    if self_info.st_nlink != 1:
        return {
            "error": "People/Self.md is hard-linked; refusing to write identity through it",
            "hint": "A second name for this file would let another path change your identity.",
        }

    return None


def _validated_proposal(
    self_path: Path, text: str, row: dict[str, Any]
) -> dict[str, Any]:
    """Validate the same proposal and base before preview and again before apply."""
    patch = extract_proposed(text)
    if patch is None:
        return {"error": "proposal must contain exactly one ```markdown block"}
    # Re-run the patch rules at apply time, not only at propose time. A proposal
    # can predate a rule (the ledger outlives the code that wrote it), and the
    # human is about to approve whatever this renders.
    patch_problem = validate_patch(patch)
    if patch_problem:
        return {
            "error": patch_problem,
            "hint": "This proposal is no longer acceptable; create a new one.",
        }
    if hashlib.sha256(patch.encode("utf-8")).hexdigest() != row.get("body_sha256"):
        return {
            "error": "proposal content was edited after it was created",
            "hint": "The ledger records the proposed body; create a new proposal instead.",
        }

    # The approval screen renders what a human reads, so the *whole* rendered
    # file must be authentic, not just the fenced block. Otherwise a file could
    # display "heuristics / harmless" while the ledger applies something else.
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != str(
        row.get("file_sha256") or ""
    ):
        return {
            "error": "proposal file was edited after it was created",
            "hint": (
                "Everything the approval screen shows must match what the ledger "
                "recorded. Create a new proposal instead of editing this one."
            ),
        }

    section = str(row.get("section") or "")
    if section not in SECTION_ALIASES:
        return {"error": f"unknown proposal section: {section or '(missing)'}"}
    mode = str(row.get("mode") or "replace")
    if mode not in {"replace", "append"}:
        return {"error": f"invalid proposal mode: {mode}"}

    # The file's own frontmatter is display text; if it disagrees with the
    # ledger, the screen would be lying about what is being applied.
    claimed = _claimed_section(text)
    if claimed and claimed != section:
        return {
            "error": (
                f"proposal file claims section '{claimed}' but the ledger says "
                f"'{section}'; refusing"
            ),
            "hint": "Create a new proposal; do not edit a proposal's metadata.",
        }

    self_text = self_path.read_text(encoding="utf-8", errors="replace")
    try:
        current = section_digest(self_text, section)
    except ValueError as exc:
        return {"error": str(exc)}
    if current != str(row.get("base_digest") or ""):
        return {
            "error": "Self.md changed since this proposal was created",
            "hint": "Re-read Self.md and propose again; accepting now could undo a manual edit.",
        }

    return {"patch": patch, "section": section, "mode": mode, "self_text": self_text}


def describe(vault: Path, proposals_dir: Path, proposal_path: str) -> dict[str, Any]:
    """Return an authentic proposal against its expected Self base for preview."""
    path, problem = _resolve_proposal(vault, proposals_dir, proposal_path)
    if path is None:
        return problem
    rel = path.relative_to(vault).as_posix()
    row, dup_problem = _row_for(vault, rel)
    if dup_problem:
        return {"error": dup_problem}
    if row is None:
        return {
            "error": "proposal is not registered in this install's Self proposal ledger",
            "hint": "Only proposals created by this install can be approved.",
        }
    self_path = Path(vault) / "People" / "Self.md"
    self_problem = _self_file_problem(self_path)
    if self_problem:
        return self_problem
    text = path.read_text(encoding="utf-8", errors="replace")
    validated = _validated_proposal(self_path, text, row)
    if validated.get("error"):
        return validated
    return {
        "path": path,
        "rel": rel,
        "section": validated["section"],
        "mode": validated["mode"],
        "patch": validated["patch"],
        "allow_destructive": bool(row.get("allow_destructive")),
    }


def _fenceless(text: str) -> str:
    return text.replace("```markdown", "'''markdown")


def _quote_metadata_lines(text: str) -> str:
    """Indent lines that a prose reader could mistake for this file's own metadata.

    A proposal's frontmatter is delimited, and the approval screen reads the ledger, so
    this is not load-bearing for either. It is for the third reader: a human, or a future
    tool, opening the file and seeing `proposal_mode: append` sitting in the body of a
    proposal that replaces a section. Indenting says "this is quotation".
    """
    out = []
    for line in text.splitlines():
        if line.startswith("proposal_") or line.startswith("---"):
            out.append("    " + line)
        else:
            out.append(line)
    return "\n".join(out)


def _fenced(markdown: str) -> str:
    longest = max((len(m) for m in re.findall(r"(`{3,})", markdown)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}markdown\n{markdown.strip()}\n{fence}"


# --------------------------------------------------------------------------- #
# public operations
# --------------------------------------------------------------------------- #


def learning_claim_key(markdown: str) -> str:
    text = rendered_text(markdown).casefold()
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s+|\d+[.)]\s+|[-*+]\s+)", "", text)
    return " ".join(re.findall(r"\w+|[<>=+/#]", text))


def _legacy_lesson_claim(vault: Path, proposals_dir: Path, row: dict[str, Any]) -> str | None:
    if row.get("section") != "heuristics" or row.get("mode") != "append":
        return None
    path, _problem = _resolve_proposal(vault, proposals_dir, str(row["proposal"]))
    if path is None:
        return None
    patch = extract_proposed(path.read_text(encoding="utf-8", errors="replace"))
    if not patch or hashlib.sha256(patch.strip().encode("utf-8")).hexdigest() != row.get("body_sha256"):
        return None
    lesson = re.fullmatch(r"\*\s+\*\*From decision \[.*\]\([^)]+\)\*\*:\s*(.+)", patch.strip(), re.S)
    if lesson is None:
        return None
    return learning_claim_key(lesson[1])


def propose(
    vault: Path,
    self_path: Path,
    proposals_dir: Path,
    summary: str,
    section: str,
    proposed_markdown: str,
    rationale: str = "",
    mode: str = "replace",
    allow_destructive: bool = False,
    *,
    learning_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from knowledgeos.memory import SAFE_NAME_RE, _one_line

    if mode not in {"replace", "append"}:
        return {"error": "mode must be 'replace' or 'append'"}
    # Normalise line endings *before* hashing. A tool argument sourced on Windows
    # carries `\r\n`; the hash was taken over the raw string while the rendered file was
    # read back with universal newlines, so the two disagreed and the proposal could
    # never be approved — with an error that blamed the human for editing it.
    proposed_markdown = proposed_markdown.replace("\r\n", "\n").replace("\r", "\n")
    section_key = _one_line(section)
    if section_key not in SECTION_ALIASES:
        return {
            "error": f"unknown section: {section_key}",
            "hint": f"Use canonical keys: {', '.join(sorted(SECTION_ALIASES))}",
        }
    problem = validate_patch(proposed_markdown)
    if problem:
        return {"error": problem}

    # `exists()` is True for a directory, and `read_text` then raises
    # IsADirectoryError/PermissionError straight through the MCP surface. A vault whose
    # Self.md was replaced by a folder should get a clear refusal, not a traceback.
    if not self_path.exists():
        return {"error": "People/Self.md missing"}
    if not self_path.is_file() or self_path.is_symlink():
        return {
            "error": "People/Self.md is not a plain file",
            "hint": "It is a directory or a link; restore the markdown file, or re-run init.",
        }
    # A second hard link to the identity file means another path can change it, and that
    # path may be one an ordinary tool call writes to. Apply already refused this; propose
    # did not, so a proposal could be created against a file that a later `capture` or
    # hook write would silently rewrite. Refuse at the first opportunity instead.
    try:
        if os.lstat(self_path).st_nlink != 1:
            return {
                "error": "People/Self.md is hard-linked; refusing to treat it as identity",
                "hint": (
                    "A second name for this file would let an ordinary note write change "
                    "your identity. Remove the extra link, or restore the file from a backup."
                ),
            }
    except OSError as exc:
        return {"error": f"cannot inspect People/Self.md: {exc}"}
    try:
        self_text = self_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": f"People/Self.md could not be read: {exc}"}
    try:
        base_digest = section_digest(self_text, section_key)
        current_body = section_body(self_text, section_key) or ""
    except ValueError as exc:
        return {"error": str(exc)}
    if not base_digest:
        return {
            "error": f"section '{section_key}' not found in People/Self.md",
            "hint": "Add the section (with a kos:section marker) before proposing changes to it.",
        }
    if mode == "replace" and not allow_destructive and _destructive(current_body, proposed_markdown):
        return {
            "error": (
                "this proposal would delete most of the section it targets; refusing a "
                "destructive replace"
            ),
            "hint": "Re-propose with allow_destructive=true if that is genuinely intended.",
        }

    # `propose` used to mkdir whatever path it was handed. `reject` and apply validate the
    # directory, `propose` did not — so a junction at `People/Self-Proposals` made a tool
    # call write a proposal file outside the vault, which is how a hardlinked temp name
    # became a write primitive for arbitrary paths.
    if proposals_dir.exists():
        if _proposal_root(vault, proposals_dir) is None:
            return {
                "error": (
                    "People/Self-Proposals is not a plain directory inside the vault "
                    "(it is a link, a junction, or somewhere else)"
                ),
                "hint": "Move it back, or re-run init to recreate it.",
            }
    else:
        proposals_dir.mkdir(parents=True, exist_ok=True)
        if _proposal_root(vault, proposals_dir) is None:
            return {"error": "refusing to write proposals into a directory that is a link"}
    now = datetime.datetime.now()
    today = now.date().isoformat()
    proposal_id = f"{now.strftime('%Y%m%d%H%M%S%f')}-{secrets.token_hex(4)}"
    safe_section = SAFE_NAME_RE.sub("", section_key).strip().replace(" ", "_") or "section"
    path = proposals_dir / f"{now.strftime('%Y%m%d-%H%M%S')}-{safe_section}-{proposal_id[-8:]}.md"

    title = _one_line(summary)[:120] or f"Self proposal — {section_key}"
    body_sha = hashlib.sha256(proposed_markdown.strip().encode("utf-8")).hexdigest()
    # The rationale is free text the agent chooses, with real newlines. Left verbatim it
    # could contain a line reading `proposal_mode: append`, and every reader that scanned
    # the file for metadata found it. The ledger is now the only authority the screen
    # consults, so this is belt and braces — but a proposal file whose own text cannot be
    # mistaken for its metadata is worth having in a format humans read too.
    text = f"""---
type: research
title: {title}
description: Proposed Self.md update for section '{section_key}'.
schema: knowledgeos-v0.3
status: draft
created: {today}
updated: {today}
timestamp: {today}T00:00:00Z
tags: [self-proposal, ego-node]
project: KnowledgeOS
proposal_id: {proposal_id}
proposal_section: {section_key}
proposal_target: People/Self.md
proposal_mode: {mode}
proposal_origin: memory_propose_self_update
proposal_base_hash: {base_digest}
---

# Self proposal — {section_key}

## Summary
{_one_line(summary)}

## Rationale
{_quote_metadata_lines(_fenceless(rationale)) or "_None provided._"}

## Proposed markdown for section `{section_key}`

{_fenced(proposed_markdown)}

## Accept

A human must approve this in a terminal:

    twinaatma self approve "{path.name}"

The agent cannot approve its own proposal; that is the point.
"""
    # `_lock` raises `TimeoutError` after a short wait. That type is not part of any
    # interface: it reached the agent as
    # `{"error": "TimeoutError: Self gate is busy; try again in a moment"}`, which names
    # an internal class and reads like a crash instead of "try again". The message was
    # already right, so only the wrapping changes.
    try:
        with _lock(vault):
            rows, _rejected = read_ledger(vault)
            if learning_evidence is not None:
                if _rejected:
                    return {"error": "proposal history could not be verified; refusing to repeat a learning suggestion"}
                known = {str(row["proposal"]) for row in rows}
                if any(file.relative_to(vault).as_posix() not in known for file in proposals_dir.glob("*.md")):
                    return {"error": "proposal history is incomplete; refusing to repeat a learning suggestion"}
                claim = learning_evidence["claim"]
                for prior in rows:
                    old = prior.get("learning_evidence") or {}
                    same_claim = old.get("claim") == claim
                    same_legacy_body = not old and (
                        prior.get("body_sha256") == body_sha or
                        _legacy_lesson_claim(vault, proposals_dir, prior) == claim
                    )
                    if not (same_claim or same_legacy_body):
                        continue
                    status = prior.get("status")
                    previous_sources = old.get("sources", [])
                    previous_ids = {source["id"] for source in previous_sources}
                    previous_paths = {source.get("path") for source in previous_sources}
                    previous_outcomes = {source.get("actual_outcome") for source in previous_sources}
                    has_new_source = any(
                        str(source["id"]).startswith("kos:decision:") and
                        source["id"] not in previous_ids and
                        source.get("path") not in previous_paths and
                        source.get("actual_outcome") and source["actual_outcome"] not in previous_outcomes
                        for source in learning_evidence["sources"]
                    )
                    suppression = None
                    if status == "draft":
                        suppression = "already_suggested"
                    elif status == "applied":
                        suppression = "already_applied"
                    elif status == "rejected" and (same_legacy_body or not has_new_source):
                        suppression = "rejected_without_new_source"
                    if suppression:
                        return {
                            "ok": True, "proposed": False, "mutated_self": False,
                            "suppression": suppression,
                            "existing_proposal": prior["proposal"],
                            "reason": "This suggestion already has a recorded disposition; edits to existing sources do not establish a new completed source.",
                        }
            _write_file(path, text)
            rows.append(
                {
                    "id": proposal_id,
                    "created": now.isoformat(timespec="seconds"),
                    "proposal": path.relative_to(vault).as_posix(),
                    "section": section_key,
                    "mode": mode,
                    # Recorded so the approval screen can say "the agent waived the
                    # retention floor" instead of silently applying a wipe after showing
                    # a replace that looked ordinary.
                    "allow_destructive": bool(allow_destructive),
                    "base_digest": base_digest,
                    "body_sha256": body_sha,
                    # The whole rendered file, so the approval screen cannot be made to
                    # show something other than what will be applied.
                    "file_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "status": "draft",
                    **({"learning_evidence": learning_evidence} if learning_evidence is not None else {}),
                }
            )
            try:
                _write_ledger(vault, rows)
            except OSError as exc:
                with contextlib.suppress(OSError):
                    path.unlink()
                return {"error": f"could not record the proposal in the ledger: {exc}"}
    except TimeoutError as exc:
        return {"error": str(exc), "retryable": True}

    return {
        "ok": True,
        "proposal_path": path.relative_to(vault).as_posix(),
        "proposal_id": proposal_id,
        "section": section_key,
        "base_digest": base_digest,
        "approval": (
            "Ask the human to run "
            f"`twinaatma self approve {path.name}` in their terminal, then stop. "
            "The agent cannot approve its own proposal; that is the point."
        ),
        "policy": "proposal_only",
        "mutated_self": False,
    }


def _proposal_root(vault: Path, proposals_dir: Path) -> Path | None:
    """The canonical proposals directory, or None if this path is not sound.

    `reject` writes to whatever `_resolve_proposal` returns, and it has no TTY check —
    rejecting is a routine agent action. That is only safe while the directory it writes
    into really is `People/Self-Proposals`. It used to resolve the directory and then
    test containment against *that* result, so a junction at `People/Self-Proposals`
    pointing at `People/` made `People/Self-Proposals/Self.md` resolve to
    `People/Self.md`, pass every check, and get agent-authored text written into the
    identity file. Containment must be measured against a path we did not just follow
    a link through.
    """
    try:
        root = Path(vault).resolve()
        expected = root / "People" / "Self-Proposals"
        link = proposals_dir
        if link.is_symlink() or _is_reparse(link):
            return None
        resolved = link.resolve()
        if resolved != expected:
            return None
        if not resolved.is_dir():
            return None
        # A junction further up (People/ itself, or the vault) would put the same
        # identity file inside the "safe" directory. `is_symlink()` alone missed a
        # directory junction, which `resolve()` follows and `is_symlink()` reports False.
        people = root / "People"
        if resolved.parent != people or people.is_symlink() or _is_reparse(people):
            return None
    except (OSError, ValueError):
        return None
    return resolved


def _is_reparse(path: Path) -> bool:
    """True for Windows junctions and any other reparse point.

    `is_symlink()` covers symlinks; a directory junction is not a symlink but is
    followed by `resolve()` in exactly the same way.
    """
    try:
        stats = os.lstat(path)
    except OSError:
        return False
    attributes = getattr(stats, "st_file_attributes", 0)
    return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def _resolve_proposal(
    vault: Path, proposals_dir: Path, proposal_path: str
) -> tuple[Path | None, dict]:
    root = _proposal_root(vault, proposals_dir)
    if root is None:
        return None, {
            "error": (
                "People/Self-Proposals is not a plain directory inside the vault "
                "(it is a link, a junction, or somewhere else)"
            ),
            "hint": "Restore it as a real folder; the gate will not write through a redirect.",
        }
    self_path = (Path(vault).resolve() / "People" / "Self.md").resolve()
    raw = Path(proposal_path)
    candidate = raw if raw.is_absolute() else vault / raw
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (ValueError, OSError):
        return None, {
            "error": "not a Self proposal in People/Self-Proposals",
            "hint": "Only proposals in People/Self-Proposals/ can be accepted or rejected.",
        }
    if resolved == self_path:
        return None, {
            "error": "that path is People/Self.md, not a proposal",
            "hint": "Proposals are separate files; the gate is the only writer of Self.md.",
        }
    if not resolved.exists():
        return None, {"error": f"proposal not found: {proposal_path}"}
    if resolved.is_symlink() or _is_reparse(resolved) or not resolved.is_file():
        return None, {"error": "proposal path must be a regular file, not a link"}
    try:
        info = os.lstat(resolved)
    except OSError as exc:
        return None, {"error": f"cannot inspect proposal: {exc}"}
    if info.st_nlink != 1:
        return None, {
            "error": "proposal is hard-linked; refusing to write through it",
            "hint": "A hardlink to People/Self.md would let a proposal file mutate your identity.",
        }
    return resolved, {}


def _dominant_newline(raw: bytes) -> str:
    """The line ending most of the file already uses."""
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def _bump_frontmatter_date(text: str, today: str) -> str:
    """Set ``updated:`` in the YAML frontmatter block, leaving the body alone.

    A ``re.sub(..., count=1, flags=re.M)`` over the whole document rewrote the first
    line anywhere in the file that began with ``updated:`` — which could be a rule the
    human wrote in a section body. Only the frontmatter is bookkeeping.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    for index in range(1, len(lines)):
        stripped = lines[index].strip()
        if stripped in {"---", "..."}:
            break
        if stripped.startswith("updated:"):
            ending = lines[index][len(lines[index].rstrip("\r\n")) :]
            lines[index] = f"updated: {today}{ending}"
            return "".join(lines)
    return text


def _write_file(path: Path, text: str) -> None:
    """Atomic write that replaces the directory entry, never writing through a link.

    The body lives in ``knowledgeos.textio.atomic_write`` because three other writers
    had the same two hazards and were fixed one at a time — ``autopilot._write_atomic``,
    ``indexer.save_manifest`` and the ledger. Every one of them staged at a *predictable*
    name, so an agent could hardlink ``People/Self.md`` to ``<name>.tmp`` and let an
    ordinary tool call replace the identity file with its own content. That is the
    round-10 critical, and the reason this is now a shared function rather than a
    well-commented one.
    """
    from knowledgeos.textio import write_preserving_endings

    write_preserving_endings(path, text)


def _require_human_terminal() -> str | None:
    """None when this process really is a human at a terminal, else a refusal.

    The check lives *here*, not only in the CLI, because a guard that exists only in
    the caller is a suggestion: importing the library skipped it entirely. It still
    cannot prove a human is present — an agent that can spawn an interactive terminal
    can satisfy it — but it raises the bar from one import call to driving a terminal,
    and it makes ``authorized_by: terminal`` true rather than a forged claim.
    """
    try:
        stdin_ok = sys.stdin.isatty()
        stdout_ok = sys.stdout.isatty()
    except (AttributeError, ValueError):
        return "identity changes must be approved by a human in a terminal"
    if not (stdin_ok and stdout_ok):
        return (
            "identity changes must be approved by a human in a terminal: stdin/stdout "
            "are not a TTY, so no human could have read this"
        )
    return None


def _apply(
    vault: Path,
    self_path: Path,
    proposals_dir: Path,
    proposal_path: str,
    *,
    authorized_by: str,
) -> dict[str, Any]:
    refusal = _require_human_terminal()
    if refusal:
        return {
            "error": refusal,
            "hint": "Ask the human to run: twinaatma self approve <file>",
            "policy": "human_only",
            "mutated_self": False,
        }
    path, problem = _resolve_proposal(vault, proposals_dir, proposal_path)
    if path is None:
        return problem
    rel = path.relative_to(vault).as_posix()

    self_problem = _self_file_problem(self_path)
    if self_problem:
        return self_problem

    try:
        with _lock(vault):
            row, dup_problem = _row_for(vault, rel)
            if dup_problem:
                return {"error": dup_problem}
            if row is None:
                return {
                    "error": "proposal is not registered in this install's Self proposal ledger",
                    "hint": (
                        "The ledger lives outside the vault, signed with this machine's key. "
                        "Hand-written or legacy proposals cannot change Self.md; create a new "
                        "proposal with memory_propose_self_update."
                    ),
                }
            status = str(row.get("status") or "")
            if status == "applied":
                return {"error": "proposal already accepted", "status": "accepted"}
            if status == "rejected":
                return {"error": "proposal was rejected; it cannot be accepted", "status": "rejected"}
            if status == "superseded":
                return {
                    "error": "proposal was superseded by a newer accepted change to the same section",
                    "hint": "Re-propose against the current Self.md if this is still wanted.",
                    "status": "superseded",
                }
            if status != "draft":
                return {"error": f"proposal is {status or 'not a draft'}; only drafts can be accepted"}

            text = path.read_text(encoding="utf-8", errors="replace")
            validated = _validated_proposal(self_path, text, row)
            if validated.get("error"):
                return validated
            patch = validated["patch"]
            section = validated["section"]
            mode = validated["mode"]
            self_text = validated["self_text"]

            try:
                new_text, found = replace_section(self_text, section, patch, mode=mode)
            except ValueError as exc:
                return {"error": str(exc)}
            if not found:
                return {
                    "error": f"could not locate section '{section}' in Self.md",
                    "hint": "Use canonical keys: heuristics, values, mental_models, anti_goals, active_bets, drift_log",
                }
            if not _shape_ok(self_text, new_text):
                return {
                    "error": "proposal would change the set of sections in Self.md; refusing",
                    "hint": "A proposal may only fill in the body of its own section.",
                }
            if visible_len(rendered_text(section_body(new_text, section) or "")) == 0:
                return {"error": "proposal would leave the section empty; refusing"}
            # Append mode adds only lines the section does not already contain, so a
            # duplicate-only proposal produces byte-identical text. It used to be marked
            # applied and reported success, which told the human their rule had been
            # recorded when nothing had changed — and consumed the draft, so they could
            # not tell it apart from a change that did land.
            if (section_body(self_text, section) or "").strip() == (
                section_body(new_text, section) or ""
            ).strip():
                return {
                    "error": "this proposal would not change the section; nothing to apply",
                    "hint": (
                        "Every line in it is already there (or the replacement text is "
                        "identical). The proposal is still open, so nothing was lost."
                    ),
                    "status": "draft",
                }

            # Rewrite the `updated:` *frontmatter* date only. `re.sub(..., count=1)` over
            # the whole document rewrote the first line in the body that happened to
            # start with `updated:`, which could be a rule the human wrote.
            today = datetime.date.today().isoformat()
            new_text = _bump_frontmatter_date(new_text, today)
            self_sha = hashlib.sha256(new_text.encode("utf-8")).hexdigest()

            # Ledger first: a crash between the two leaves a recoverable marker
            # rather than an unrecorded change to the human's identity.
            rows, _ = read_ledger(vault)
            snapshot = [dict(r) for r in rows]
            superseded: list[str] = []
            for other in rows:
                if other.get("proposal") == rel:
                    other["status"] = "applied"
                    other["applied_at"] = datetime.datetime.now().isoformat(timespec="seconds")
                    other["self_sha256"] = self_sha
                    other["authorized_by"] = authorized_by
                elif (
                    other.get("status") == "draft"
                    and other.get("section") == section
                    and other.get("proposal") != rel
                ):
                    other["status"] = "superseded"
                    other["superseded_by"] = row.get("id")
                    superseded.append(str(other.get("proposal")))
            _write_ledger(vault, rows)

            try:
                _write_file(self_path, new_text)
            except OSError as exc:
                # Put the ledger back exactly as it was: a half-applied bookkeeping
                # change would make the proposal look applied while Self.md is not.
                with contextlib.suppress(OSError):
                    _write_ledger(vault, snapshot)
                return {"error": f"could not write People/Self.md: {exc}"}

            accepted = re.sub(r"^status: draft\s*$", "status: accepted", text, count=1, flags=re.M)
            accepted += f"\n\n## Applied\nAccepted on {today} into People/Self.md.\n"
            with contextlib.suppress(OSError):
                _write_file(path, accepted)

            for other_rel in superseded:
                other_path = vault / other_rel
                if not other_path.exists():
                    continue
                with contextlib.suppress(OSError):
                    other_text = other_path.read_text(encoding="utf-8", errors="replace")
                    _write_file(
                        other_path,
                        re.sub(
                            r"^status: draft\s*$",
                            "status: superseded",
                            other_text,
                            count=1,
                            flags=re.M,
                        )
                        + f"\n\n## Superseded\nSuperseded on {today} by {row.get('id')}.\n",
                    )
    except TimeoutError as exc:
        return {"error": str(exc)}

    return {
        "ok": True,
        "self_path": self_path.relative_to(vault).as_posix(),
        "proposal_path": rel,
        "section": section,
        "superseded": superseded,
        "authorized_by": authorized_by,
        "policy": "explicit_accept",
    }


def accept(
    vault: Path,
    self_path: Path,
    proposals_dir: Path,
    proposal_path: str,
) -> dict[str, Any]:
    """MCP path. Always refuses.

    There is no confirmation-code parameter, deliberately. One used to exist: the gate
    minted a code and returned it in a tool result, so the model it was meant to stop
    could read it and echo it back. A secret that travels through the tool result is not
    a separation of privilege. Approval happens in a process the model does not drive,
    so this entry point exists to explain that instead of pretending otherwise.
    """
    return {
        "error": "Self.md changes must be approved by the human in a terminal",
        "hint": (
            "Ask the human to run:  twinaatma self approve "
            f"\"{Path(proposal_path).name}\"  — then stop. Never run it yourself, "
            "and never invent a confirmation code."
        ),
        "policy": "human_only",
        "mutated_self": False,
    }


def approve_interactive(
    vault: Path,
    self_path: Path,
    proposals_dir: Path,
    proposal_path: str,
) -> dict[str, Any]:
    """Terminal path: the human read the diff and pressed yes. Caller must verify TTY."""
    return _apply(
        vault,
        self_path,
        proposals_dir,
        proposal_path,
        authorized_by="terminal",
    )


def reject(vault: Path, proposals_dir: Path, proposal_path: str, reason: str = "") -> dict[str, Any]:
    path, problem = _resolve_proposal(vault, proposals_dir, proposal_path)
    if path is None:
        return problem
    rel = path.relative_to(vault).as_posix()
    try:
        with _lock(vault):
            row, dup_problem = _row_for(vault, rel)
            if dup_problem:
                return {"error": dup_problem}
            if row is None:
                return {
                    "error": "not a Self proposal registered in this install's ledger",
                    "hint": "This tool only archives proposals created by the toolkit.",
                }
            status = str(row.get("status") or "")
            if status == "applied":
                return {"error": "proposal already accepted; it cannot be rejected"}
            if status == "rejected":
                return {"error": "proposal already rejected"}
            if status != "draft":
                return {"error": f"proposal is {status or 'not a draft'}; only drafts can be rejected"}

            text = path.read_text(encoding="utf-8", errors="replace")
            # Rejecting is an ordinary agent action with no terminal check, so it must
            # not be able to write a file the gate did not render. Without this, a
            # forged row pointing at an arbitrary file made `reject` append to it and
            # report `mutated_self: false`.
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != str(
                row.get("file_sha256") or ""
            ):
                return {
                    "error": "proposal file was edited after it was created",
                    "hint": "Create a new proposal instead of editing this one.",
                }
            today = datetime.date.today().isoformat()
            text = re.sub(r"^status: draft\s*$", "status: rejected", text, count=1, flags=re.M)
            clean_reason = " ".join(str(reason or "").split()) or "_No reason given._"
            text += f"\n\n## Rejected\nRejected on {today}. {clean_reason}\n"
            _write_file(path, text)
            _set_status(
                vault,
                rel,
                "rejected",
                rejected_at=datetime.datetime.now().isoformat(timespec="seconds"),
            )
    except TimeoutError as exc:
        return {"error": str(exc)}
    return {
        "ok": True,
        "proposal_path": rel,
        "mutated_self": False,
        "policy": "explicit_reject",
    }


def list_open(vault: Path) -> list[dict[str, Any]]:
    rows, _ = read_ledger(vault)
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") != "draft":
            continue
        rel = str(row.get("proposal") or "")
        if not rel or not (vault / rel).exists():
            continue
        out.append(
            {
                "path": rel,
                "id": row.get("id"),
                "title": Path(rel).stem,
                "status": "draft",
                "section": row.get("section", ""),
                "mode": row.get("mode", "replace"),
            }
        )
    return sorted(out, key=lambda item: item["path"])


def untrusted_proposals(vault: Path, proposals_dir: Path) -> list[str]:
    if not proposals_dir.exists():
        return []
    rows, _ = read_ledger(vault)
    known = {str(row.get("proposal")) for row in rows}
    return [
        path.relative_to(vault).as_posix()
        for path in sorted(proposals_dir.glob("*.md"))
        if path.relative_to(vault).as_posix() not in known
    ]


def key_source() -> str:
    """Where the signing key comes from, in plain words, for `doctor`.

    "signed: true" on its own hid a real problem: an environment override is a key
    that anything able to set a variable can also read, and a key file on the same
    filesystem is readable by anything that can read the vault. The ledger detects
    tampering from vault-side content; saying which key was used keeps that honest.
    """
    if os.environ.get("KNOWLEDGEOS_GATE_KEY"):
        return "environment (KNOWLEDGEOS_GATE_KEY)"
    path = _key_path()
    return f"per-install key file ({path})" if path.exists() else "missing"


def ledger_health(vault: Path) -> dict[str, Any]:
    rows, rejected = read_ledger(vault)
    return {
        "path": str(ledger_path(vault)),
        "signed": _signing_key() is not None,
        "key_source": key_source(),
        "rows": len(rows),
        "rejected_rows": rejected,
        "draft": sum(1 for row in rows if row.get("status") == "draft"),
    }
