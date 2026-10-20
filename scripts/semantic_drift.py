#!/usr/bin/env python
"""KnowledgeOS Semantic Drift Tracker.

Queries git history to analyze file modifications over the last 30 days,
categorizing active focus by note types and generating a cognitive shift report.
"""
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

VAULT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(VAULT_DIR))

from knowledgeos.indexer import iter_markdown
from knowledgeos.remembering import RememberingPolicy, PolicyError

def run_git_command(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(VAULT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
            check=True, timeout=30,
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Git activity could not be read (exit {e.returncode}).", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print("Git activity could not be read before the diagnostic timeout.", file=sys.stderr)
        return None
    except FileNotFoundError:
        print("Git command-line utility not found in PATH.", file=sys.stderr)
        return None

def main():
    try:
        policy = RememberingPolicy(VAULT_DIR)
        policy.require_text(str(VAULT_DIR))
        permitted = {path.relative_to(VAULT_DIR).as_posix() for path in iter_markdown(VAULT_DIR)
                     if policy.read(path, historical=False) is not None}
    except PolicyError as error:
        print(str(error), file=sys.stderr)
        return 1
    git_dir = VAULT_DIR / ".git"
    if not git_dir.exists():
        print(f"Not a git repository at {VAULT_DIR}. Run git init first.")
        return 1

    print("=== KnowledgeOS Semantic Drift Report ===")
    print(f"Analyzing commits over the last 30 days in: {VAULT_DIR}")

    # Query log to get modified files in the last 30 days
    git_log_output = run_git_command([
        "-c", "core.quotePath=false", "log",
        "--since=30.days.ago",
        "--name-only",
        "--pretty=format:"
    ])

    if git_log_output is None:
        return 1
    if not git_log_output.strip():
        print("No commits found in the last 30 days. Commit weekly reviews to populate drift logs.")
        return 0

    # Count modifications per file
    file_counts = defaultdict(int)
    for line in git_log_output.splitlines():
        line = line.strip()
        if line in permitted:
            file_counts[line] += 1

    if not file_counts:
        print("No permitted current personal-note activity is available from this history.")
        return 0

    # Categorize edits by folder
    categories = defaultdict(list)
    total_edits = 0
    for file_path, count in file_counts.items():
        parts = Path(file_path).parts
        category = parts[0] if len(parts) > 1 else "Root"
        categories[category].append((file_path, count))
        total_edits += count

    # Print Summary of Activity
    print(f"\nTotal Note Edits Committed: {total_edits}\n")
    print("--- Distribution of Focus ---")
    for category, items in sorted(categories.items(), key=lambda x: sum(i[1] for i in x[1]), reverse=True):
        cat_edits = sum(count for _, count in items)
        percentage = (cat_edits / total_edits) * 100
        print(f"  {category:<12} : {'#' * int(percentage // 5)} {cat_edits} edit(s) ({percentage:.1f}%)")

    # Print Detailed File Activity
    print("\n--- Detailed Activity Log ---")
    for category, items in sorted(categories.items()):
        print(f"\n[{category}]")
        for file_path, count in sorted(items, key=lambda x: x[1], reverse=True):
            note_name = Path(file_path).stem.replace("_MOC_", "MOC: ").replace("_Index", "Index")
            print(f"  - {note_name:<30} ({count} edits) -> {file_path}")

    print("\nThese are edit counts for permitted current sources, not evidence of changed beliefs.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
