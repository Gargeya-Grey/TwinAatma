#!/usr/bin/env python
"""Mark orphan sessions so the next breath can soft-prompt to keep unfinished work."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    try:
        raw = sys.stdin.read()
        _ = json.loads(raw) if raw.strip() else {}
    except Exception:
        pass
    try:
        from knowledgeos.autopilot import mark_orphan_if_open

        mark_orphan_if_open(ROOT)
    except Exception:
        pass
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
