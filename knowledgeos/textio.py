"""Byte-exact text writing.

``Path.write_text`` opens in text mode, so on Windows every ``\\n`` in the string becomes
``\\r\\n`` on disk. For a file the product generates that is only inconsistent between
platforms; for a file the product *edits*, it is a diff on every line of a file the user
wrote, for a change that touched one. Both are avoided by writing bytes.

This module states the rule once. It is not an abstraction over ``Path``: it is a comment
with a function attached, so the next caller does not have to rediscover the bug.
"""
from __future__ import annotations

import contextlib
import difflib
import os
import re
import stat
import tempfile
from pathlib import Path


def write_exact(path: Path, text: str, newline: str = "\n") -> None:
    """Write ``text`` as UTF-8 with exactly ``newline`` line endings."""
    body = text.replace("\r\n", "\n")
    if newline != "\n":
        body = body.replace("\n", newline)
    path.write_bytes(body.encode("utf-8"))


def write_keeping_endings(path: Path, text: str) -> None:
    """Write ``text`` using whatever line ending the file already uses."""
    ending = "\n"
    try:
        ending = dominant_newline(path.read_bytes())
    except OSError:
        pass
    write_exact(path, text, ending)

def _split_keeping_endings(raw: bytes) -> list[bytes]:
    """Split bytes into lines, each still carrying its own terminator."""
    return [m.group() for m in re.finditer(rb"[^\r\n]*(?:\r\n|\r|\n|$)", raw) if m.group()]


def write_preserving_endings(path: Path, text: str) -> None:
    """Atomically write logical text, preserving all matched lines' original endings.

    New lines adopt the file's dominant ending. Whether the final line is terminated
    comes from ``text``. Match the whole file, not just its prefix and suffix: two edits
    must not rewrite untouched mixed-ending lines between them.
    """
    try:
        original = path.read_bytes()
    except FileNotFoundError:
        original = b""
    ending = dominant_newline(original).encode()
    old_lines = _split_keeping_endings(original)
    new_lines = _split_keeping_endings(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))

    def logical(line: bytes) -> bytes:
        return line.rstrip(b"\r\n") + (b"\n" if line.endswith((b"\r", b"\n")) else b"")

    matcher = difflib.SequenceMatcher(
        a=[logical(line) for line in old_lines], b=[logical(line) for line in new_lines],
        autojunk=False,
    )
    out: list[bytes] = []
    for tag, i, j, k, l in matcher.get_opcodes():
        if tag == "equal":
            out.extend(old_lines[i:j])
        else:
            for line in new_lines[k:l]:
                out.append(line[:-1] + ending if line.endswith(b"\n") else line)
    payload = b"".join(out)
    if payload == original:
        return
    atomic_write_bytes(path, payload)


def atomic_write(path: Path, text: str, newline: str = "\n") -> None:
    """Replace ``path`` with ``text`` without ever writing through a pre-existing name.

    This is `gate._write_file`'s body, moved here because the same two hazards existed in
    every other writer and were fixed one at a time:

    *Line endings.* ``Path.write_text`` translates ``\n`` to ``os.linesep``, so a
    one-line change rewrote a whole LF file as CRLF.

    *The temp name.* Staging at a name the caller can predict — ``<name>.tmp``,
    ``<name>.gate-write`` — meant an agent could hardlink ``People/Self.md`` (or the
    index manifest, or the autopilot state) to that name and then let an ordinary tool
    call replace the file with its own content. ``mkstemp`` makes the name unpredictable
    and ``O_EXCL`` means it cannot already exist; the descriptor is verified to be a
    single-link regular file before anything is written through it.

    Every writer that touches a file the user owns or that the product trusts goes
    through here. A writer with its own copy of this logic is a defect waiting for the
    next review round.
    """
    body = text.replace("\r\n", "\n")
    if newline != "\n":
        body = body.replace("\n", newline)
    atomic_write_bytes(path, body.encode("utf-8"))


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Replace a file with exact bytes through a fresh, single-link staging file."""
    _atomic_file(path, payload)


def atomic_create_bytes(path: Path, payload: bytes, *, mode: int | None = None) -> None:
    """Publish a complete new file, refusing a destination created concurrently."""
    _atomic_file(path, payload, exclusive=True, mode=mode)


def _atomic_file(path: Path, payload: bytes, *, exclusive: bool = False, mode: int | None = None) -> None:

    handle_fd, tmp_name = tempfile.mkstemp(
        prefix=".gate-write-", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        # mkstemp already guarantees a fresh regular file; assert it rather than trust
        # it, because a hostile ACL or a filesystem filter driver is outside our control.
        info = os.fstat(handle_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError("refusing to write through a temp file that is not a plain file")
        with os.fdopen(handle_fd, "wb") as handle:
            handle_fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        # Re-check the *name* now that the descriptor is closed. Nothing should have been
        # able to swap it, but a rename over an open handle on Windows fails anyway.
        named = os.lstat(tmp)
        if not stat.S_ISREG(named.st_mode) or named.st_nlink != 1:
            raise OSError("refusing to replace a target from an unexpected temp file")
        if exclusive:
            # link is an atomic create-if-absent on the same filesystem. Unlike
            # replace, it cannot overwrite a hook another writer just installed.
            os.link(tmp, path)
        else:
            os.replace(tmp, path)
    finally:
        if handle_fd != -1:
            with contextlib.suppress(OSError):
                os.close(handle_fd)
        with contextlib.suppress(OSError):
            if tmp.exists():
                tmp.unlink()


def dominant_newline(original: bytes) -> str:
    """The line ending a file mostly uses, so editing it does not rewrite every line.

    This used to be ``"\r\n" if b"\r\n" in original else "\n"``, which asks whether a
    CRLF exists *anywhere*. On a file with one stray CRLF — a single line pasted from
    Notepad into an otherwise LF note — approving one appended rule rewrote every line of
    the file as CRLF, because the gate then wrote the whole thing with the "dominant"
    ending it had just picked. The reviewer's measurement: 1 CRLF in 49 lines before,
    49 CRLF after, from an append that touched one.

    Counting is the honest question. Ties go to LF, which is what the toolkit writes.
    """
    crlf = original.count(b"\r\n")
    lone_lf = original.count(b"\n") - crlf
    lone_cr = original.count(b"\r") - crlf
    if lone_cr > max(crlf, lone_lf):
        return "\r"
    return "\r\n" if crlf > lone_lf else "\n"
