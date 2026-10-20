"""Locate toolkit resources (starter templates, agent contract, Cursor hooks) at runtime.

Three layouts exist and all must work:

* **Source checkout** — resources sit at the repository root, one level above the
  package directory.
* **Installed from PyPI / ``pip install .``** — the build step copies them into
  ``knowledgeos/_assets`` so they travel with the wheel. Without that, ``init``
  silently produced a vault with no ``AGENTS.md`` and no hooks, which is exactly
  the kind of "it installed but does nothing" failure this project must not have.
* **PyInstaller binary** — unpacked into ``sys._MEIPASS``.
"""
from __future__ import annotations

import sys
from pathlib import Path

ASSET_MARKERS = ("Templates", "AGENTS.md")


def _looks_like_root(path: Path) -> bool:
    return all((path / marker).exists() for marker in ASSET_MARKERS)


def toolkit_root() -> Path:
    """Where the starter kit (Templates, AGENTS.md, .cursor) lives."""
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return bundle

    package_dir = Path(__file__).resolve().parent
    packaged = package_dir / "_assets"
    if _looks_like_root(packaged):
        return packaged
    return package_dir.parent


def import_root() -> Path:
    """Directory to put on ``PYTHONPATH`` so ``import knowledgeos`` resolves.

    Deliberately *not* ``toolkit_root()``: a wheel install puts the assets inside the
    package, and treating that asset folder as an import root produced a MCP command
    that could not import the toolkit at all.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def missing_assets(root: Path | None = None) -> list[str]:
    """Asset names a broken install is missing, for ``doctor`` to report."""
    base = root or toolkit_root()
    return [name for name in ASSET_MARKERS if not (base / name).exists()]
