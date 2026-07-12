#!/usr/bin/env python
"""Generate weekly intelligence brief."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
if str(VAULT) not in sys.path:
    sys.path.insert(0, str(VAULT))

from knowledgeos.intelligence import weekly_intelligence_report  # noqa: E402
from knowledgeos.memory import MemoryAPI  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--vault", type=Path, default=VAULT)
    args = parser.parse_args()
    api = MemoryAPI(args.vault.resolve())
    out = weekly_intelligence_report(api, days=args.days)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
