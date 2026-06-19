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

def run_git_command(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(VAULT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Git command failed: {e.stderr}", file=sys.stderr)
        return ""
    except FileNotFoundError:
        print("Git command-line utility not found in PATH.", file=sys.stderr)
        return ""

def main():
    git_dir = VAULT_DIR / ".git"
    if not git_dir.exists():
        print(f"Not a git repository at {VAULT_DIR}. Run git init first.")
        sys.exit(1)

    print("=== KnowledgeOS Semantic Drift Report ===")
    print(f"Analyzing commits over the last 30 days in: {VAULT_DIR}")

    # Query log to get modified files in the last 30 days
    git_log_output = run_git_command([
        "log",
        "--since=30.days.ago",
        "--name-only",
        "--pretty=format:"
    ])

    if not git_log_output.strip():
        print("No commits found in the last 30 days. Commit weekly reviews to populate drift logs.")
        sys.exit(0)

    # Count modifications per file
    file_counts = defaultdict(int)
    for line in git_log_output.splitlines():
        line = line.strip()
        if line and line.endswith(".md"):
            file_counts[line] += 1

    if not file_counts:
        print("No markdown note edits detected in the last 30 days commit history.")
        sys.exit(0)

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

    print("\n[TIP] AI Analysis Tip: Feed this output to your LLM assistant and ask:")
    print("   'Analyze my recent cognitive focus distribution and suggest updates for my People/Self.md heuristics.'")

if __name__ == "__main__":
    main()
