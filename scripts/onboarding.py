#!/usr/bin/env python
"""KnowledgeOS Cognitive Onboarding Wizard.

Runs an interactive CLI interview to capture user heuristics, values, and anti-goals,
then generates the core ego node note (People/Self.md).
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
SELF_NOTE = VAULT_DIR / "People" / "Self.md"


def get_input(prompt: str, default: str = "") -> str:
    try:
        val = input(prompt).strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print("\nOnboarding cancelled.")
        sys.exit(1)


def main() -> None:
    print("=== KnowledgeOS Cognitive Onboarding Wizard ===")
    print("This wizard configures your Ego Node (People/Self.md)\n")

    if SELF_NOTE.exists():
        overwrite = get_input("People/Self.md already exists.\nOverwrite? (y/n) [n]: ", "n")
        if overwrite.lower() != "y":
            print("Aborting. Self.md was not changed.")
            return

    name = get_input("1. Enter your full name: ")
    if not name:
        print("[ERROR] Name is required to initialize Ego Node.")
        sys.exit(1)

    print("\n2. Define your top 3 Operating Heuristics / Rules of Thumb.")
    rule1 = get_input("   - Rule 1: ")
    rule2 = get_input("   - Rule 2: ")
    rule3 = get_input("   - Rule 3: ")

    print("\n3. List your top 3 Core Values.")
    val1 = get_input("   - Value 1: ")
    val2 = get_input("   - Value 2: ")
    val3 = get_input("   - Value 3: ")

    print("\n4. List your top 3 Anti-Goals.")
    anti1 = get_input("   - Anti-Goal 1: ")
    anti2 = get_input("   - Anti-Goal 2: ")
    anti3 = get_input("   - Anti-Goal 3: ")

    today = datetime.date.today().isoformat()
    md_content = f"""---
type: person
title: Self ({name})
description: The core ego node representing {name}, operating heuristics, values, and cognitive drift over time.
id: kos:person:self
schema: knowledgeos-v0.3
status: active
created: {today}
updated: {today}
tags: [ego-node, core, systems]
timestamp: {today}T00:00:00Z
last_reviewed: {today}
---

# Self ({name})

Identity layer for {name}. Agents load this before advising; propose edits only.

## Operating Heuristics & Rules of Thumb
<!-- kos:section=heuristics -->
* {rule1 if rule1 else "Prefer durability over cleverness"}
* {rule2 if rule2 else "Write a decision note before major scope shifts"}
* {rule3 if rule3 else "Close loops: Decide → Outcome → Lesson → Self update"}

## Values Hierarchy
<!-- kos:section=values -->
1. **{val1 if val1 else "Clarity"}**
2. **{val2 if val2 else "Autonomy"}**
3. **{val3 if val3 else "Execution"}**

## Mental Models
<!-- kos:section=mental_models -->
* First Principles
* Inversion

## Anti-Goals
<!-- kos:section=anti_goals -->
* {anti1 if anti1 else "Building before validating"}
* {anti2 if anti2 else "Letting Inbox grow without triage"}
* {anti3 if anti3 else "Silent Self mutations by agents"}

## Active Bets
<!-- kos:section=active_bets -->
* _(Add your current strategic bets)_

## Drift Log
<!-- kos:section=drift_log -->
| Topic | Shift Observed | Date Flagged | Evidence |
|---|---|---|---|
| — | Ego node initialized via onboarding | {today} | onboarding.py |
"""

    SELF_NOTE.parent.mkdir(parents=True, exist_ok=True)
    SELF_NOTE.write_text(md_content, encoding="utf-8")
    print(f"\n[OK] Wrote Ego Node to: {SELF_NOTE}")
    print("Next: python scripts/rebuild_index.py")
    print("      python -m knowledgeos self summary")


if __name__ == "__main__":
    main()
