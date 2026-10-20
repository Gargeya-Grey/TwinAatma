"""Build hook: put the vault starter kit inside the wheel.

``pip install twinaatma`` must produce a working ``twinaatma init``. The starter
templates, `AGENTS.md` and the Cursor hooks live at the repository root (they are
files a user can read and diff), so packaging them needs an explicit copy step:
``knowledgeos/_assets/`` exists only inside the build tree and is never written into
the source checkout.

Without this, ``pip install .`` produced an install where ``init`` created folders
and then silently shipped no `AGENTS.md`, no hooks and no templates — an install
that looks successful and does nothing.

Staging into the *source* tree was a bug: it made ``toolkit_root()`` start returning
``knowledgeos/_assets`` for the checkout itself, and `python setup.py build` left the
working tree dirty enough that the test suite (which asserts it leaves no residue)
failed afterwards.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py

ROOT = Path(__file__).resolve().parent

DIR_ASSETS = ["Templates", ".cursor"]
FILE_ASSETS = ["AGENTS.md", "LICENSE"]


def _ignore(directory: str, names: list[str]) -> set[str]:
    drop = {"__pycache__", ".git", ".knowledgeos", "node_modules"}
    return {name for name in names if name in drop or name.endswith(".pyc")}


def stage_assets(target: Path) -> None:
    """Copy the starter kit into ``target`` (a build-tree directory)."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in DIR_ASSETS:
        src = ROOT / name
        if src.exists():
            shutil.copytree(src, target / name, ignore=_ignore)
    for name in FILE_ASSETS:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, target / name)

    missing = [n for n in ("Templates", "AGENTS.md") if not (target / n).exists()]
    if missing:
        raise RuntimeError(
            "the wheel would ship without " + ", ".join(missing) + "; a pip install "
            "would create a vault with no starter kit. Refusing to build."
        )


class build_py(_build_py):
    def run(self) -> None:  # noqa: D102 - setuptools hook
        super().run()
        self._copy_assets_into_build()

    def _copy_assets_into_build(self) -> None:
        """Put the staged kit in the build tree so the wheel carries it.

        Declaring ``package-data`` globs is fragile across setuptools versions;
        copying into the build directory is not. Everything under the build
        directory becomes part of the wheel. A temp staging directory keeps the
        source checkout untouched.
        """
        target = Path(self.build_lib) / "knowledgeos" / "_assets"
        with tempfile.TemporaryDirectory(prefix="ta-assets-") as tmp:
            staged = Path(tmp) / "assets"
            stage_assets(staged)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(staged, target)
        # `py.typed` is declared in `package-data`, but a build hook that rewrites the
        # package tree is exactly where declared data quietly goes missing: the wheel
        # shipped without it while `pyproject.toml` promised it. Copy it here too.
        marker = Path(self.build_lib) / "knowledgeos" / "py.typed"
        if not marker.exists():
            source = ROOT / "knowledgeos" / "py.typed"
            if source.exists():
                shutil.copy2(source, marker)


setup(cmdclass={"build_py": build_py})
