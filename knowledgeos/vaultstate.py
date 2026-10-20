"""The one place that decides where a vault's hidden state lives.

Both the autopilot state file and the index manifest are written into
``<vault>/.knowledgeos/``. Two separate implementations of "make that folder" is how one
of them ended up without a containment check: a ``.knowledgeos`` junction pointing at
another disk made every write succeed outside the vault and report success.
"""
from __future__ import annotations

from pathlib import Path

STATE_DIR_NAME = ".knowledgeos"


def state_dir(vault: Path) -> Path:
    """The vault's state folder, refused if it is a link or lands outside the vault.

    ``mkdir(parents=True)`` follows a junction, so a junctioned ``.knowledgeos`` made
    `breathe` write ``autopilot.json`` and ``index-manifest.json`` outside the vault —
    reported as success, because every call worked. `Inbox` already refused this; the
    state folder is the same class of write and had no check at all. A reparse point is
    refused even when it points *inside* the vault, because the gate refuses those for
    the same reason: the human cannot see where the bytes went.
    """
    from knowledgeos.gate import _is_reparse

    root = vault.resolve()
    folder = root / STATE_DIR_NAME
    if folder.exists() and (folder.is_symlink() or _is_reparse(folder)):
        raise PermissionError(
            f"{STATE_DIR_NAME} is a link or junction; refusing to write vault state through it"
        )
    if folder.exists() and not folder.is_dir():
        # A *file* at the state path is not a vault fault we can route around, and the
        # old `mkdir(exist_ok=True)` surfaced it as a bare `FileExistsError` out of the
        # tool call: the reviewer created `.knowledgeos` as an ordinary file and every
        # session tool answered `{"error": ...}` while `doctor` printed PASSED.
        raise NotADirectoryError(
            f"{STATE_DIR_NAME} exists but is not a folder; remove it so the twin can keep "
            "its state"
        )
    folder.mkdir(parents=True, exist_ok=True)
    resolved = folder.resolve()
    resolved.relative_to(root)
    return resolved
