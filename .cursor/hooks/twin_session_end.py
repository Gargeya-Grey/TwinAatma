#!/usr/bin/env python
"""Mark orphan sessions so the next breath can soft-prompt to keep unfinished work.

Data-only safe: only touches .knowledgeos/autopilot.json state in the vault
(workspace root). Never imports the toolkit.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
STATE_FILE = VAULT / ".knowledgeos" / "autopilot.json"


def main() -> int:
    try:
        raw = sys.stdin.read()
        _ = json.loads(raw) if raw.strip() else {}
    except Exception:
        pass
    try:
        if STATE_FILE.exists():
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if state.get("session_open") and not state.get("session_ended"):
                state["orphan_unsaved_session"] = True
                state["session_open"] = False
                state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
