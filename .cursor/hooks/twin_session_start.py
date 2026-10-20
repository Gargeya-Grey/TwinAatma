#!/usr/bin/env python
"""Pre-warm TwinAatma when a Cursor chat starts.

Safety rules, in order of importance:

* This file lives **inside the vault**, so it must never import anything from the
  vault or its parents. A note cannot become code.
* Pre-warm uses this installation's executable, never a different installation
  found through ``PATH`` or the working directory.
* Python 3.9/3.10 use ``-I -m knowledgeos`` to import the installed package without
  the vault or environment on the import path. Python 3.11+ can also run from a
  verified source root through ``-P`` and an explicit ``PYTHONPATH``.
* ``--prewarm`` tells autopilot this is not a user session, so the first real chat
  still stays silent.

Best-effort: the agent must still call memory_session_start via MCP.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

def _arg(name: str) -> str | None:
    """Value of ``--name <value>`` or ``--name=<value>`` in this process's argv."""
    argv = sys.argv[1:]
    for index, item in enumerate(argv):
        if item == name and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith(name + "="):
            return item.split("=", 1)[1]
    return None


def _vault_from_environment() -> Path | None:
    """The vault the host named, when the host named one.

    Scripted installs put this file at ``<vault>/.cursor/hooks/``, so ``__file__`` is the
    answer. The frozen binary runs the same file *from inside its own bundle* through
    ``twinaatma hook``, where ``parents[2]`` is a temporary extraction directory — the
    hook then pre-warmed a vault that does not exist and the chat had no memory in it,
    with nothing reported as broken. Both installs now pass ``--vault`` on the command
    line, which wins, and the frozen binary also sets this variable.
    """
    raw = _arg("--vault") or os.environ.get("KNOWLEDGEOS_VAULT")
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if (candidate / "People" / "Self.md").is_file():
        return candidate.resolve()
    return None


VAULT = _vault_from_environment() or Path(__file__).resolve().parents[2]
TIMEOUT = 120


def _shipped_root() -> str | None:
    """The toolkit root this hook file ships inside, when it really holds the package.

    The probe below cannot answer for a source checkout: it runs isolated, so it only
    finds `knowledgeos` when the package is *installed*, and the documented source
    workflow is `twinaatma init` from the checkout. The result was a hook that reported
    "Pre-warm unavailable" on every chat and never warmed anything.

    The check is a real one, not a guess from location: the directory has to contain
    `knowledgeos/__init__.py`. A wheel install puts this file under
    `site-packages/knowledgeos/_assets/.cursor/hooks/`, where that test fails, and the
    installed-package probe answers instead.
    """
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "knowledgeos" / "__init__.py").is_file():
        return str(candidate)
    return None


def _package_root() -> str | None:
    """Import root reported by the *installed* package, verified before use."""
    shipped = _shipped_root()
    if shipped:
        return shipped
    try:
        probe = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import knowledgeos, pathlib;"
                "print(pathlib.Path(knowledgeos.__file__).resolve().parent.parent)",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(VAULT),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if probe.returncode != 0:
        return None
    candidate = probe.stdout.strip()
    if not candidate or (Path(candidate) / "knowledgeos" / "__init__.py").is_file() is False:
        return None
    return candidate


def _command() -> tuple[list[str], dict[str, str]]:
    breathe = ["breathe", "--vault", str(VAULT), "--limit", "6", "--prewarm"]

    if getattr(sys, "frozen", False):
        return [sys.executable, *breathe], {}

    if sys.version_info < (3, 11):
        return [sys.executable, "-I", "-m", "knowledgeos", *breathe], {}

    env: dict[str, str] = {}
    root = _package_root()
    if root:
        env["PYTHONPATH"] = root
    else:
        # Without a verified root, `-m knowledgeos` may not import at all. Trying is
        # still safe (cwd is excluded by `-P`), but do not invent a PYTHONPATH.
        env = {}
    return [sys.executable, "-P", "-m", "knowledgeos", *breathe], env


def _run_breathe() -> dict:
    cmd, extra_env = _command()
    if not cmd:
        return {}
    env = {**os.environ, **extra_env}
    if extra_env.get("PYTHONPATH"):
        env["PYTHONPATH"] = extra_env["PYTHONPATH"]
    else:
        # A stale PYTHONPATH from the terminal can point at the vault and re-enable
        # exactly the shadowing `-P` was chosen to prevent.
        env.pop("PYTHONPATH", None)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd=str(VAULT),
            env=env,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def main() -> int:
    try:
        raw = sys.stdin.read()
        _ = json.loads(raw) if raw.strip() else {}
    except Exception:
        pass

    additional = (
        "TwinAatma autopilot is active in this workspace (technical toolkit: knowledgeos). "
        "Your FIRST tool call this chat must be memory_session_start "
        "(task_hint = the user's goal). Keep the twin current yourself. "
        "Never ask the user to run toolkit commands. "
        "Do not name TwinAatma/KnowledgeOS/hooks/scripts to the user. "
        "If memory_session_start returns a soft_prompt, ask it once in plain language. "
        "You may PROPOSE identity updates, but you can never approve them: the human "
        "runs `twinaatma self approve <file>` themselves. Never run that command, "
        "and never claim a proposal was accepted."
    )
    result = _run_breathe()
    if result:
        # A pre-warm never carries a soft prompt: it has not seen the human yet.
        actions = result.get("actions_taken") or []
        if actions:
            additional += f" Autopilot pre-warm ran: {', '.join(actions)}."
    else:
        additional += " (Pre-warm unavailable. Still call memory_session_start.)"

    print(json.dumps({"additional_context": additional}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
