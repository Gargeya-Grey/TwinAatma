#!/usr/bin/env python
"""KnowledgeOS Diagnostic & Health Doctor.

Validates the local environment, Python runtime version, folder structure,
git capability, index DB, and optional Notion config.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
DB = VAULT_DIR / "knowledge_index.db"

REQUIRED_DIRS = [
    "Inbox",
    "Concepts",
    "Projects",
    "Experiments",
    "Research",
    "Decisions",
    "People",
    "MOCs",
    "Templates",
    "Assets",
    "Archive",
]


def main() -> int:
    print("=== KnowledgeOS Environment Diagnostic Doctor ===")
    print(f"Vault Root: {VAULT_DIR}\n")

    passed = True

    py_ver = sys.version_info
    print("[*] Checking Python version...")
    if py_ver.major < 3 or (py_ver.major == 3 and py_ver.minor < 9):
        print(
            f"  [ERROR] Python {py_ver.major}.{py_ver.minor} detected. "
            "KnowledgeOS requires Python 3.9+."
        )
        passed = False
    else:
        print(f"  [OK] Python {py_ver.major}.{py_ver.minor}.{py_ver.micro} detected.")

    print("\n[*] Checking folder structure...")
    missing_dirs = [d for d in REQUIRED_DIRS if not (VAULT_DIR / d).exists()]
    if missing_dirs:
        print(f"  [WARNING] Missing directories: {', '.join(missing_dirs)}.")
        print("            Creating missing directories now...")
        for d in missing_dirs:
            (VAULT_DIR / d).mkdir(parents=True, exist_ok=True)
        print("  [OK] Folder structure initialized.")
    else:
        print("  [OK] All core vault directories are present.")

    print("\n[*] Checking Git configuration...")
    git_dir = VAULT_DIR / ".git"
    if not git_dir.exists():
        print("  [WARNING] Git repository is not initialized. Run 'git init' to track cognitive drift.")
    else:
        import subprocess

        try:
            subprocess.run(
                ["git", "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            print("  [OK] Git is installed and initialized.")
        except Exception:
            print("  [WARNING] Git command line utility was not found in PATH.")

    print("\n[*] Checking SQLite Database index...")
    if not DB.exists():
        print(
            "  [WARNING] 'knowledge_index.db' is missing. "
            "Run 'python scripts/rebuild_index.py' to generate it."
        )
    else:
        size = DB.stat().st_size
        print(f"  [OK] SQLite index found ({size} bytes).")

    print("\n[*] Checking Notion configuration (optional)...")
    has_key = bool(os.environ.get("NOTION_API_KEY"))
    has_db = bool(
        os.environ.get("NOTION_DATABASE_ID") or os.environ.get("NOTION_DATA_SOURCE_ID")
    )
    config_path = VAULT_DIR / "knowledgeos.config.json"
    example_path = VAULT_DIR / "knowledgeos.config.example.json"
    if config_path.exists():
        print(f"  [OK] Found {config_path.name}")
    elif example_path.exists():
        print(f"  [INFO] No knowledgeos.config.json yet (example present). Notion remains optional.")
    if has_key and has_db:
        print("  [OK] Notion API key and database id detected in environment.")
    elif has_key or has_db:
        print("  [WARNING] Partial Notion env detected (need both API key and database id).")
    else:
        print("  [INFO] Notion not configured. Core KnowledgeOS works without it.")

    print("\n[*] Checking LICENSE / hygiene...")
    if (VAULT_DIR / "LICENSE").exists():
        print("  [OK] LICENSE present.")
    else:
        print("  [WARNING] LICENSE file missing.")

    print("\n--- Diagnostic Summary ---")
    if passed:
        print("[OK] System environment check PASSED. KnowledgeOS is ready for use!")
        return 0
    print("[FAIL] System environment check FAILED. Please resolve errors above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
