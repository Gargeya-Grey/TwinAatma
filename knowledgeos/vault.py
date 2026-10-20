"""Vault root helpers."""
from __future__ import annotations

from pathlib import Path


class Vault:
    def __init__(self, root: Path | str | None = None):
        if root is None:
            # Default: package lives at <vault>/knowledgeos/
            root = Path(__file__).resolve().parent.parent
        self.root = Path(root).resolve()

    def iter_markdown(self, skip_archive: bool = False):
        from knowledgeos.indexer import iter_markdown

        for path in iter_markdown(self.root):
            if skip_archive and "Archive" in path.relative_to(self.root).parts[:-1]:
                continue
            yield path

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()
