"""Run an external tool without letting the vault choose which binary runs.

On Windows, ``CreateProcess`` resolves an unqualified executable against the current
working directory *before* it consults ``PATH``. Every process this package starts on a
user's behalf has ``cwd`` set to the vault — the vault is a folder a user clones, syncs,
or opens from a shared repo. So a file named ``git.exe`` sitting in the vault root was
executed whenever anything shelled out to ``git``: the weekly drift pass and
``twinaatma doctor`` both did, and the Cursor ``sessionStart`` hook triggers the drift
pass on every chat. Vault content became code, which is the one thing the design says
cannot happen.

This module exists so that every subprocess in the package goes through one resolver
that only accepts an absolute path from ``PATH`` and refuses anything inside the
directory the caller is about to use as a working directory.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Sequence

# Windows-only extension precedence. It is *not* harmless elsewhere: there is no
# implicit-CWD search on POSIX, so the only thing a bare name needs is `PATH`, but
# appending `.exe` to it meant `resolve_executable("git")` looked for `git.com`,
# `git.exe`, `git.bat`, `git.cmd` and never for `git` — so on Linux and macOS every
# tool returned None and the drift pass, the doctor checks and the git-status line all
# silently degraded to "not available".
_DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD"


def resolve_executable(name: str, *, forbid_under: Path | str | None = None) -> str | None:
    """Absolute path for ``name`` from ``PATH``, or None.

    Deliberately not ``shutil.which``: on Windows that searches the CWD first, which is
    the whole bug. Only absolute ``PATH`` entries are considered, and a candidate that
    resolves inside ``forbid_under`` is rejected even if ``PATH`` lists that directory —
    a vault directory on ``PATH`` must not be able to shadow a system tool.
    """
    if not name or os.path.isabs(name):
        return name if name and Path(name).is_file() else None
    banned: Path | None = None
    if forbid_under is not None:
        try:
            banned = Path(forbid_under).resolve()
        except OSError:
            banned = None

    raw_path = os.environ.get("PATH", "")
    if os.name == "nt":
        pathext = [
            ext.lower()
            for ext in os.environ.get("PATHEXT", _DEFAULT_PATHEXT).split(os.pathsep)
            if ext
        ]
        has_suffix = bool(os.path.splitext(name)[1])
        names = [name] if has_suffix else [name + ext for ext in pathext]
    else:
        # POSIX: one name, no extension guessing, and the executable bit is the test.
        names = [name]
    for directory in raw_path.split(os.pathsep):
        if not directory or not os.path.isabs(directory):
            continue
        for candidate in names:
            path = Path(directory) / candidate
            try:
                if not _runnable_file(path):
                    continue
                resolved = path.resolve()
            except OSError:
                continue
            if banned is not None and _is_within(resolved, banned):
                continue
            return str(resolved)
    return None


def _runnable_file(path: Path) -> bool:
    """A regular file we would be allowed to exec.

    ``is_file`` alone is not enough on POSIX, where something on ``PATH`` can be a
    regular file without the executable bit and ``subprocess`` then fails with EACCES
    instead of the caller's clean "tool not available" path.
    """
    if not path.is_file():
        return False
    if os.name == "nt":
        return True
    return os.access(path, os.X_OK)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def run_trusted(
    name: str,
    args: Sequence[str],
    *,
    cwd: Path | str,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str] | None:
    """Run ``name`` (resolved safely) from ``cwd``; None when it is not available.

    Never raises for a missing tool: callers have a documented fallback, and a stack
    trace raised from a background hook is worse than a quiet downgrade.
    """
    exe = resolve_executable(name, forbid_under=cwd)
    if exe is None:
        return None
    try:
        return subprocess.run(
            [exe, *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
