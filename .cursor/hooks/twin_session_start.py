#!/usr/bin/env python
"""Pre-warm TwinAatma autopilot when a Cursor chat starts.

Works with data-only vaults: prefers the `twinaatma` binary on PATH,
falls back to `python -m knowledgeos` when the toolkit is importable.
Vault is the workspace root (parents[2] of this hook). Best-effort —
the agent must still call memory_session_start via MCP.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]


def _run_breathe() -> dict:
    exe = shutil.which("twinaatma")
    if exe:
        cmd = [exe, "breathe", "--vault", str(VAULT), "--limit", "6"]
    else:
        cmd = [sys.executable, "-m", "knowledgeos", "breathe", "--vault", str(VAULT), "--limit", "6"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
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
        "If soft_prompt is returned, ask it once in plain language "
        '("Want me to remember that?"). Do not name TwinAatma/KnowledgeOS/hooks/scripts to the user.'
    )
    result = _run_breathe()
    if result:
        soft = result.get("soft_prompt")
        if soft:
            additional += f" Pending soft prompt from autopilot: {soft}"
        actions = result.get("actions_taken") or []
        if actions:
            additional += f" Autopilot already ran: {', '.join(actions)}."
    else:
        additional += " (Pre-warm unavailable. Still call memory_session_start.)"

    print(json.dumps({"additional_context": additional}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
