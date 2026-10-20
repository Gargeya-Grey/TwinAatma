"""Preserving boundaries for source maintenance and generated reports."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from knowledgeos.textio import atomic_write_bytes


def _generated_hashes(receipt: Path) -> tuple[str | None, ...]:
    try:
        stored = receipt.read_text(encoding="ascii").strip()
        if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored):
            return (stored,)
        intent = json.loads(stored)
        if (not isinstance(intent, dict)
                or set(intent) != {"schema", "before_sha256", "after_sha256"}
                or intent["schema"] != "twinaatma.generated-write/v1"
                or intent["after_sha256"] is None
                or any(value is not None and (
                    not isinstance(value, str) or len(value) != 64
                    or any(c not in "0123456789abcdef" for c in value))
                    for value in (intent["before_sha256"], intent["after_sha256"]))):
            raise ValueError("Invalid receipt fields")
        return (intent["before_sha256"], intent["after_sha256"])
    except ValueError as error:
        raise ValueError(f"Invalid generated output receipt: {receipt}") from error


def plain_vault_path(vault: Path, path: Path) -> Path:
    """Check lexical containment before resolving, and refuse linked components."""
    vault = Path(os.path.abspath(vault))
    path = Path(os.path.abspath(path))
    try:
        relative = path.relative_to(vault)
    except ValueError as error:
        raise ValueError(f"Path is outside the vault: {path}") from error
    components = [vault]
    for part in relative.parts:
        components.append(components[-1] / part)
    for component in components:
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise ValueError(f"Refusing linked/reparse path: {component}")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError(f"Refusing hardlinked file: {component}")
    return path


def personal_note_paths(vault: Path, paths: list[Path]) -> list[Path]:
    """Exclude unchanged owned reports; untrusted receipts never hide a note."""
    try:
        receipts = plain_vault_path(vault, vault / ".knowledgeos/generated")
        names = {path.name for path in receipts.iterdir()}
    except (OSError, ValueError):
        return paths
    personal = []
    for path in paths:
        relative = path.relative_to(vault).as_posix()
        name = hashlib.sha256(relative.encode()).hexdigest() + ".sha256"
        if name in names:
            try:
                receipt = plain_vault_path(vault, receipts / name)
                authorized = _generated_hashes(receipt)
                report = plain_vault_path(vault, path)
                if hashlib.sha256(report.read_bytes()).hexdigest() in authorized:
                    continue
            except (OSError, ValueError):
                pass
        personal.append(path)
    return personal


def write_generated(vault: Path, path: Path, text: str) -> None:
    from knowledgeos.remembering import RememberingPolicy

    with RememberingPolicy(vault).lock() as policy:
        policy.require_text(text)
        _write_generated(vault, path, text)


def _write_generated(vault: Path, path: Path, text: str) -> None:
    """Regenerate only our unchanged prior output; preserve unowned or edited files.

    The receipt records the old and new hashes before the report is replaced.
    Either state is safe to retry after an interrupted replacement.
    Receipts establish accidental-overwrite protection, not an approval boundary.
    """
    path = plain_vault_path(vault, path)
    relative = path.relative_to(Path(os.path.abspath(vault))).as_posix()
    key = hashlib.sha256(relative.encode()).hexdigest()
    receipt = plain_vault_path(vault, Path(vault) / ".knowledgeos/generated" / (key + ".sha256"))
    payload = text.encode("utf-8")
    authorized = ()
    if receipt.exists():
        authorized = _generated_hashes(receipt)
    original_hash = None
    if path.exists():
        original = path.read_bytes()
        if original == payload:
            return
        original_hash = hashlib.sha256(original).hexdigest()
        if original_hash not in authorized:
            raise ValueError(f"Refusing to replace unowned or edited generated output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    plain_vault_path(vault, path)
    plain_vault_path(vault, receipt)
    intent = {
        "schema": "twinaatma.generated-write/v1",
        "before_sha256": original_hash,
        "after_sha256": hashlib.sha256(payload).hexdigest(),
    }
    atomic_write_bytes(receipt, json.dumps(intent, sort_keys=True).encode("ascii"))
    atomic_write_bytes(path, payload)
