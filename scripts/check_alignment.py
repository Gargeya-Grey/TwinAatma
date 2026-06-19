#!/usr/bin/env python
"""KnowledgeOS Alignment & Project Health Diagnostic.

Checks for:
1. Orphan decisions (decisions with no incoming or outgoing links).
2. Pending decisions mentioned in folder indexes.
3. Stale projects (projects without next actions).
"""
import sqlite3
import sys
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
DB = VAULT_DIR / "knowledge_index.db"

def main():
    if not DB.exists():
        print(f"Index database not found at {DB}. Please run python scripts/rebuild_index.py first.")
        sys.exit(1)

    conn = sqlite3.connect(DB, timeout=30.0)
    cur = conn.cursor()

    # 1. Fetch decisions (excluding templates)
    decisions = cur.execute("SELECT title, path, tags FROM notes WHERE type = 'decision' AND path NOT LIKE 'Templates/%'").fetchall()
    
    # 2. Fetch projects (excluding templates)
    projects = cur.execute("SELECT title, path FROM notes WHERE type = 'project' AND path NOT LIKE 'Templates/%'").fetchall()

    print("=== KnowledgeOS Alignment Diagnostic ===")
    print(f"Vault: {VAULT_DIR}")
    
    # Diagnostic A: Orphan Decisions
    print("\n[Diagnostic A: Decisions Link Check]")
    orphan_count = 0
    for title, path, tags in decisions:
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

    # Diagnostic B: Unlinked decisions to be made
    print("\n[Diagnostic B: Pending Decisions Check]")
    indices = cur.execute("SELECT path FROM notes WHERE type = 'index'").fetchall()
    pending_count = 0
    for (idx_path,) in indices:
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

    # Diagnostic C: Project Health Check
    print("\n[Diagnostic C: Project Health Check]")
    stale_count = 0
    for title, path in projects:
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
                    
    conn.close()

if __name__ == "__main__":
    main()
