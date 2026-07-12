#!/usr/bin/env python
"""CLI wrappers for Self proposal workflow (never silent Self writes)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
if str(VAULT) not in sys.path:
    sys.path.insert(0, str(VAULT))

from knowledgeos.evolution import (  # noqa: E402
    propose_from_decision_lesson,
    propose_from_drift,
    reject_proposal,
)
from knowledgeos.memory import MemoryAPI  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Propose / reject Self.md updates")
    parser.add_argument("--vault", type=Path, default=VAULT)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("from-drift", help="Propose Drift Log update from recent activity")
    p1.add_argument("--days", type=int, default=30)

    p2 = sub.add_parser("from-lesson", help="Propose heuristics update from a decision lesson")
    p2.add_argument("path", help="Decision note path")

    p3 = sub.add_parser("manual", help="Manual section proposal")
    p3.add_argument("--section", required=True)
    p3.add_argument("--summary", required=True)
    p3.add_argument("--markdown", required=True)
    p3.add_argument("--rationale", default="")

    p4 = sub.add_parser("reject", help="Reject a proposal without mutating Self")
    p4.add_argument("proposal_path")
    p4.add_argument("--reason", default="")

    args = parser.parse_args()
    api = MemoryAPI(args.vault.resolve())

    if args.cmd == "from-drift":
        result = propose_from_drift(api, args.days)
    elif args.cmd == "from-lesson":
        result = propose_from_decision_lesson(api, args.path)
    elif args.cmd == "manual":
        result = api.propose_self_update(args.summary, args.section, args.markdown, args.rationale)
    elif args.cmd == "reject":
        result = reject_proposal(api, args.proposal_path, args.reason)
    else:
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 1 if isinstance(result, dict) and result.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
