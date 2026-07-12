#!/usr/bin/env python
"""KnowledgeOS Alignment & Project Health Diagnostic.

Checks for:
1. Orphan decisions
2. Pending decisions mentioned in folder indexes
3. Stale projects (no next actions)
4. Decision outcomes due for review (outcome_status pending + review_after)
5. Decisions with lessons that have no Self proposal yet (informational)
"""
from __future__ import annotations

import datetime
import sqlite3
import sys
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
DB = VAULT_DIR / "knowledge_index.db"


def main() -> int:
    if not DB.exists():
        print(f"Index database not found at {DB}. Please run python scripts/rebuild_index.py first.")
        return 1

    conn = sqlite3.connect(DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    today = datetime.date.today().isoformat()

    decisions = cur.execute(
        """
        SELECT title, path, tags, outcome_status, review_after, lesson
        FROM notes
        WHERE type = 'decision' AND path NOT LIKE 'Templates/%'
        """
    ).fetchall()
    projects = cur.execute(
        "SELECT title, path FROM notes WHERE type = 'project' AND path NOT LIKE 'Templates/%'"
    ).fetchall()

    print("=== KnowledgeOS Alignment Diagnostic ===")
    print(f"Vault: {VAULT_DIR}")

    print("\n[Diagnostic A: Decisions Link Check]")
    orphan_count = 0
    for row in decisions:
        title, path = row["title"], row["path"]
        links = cur.execute(
            "SELECT count(*) FROM links WHERE source = ? OR destination = ?", (path, path)
        ).fetchone()[0]
        if links == 0:
            print(f"[WARNING] Orphan Decision: '{title}' ({path}) has no internal links.")
            orphan_count += 1
        else:
            print(f"[OK]      Aligned: '{title}' ({links} link(s))")
    if orphan_count == 0:
        print("[OK] All decisions are linked to related projects/concepts.")

    print("\n[Diagnostic B: Pending Decisions Check]")
    indices = cur.execute("SELECT path FROM notes WHERE type = 'index'").fetchall()
    pending_count = 0
    for row in indices:
        idx_path = row["path"] if isinstance(row, sqlite3.Row) else row[0]
        full_path = VAULT_DIR / idx_path
        if full_path.exists():
            content = full_path.read_text(encoding="utf-8", errors="replace")
            in_decisions_to_make = False
            for line in content.splitlines():
                if "Decisions to Make" in line or "Pending Decisions" in line:
                    in_decisions_to_make = True
                    continue
                if in_decisions_to_make and line.startswith("#"):
                    in_decisions_to_make = False
                if in_decisions_to_make and line.strip().startswith("-"):
                    print(f"[PENDING] Pending Decision in {idx_path}: {line.strip()}")
                    pending_count += 1
    if pending_count == 0:
        print("[OK] No pending decisions found in folder indexes.")

    print("\n[Diagnostic C: Project Health Check]")
    stale_count = 0
    for row in projects:
        title, path = row["title"], row["path"]
        full_path = VAULT_DIR / path
        if full_path.exists():
            content = full_path.read_text(encoding="utf-8", errors="replace")
            if "Next Actions" not in content and "next steps" not in content.lower():
                print(f"[WARNING] Stale Project: '{title}' ({path}) has no 'Next Actions' section.")
                stale_count += 1
            else:
                lines = content.splitlines()
                has_action = False
                in_actions = False
                for line in lines:
                    if "Next Actions" in line or "next steps" in line.lower():
                        in_actions = True
                        continue
                    if in_actions and line.startswith("#"):
                        in_actions = False
                    if in_actions and (line.strip().startswith("- [ ]") or line.strip().startswith("-")):
                        if len(line.strip().replace("-", "").replace("[ ]", "").strip()) > 2:
                            has_action = True
                            break
                if not has_action:
                    print(f"[WARNING] Stale Project: '{title}' ({path}) has an empty next action list.")
                    stale_count += 1
                else:
                    print(f"[OK]      Active: '{title}'")
    if stale_count == 0:
        print("[OK] All active projects have next actions defined.")

    print("\n[Diagnostic D: Decision Outcome Reviews Due]")
    due_count = 0
    pending_outcomes = 0
    for row in decisions:
        title, path = row["title"], row["path"]
        outcome = (row["outcome_status"] or "").strip().lower() or "pending"
        review_after = (row["review_after"] or "").strip()
        if outcome in {"pending", ""}:
            pending_outcomes += 1
            overdue = False
            if review_after and review_after <= today:
                overdue = True
            elif not review_after:
                # No review_after: still flag as awaiting outcome (not overdue)
                print(f"[AWAITING] '{title}' ({path}) outcome_status={outcome or 'pending'} (no review_after)")
                due_count += 1
                continue
            if overdue:
                print(f"[DUE]      '{title}' ({path}) review_after={review_after}")
                due_count += 1
            else:
                print(f"[SCHEDULED] '{title}' review_after={review_after}")
        elif outcome in {"confirmed", "invalidated", "superseded"}:
            lesson = (row["lesson"] or "").strip()
            if not lesson:
                print(f"[HINT]     '{title}' has outcome={outcome} but empty lesson — consider extracting a Self heuristic.")
    if due_count == 0 and pending_outcomes == 0:
        print("[OK] No pending decision outcomes.")
    elif due_count == 0:
        print("[OK] Pending outcomes exist but none are past review_after.")

    print("\n--- Summary ---")
    print(f"orphan_decisions={orphan_count} stale_projects={stale_count} outcome_items_flagged={due_count}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
