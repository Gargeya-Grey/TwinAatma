"""Vault root helpers."""
from __future__ import annotations

from pathlib import Path

SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", ".cursor"}


class Vault:
    def __init__(self, root: Path | str | None = None):
        if root is None:
            # Default: package lives at <vault>/knowledgeos/
            root = Path(__file__).resolve().parent.parent
        self.root = Path(root).resolve()

    def iter_markdown(self, skip_archive: bool = False):
        skip = set(SKIP_DIR_NAMES)
        if skip_archive:
            skip.add("Archive")
        for path in self.root.rglob("*.md"):
            if any(part in skip for part in path.parts):
                continue
            if path.name.lower() == "readme.md" and path.parent == self.root:
                continue
            yield path

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()
