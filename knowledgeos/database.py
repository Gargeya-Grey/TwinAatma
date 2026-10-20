"""The filesystem boundary for the note index and SQLite's writable sidecars."""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import stat

from knowledgeos.data_ops import plain_vault_path


def checked_database_path(database: Path | str) -> Path:
    """Refuse redirects and non-plain files before SQLite can touch any of them."""
    database = Path(os.path.abspath(database))
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = plain_vault_path(Path(database.anchor), Path(str(database) + suffix))
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Refusing non-regular SQLite path: {path}")
    return database


def connect_database(database: Path | str, *, timeout: float = 5.0) -> sqlite3.Connection:
    """Open the checked disk index with the caller's existing busy timeout."""
    return sqlite3.connect(checked_database_path(database), timeout=timeout)
