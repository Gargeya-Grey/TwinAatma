#!/usr/bin/env python3
"""Optional Notion schema setup and explicitly opted-in source-note publishing."""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _notion_env
import publish_to_notion


def update_database(dry_run=False, key=None, ds_id=None):
    """Add Obsidian Link and Note Type properties to the database"""
    if dry_run:
        print("DRY RUN: Would ensure Obsidian Link and Note Type properties exist.")
        return True
    key = key or _notion_env.get_notion_key()
    ds_id = ds_id or _notion_env.get_notion_database_id()
    print("Adding KnowledgeOS properties to database...")
    ds = publish_to_notion.notion_api('GET', f'data_sources/{ds_id}', key=key)
    existing = list(ds.get('properties', {}).keys())
    print(f"Existing properties: {existing}")

    props_to_add = {}
    if 'Obsidian Link' not in existing:
        props_to_add['Obsidian Link'] = {'url': {}}
    if 'Note Type' not in existing:
        props_to_add['Note Type'] = {
            'select': {
                'options': [
                    {'name': 'concept', 'color': 'blue'},
                    {'name': 'project', 'color': 'green'},
                    {'name': 'research', 'color': 'purple'},
                    {'name': 'decision', 'color': 'orange'},
                    {'name': 'synthesis', 'color': 'pink'},
                    {'name': 'experiment', 'color': 'brown'},
                ]
            }
        }

    if props_to_add:
        publish_to_notion.notion_api('PATCH', f'data_sources/{ds_id}', {'properties': props_to_add}, key=key)
        for k in props_to_add:
            print(f"  Added: {k}")
    else:
        print("  All KnowledgeOS properties already exist.")
    print()
    return True


def publish_note_to_notion(note_data, dry_run=False):
    """Publish from the source file; arbitrary JSON cannot establish note opt-in."""
    source = note_data.get("source_path") if isinstance(note_data, dict) else note_data
    if not isinstance(source, str) or not source:
        print("FAILED: Supply a source note path. Unscoped JSON publishing is unsupported.")
        return False
    args = [source]
    if dry_run:
        args.insert(0, "--dry-run")
    return publish_to_notion.main(args) == 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in argv
    argv = [arg for arg in argv if arg != "--dry-run"]
    action = argv[0] if argv else "setup"
    try:
        if action == "setup":
            return 0 if update_database(dry_run=dry_run) else 1
        if action == "publish":
            source = argv[1] if len(argv) > 1 else sys.stdin.read().strip()
            if source.startswith("{"):
                source = json.loads(source)
            return 0 if publish_note_to_notion(source, dry_run=dry_run) else 1
        print("Usage: notion_bridge.py [--dry-run] setup | publish <source-note.md>")
        return 1
    except Exception as exc:
        print(f"FAILED: {exc}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
