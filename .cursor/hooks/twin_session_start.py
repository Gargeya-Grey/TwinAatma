#!/usr/bin/env python
"""Pre-warm TwinAatma autopilot when a Cursor chat starts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    # Consume stdin (sessionStart payload) so the pipe does not block
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
    try:
        from knowledgeos.autopilot import breathe
        from knowledgeos.memory import MemoryAPI

        api = MemoryAPI(ROOT)
        hint = ""
        result = breathe(api, task_hint=hint, limit=6)
        soft = result.get("soft_prompt")
        if soft:
            additional += f" Pending soft prompt from autopilot: {soft}"
        actions = result.get("actions_taken") or []
        if actions:
            additional += f" Autopilot already ran: {', '.join(actions)}."
    except Exception as e:
        additional += f" (Pre-warm note: {e}. Still call memory_session_start.)"

    # additional_context may be dropped by some Cursor builds; side effects still ran.
    print(json.dumps({"additional_context": additional}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
