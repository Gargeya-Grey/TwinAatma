#!/usr/bin/env python
"""Refresh generated operational dashboards and intelligence views."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
VAULT = SCRIPTS.parent
if str(VAULT) not in sys.path:
    sys.path.insert(0, str(VAULT))

from knowledgeos.intelligence import write_intelligence_views  # noqa: E402
from knowledgeos.memory import MemoryAPI  # noqa: E402


def main() -> int:
    for name in ["experiment_dashboard.py", "outcomes_dashboard.py"]:
        print(f"Running {name}...")
        subprocess.check_call([sys.executable, str(SCRIPTS / name)])

    print("Generating intelligence views...")
    api = MemoryAPI(VAULT)
    paths = write_intelligence_views(api)
    for title, path in paths.items():
        print(f"  Wrote {path} ({title})")

    print("Generated dashboards updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
