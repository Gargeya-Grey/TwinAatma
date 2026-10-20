"""Run the scorecard::

    python tests/score.py                 # score, with dimensions and failures
    python tests/score.py --json          # machine-readable, for CI
    python tests/score.py --only identity # one dimension
    python tests/score.py --save-baseline # record this run as the reference
    python tests/score.py --baseline      # score and diff against the reference

The number is the weighted pass rate over the scenario corpus, nothing else. It is not a
review score and it does not replace one: it cannot see a class of bug nobody imagined.
What it can do is stop the same class being paid for twice, and make "are we moving
forward" a diff instead of a memory.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from spec import (  # noqa: E402
    DIMENSIONS,
    DIMENSION_TITLES,
    SCENARIOS,
    compare,
    load_baseline,
    run_all,
    save_baseline,
    scorecard,
)


def _bar(value: float, width: int = 10) -> str:
    filled = int(round(value / 100 * width))
    return "#" * filled + "." * (width - filled)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="score", description="TwinAatma scorecard")
    parser.add_argument("--json", action="store_true", help="emit the scorecard as JSON")
    parser.add_argument("--only", default=None, help="substring of a scenario id or dimension")
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--baseline", action="store_true", help="diff against the saved baseline")
    parser.add_argument("--quiet", action="store_true", help="only print the total")
    args = parser.parse_args(argv)

    results = run_all(args.only)
    if not results:
        print("no scenarios matched", file=sys.stderr)
        return 2
    card = scorecard(results)
    card["passing"] = sorted(r.scenario.id for r in results if r.verdict == "PASS")

    if args.save_baseline:
        save_baseline(card)
        print(f"baseline saved: {card['score']}/100 across {len(results)} scenarios")

    if args.json:
        print(json.dumps(card, indent=2, sort_keys=True))
        return 0 if not card["failures"] else 1

    if not args.quiet:
        print()
        print("TwinAatma scorecard")
        print("=" * 62)
        for name, weight in DIMENSIONS.items():
            info = card["dimensions"][name]
            if not info.get("measured"):
                if info["skipped"]:
                    print(f"  {info['title']:<24} {'-' * 10}  not run")
                continue
            print(
                f"  {info['title']:<24} {_bar(info['score'])} "
                f"{info['score']:>5.1f}  (x{weight}, {info['passed']} ok"
                + (f", {info['failed']} FAIL" if info["failed"] else "")
                + (f", {info['skipped']} skip" if info["skipped"] else "")
                + ")"
            )
        print("=" * 62)
        print(f"  SCORE {card['score']}/100 across {len(results)} scenarios")
        print()
        print("  This number measures the corpus, not the product. It cannot see a")
        print("  class of bug nobody imagined: a green run says every clause written")
        print("  down still holds, not that every clause worth writing down exists.")
        print("  Coverage grows only when an adversary finds something new.")

        if card["failures"]:
            print()
            print("Failures")
            print("-" * 62)
            for item in card["failures"]:
                print(f"  [{item['verdict']}] {item['scenario']}  ({item['source']})")
                print(f"     claim: {item['claim']}")
                print(f"     why:   {item['detail']}")
        if card["skipped"]:
            print()
            print("Skipped (not counted)")
            print("-" * 62)
            for item in card["skipped"]:
                print(f"  {item['scenario']}: {item['reason']}")
        print()

    if args.baseline:
        previous = load_baseline()
        if previous is None:
            print("no baseline recorded; run --save-baseline first", file=sys.stderr)
            return 2
        diff = compare(card, previous)
        print(f"  vs baseline: {diff['score_delta']:+.1f} points")
        for name, delta in diff["dimensions"].items():
            if delta:
                print(f"    {DIMENSION_TITLES[name]:<24} {delta:+.1f}")
        if diff["newly_failing"]:
            print("  REGRESSIONS:")
            for name in diff["newly_failing"]:
                print(f"    {name}")
        if diff["newly_passing"]:
            print("  newly passing:")
            for name in diff["newly_passing"]:
                print(f"    {name}")
        print()

    return 0 if not card["failures"] else 1


if __name__ == "__main__":
    sys.exit(main())
