#!/usr/bin/env python
"""Diagnostics. Thin wrapper over knowledgeos.doctor (kept for muscle memory)."""
from __future__ import annotations

import sys
from pathlib import Path

TOOLKIT_DIR = Path(__file__).resolve().parent.parent
if str(TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLKIT_DIR))

from knowledgeos.doctor import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
