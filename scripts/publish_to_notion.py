#!/usr/bin/env python3
"""
KnowledgeOS → Notion Publisher

Publishes refined Obsidian notes to a configured Notion database.
Notion is optional — configure via env vars or knowledgeos.config.json.

Usage:
  python scripts/publish_to_notion.py <path-to-note.md>
  python scripts/publish_to_notion.py --dry-run <path-to-note.md>
  python scripts/publish_to_notion.py --dry-run --all

Only publishes notes with frontmatter containing:
  status: refined
  publish_to_notion: true
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import _notion_env
from knowledgeos.parser import split_frontmatter

VAULT_DIR = _ROOT


def _truthy(val) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def notion_api(method, path, data=None, key=None):
    req = urllib.request.Request(
        f"https://api.notion.com/v1/{path}",
        data=json.dumps(data).encode() if data else None,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Notion-Version": "2025-09-03",
            "Content-Type": "application/json",
        },
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def parse_frontmatter(content):
    """Compatibility wrapper — returns (fm, body) like the old local parser."""
    return split_frontmatter(content)


def publish_note(filepath, dry_run=False, key=None, ds_id=None, notion_cfg=None):
    notion_cfg = notion_cfg or {}
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    fm, body = parse_frontmatter(content)

    title = fm.get("title") or os.path.splitext(os.path.basename(filepath))[0]
    rel_path = os.path.relpath(filepath, VAULT_DIR)

    status = fm.get("status", "draft")
    publish = fm.get("publish_to_notion", False)
    if status != "refined" or not _truthy(publish):
        print(f"SKIP: {rel_path}")
        print(f"  status={status}, publish_to_notion={publish}")
        print("  Set status=refined and publish_to_notion=true to publish")
        return False

    tags = fm.get("tags", "")
    if isinstance(tags, list):
        tag_list = tags
    elif isinstance(tags, str):
        tag_list = [t.strip() for t in tags.replace("[", "").replace("]", "").split(",") if t.strip()]
    else:
        tag_list = []

    category_map = notion_cfg.get("category_map") or {
        "ai": "AI/Agents",
        "agent": "AI/Agents",
        "product": "Platform",
        "platform": "Platform",
        "marketing": "GTM",
        "gtm": "GTM",
        "sales": "GTM",
        "content": "Content/Vlog",
        "vlog": "Content/Vlog",
        "ops": "Ops/Systems",
        "system": "Ops/Systems",
        "systems": "Ops/Systems",
        "finance": "Finance",
        "fundraising": "Finance",
        "health": "Health",
        "learning": "Learning",
        "research": "Learning",
    }
    default_category = notion_cfg.get("default_category", "Learning")
    categories = []
    seen = set()
    for t in tag_list:
        mapped = category_map.get(t.lower().strip())
        if mapped and mapped not in seen:
            categories.append(mapped)
            seen.add(mapped)
    if not categories:
        categories = [default_category]

    status_map = notion_cfg.get("status_map") or {
        "active": "Active",
        "draft": "Dumped",
        "refined": "Active",
        "archived": "Archived",
    }
    notion_status = status_map.get(status, "Active")

    notion_priority = "Soon"
    if fm.get("priority") in {"now", "🔥 Now"}:
        notion_priority = "Now"

    next_action = f"Review and process this note: {title}"[:2000]
    note_type = fm.get("type", "concept")
    posix_rel_path = rel_path.replace("\\", "/")
    vault_name = os.path.basename(VAULT_DIR)
    obsidian_link = (
        f"obsidian://open?vault={urllib.parse.quote(vault_name)}"
        f"&file={urllib.parse.quote(posix_rel_path, safe='/')}"
    )
    body_summary = body.strip()[:2000] if body else ""

    props = notion_cfg.get("property_names") or {}
    title_prop = props.get("title", "Idea")
    category_prop = props.get("category", "Category")
    status_prop = props.get("status", "Status")
    priority_prop = props.get("priority", "Priority")
    context_prop = props.get("context", "Context")
    next_action_prop = props.get("next_action", "Next Action")
    link_prop = props.get("obsidian_link", "Obsidian Link")
    type_prop = props.get("note_type", "Note Type")
    status_prefix = notion_cfg.get("status_prefix", "⚡ ")
    priority_prefix = notion_cfg.get("priority_prefix", "🔥 ")
    default_context = notion_cfg.get("default_context", "🧠 Deep Work")

    note_data = {
        "title": title,
        "category": categories,
        "status": f"{status_prefix}{notion_status}",
        "priority": f"{priority_prefix}{notion_priority}",
        "context": default_context,
        "next_action": next_action,
        "obsidian_link": obsidian_link,
        "note_type": note_type,
        "body": body_summary,
    }

    if dry_run:
        print(f"DRY RUN: Would publish {rel_path}")
        print(json.dumps(note_data, indent=2))
        return True

    try:
        result = notion_api(
            "POST",
            "pages",
            {
                "parent": {"type": "data_source_id", "data_source_id": ds_id},
                "properties": {
                    title_prop: {"title": [{"text": {"content": title[:2000]}}]},
                    category_prop: {"multi_select": [{"name": c} for c in categories]},
                    status_prop: {"select": {"name": f"{status_prefix}{notion_status}"}},
                    priority_prop: {"select": {"name": f"{priority_prefix}{notion_priority}"}},
                    context_prop: {"select": {"name": default_context}},
                    next_action_prop: {"rich_text": [{"text": {"content": next_action}}]},
                    link_prop: {"url": obsidian_link},
                    type_prop: {"select": {"name": note_type}},
                },
                "children": [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"text": {"content": body_summary}}]},
                    }
                ]
                if body_summary
                else [],
            },
            key=key,
        )
        page_url = result.get("url", "published")
        print(f"PUBLISHED: {rel_path}")
        print(f"  Notion: {page_url}")
        print(f"  Source: {obsidian_link}")
        return True
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if hasattr(e, "read") else str(e)
        print(f"FAILED: {rel_path}")
        print(f"  HTTP Error {e.code}: {error_body[:300]}")
        return False
    except urllib.error.URLError as e:
        print(f"FAILED: {rel_path}")
        print(f"  Network/DNS Error: {e.reason}")
        return False
    except Exception as e:
        print(f"FAILED: {rel_path}")
        print(f"  Unexpected error: {str(e)}")
        return False


def _collect_publish_candidates() -> list[str]:
    """Find refined notes with publish_to_notion enabled (file scan + index assist)."""
    db_path = os.path.join(VAULT_DIR, "knowledge_index.db")
    candidate_paths: list[str] = []
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT path FROM notes WHERE status='refined' AND path NOT LIKE 'Templates/%'"
            ).fetchall()
            conn.close()
            candidate_paths = [os.path.join(VAULT_DIR, r[0]) for r in rows]
        except Exception as e:
            print(f"Warning: could not query index ({e}); scanning markdown files.")

    if not candidate_paths:
        for root, _dirs, files in os.walk(VAULT_DIR):
            if any(part.startswith(".") for part in root.split(os.sep)):
                continue
            if os.path.basename(root) in {"scripts", "Assets", "Archive"}:
                continue
            for name in files:
                if name.endswith(".md"):
                    candidate_paths.append(os.path.join(root, name))

    selected = []
    for path in candidate_paths:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read(4000)
            fm, _ = parse_frontmatter(content if content.startswith("---") else "---\n---\n" + content)
            # Re-read full file if needed for accurate frontmatter
            with open(path, encoding="utf-8") as f:
                fm, _ = parse_frontmatter(f.read())
            if fm.get("status") == "refined" and _truthy(fm.get("publish_to_notion", False)):
                selected.append(path)
        except OSError:
            continue
    return selected


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    all_mode = "--all" in sys.argv
    files = [a for a in sys.argv[1:] if not a.startswith("--")]

    # Resolve credentials only when not dry-run, or always for --all discovery messaging
    key = None
    ds_id = None
    notion_cfg = _notion_env.get_notion_config()
    if not dry_run:
        key = _notion_env.get_notion_key()
        ds_id = _notion_env.get_notion_database_id()
    else:
        # Dry-run can proceed without credentials; try config for property preview only
        try:
            key = os.environ.get("NOTION_API_KEY") or None
        except Exception:
            key = None
        try:
            ds_id = (
                os.environ.get("NOTION_DATA_SOURCE_ID")
                or os.environ.get("NOTION_DATABASE_ID")
                or notion_cfg.get("data_source_id")
                or notion_cfg.get("database_id")
            )
        except Exception:
            ds_id = None

    if all_mode:
        files = _collect_publish_candidates()
        if not files:
            print("No publishable notes found.")
            print("Mark notes with status=refined and publish_to_notion=true")
            sys.exit(0)
        print(f"Found {len(files)} note(s) with status=refined and publish_to_notion=true")

    if not files:
        print("Usage: python scripts/publish_to_notion.py [--dry-run] <note1.md> [note2.md ...]")
        print("Or:    python scripts/publish_to_notion.py [--dry-run] --all")
        print("\nRequires: status=refined, publish_to_notion=true")
        print("Configure Notion via env or knowledgeos.config.json (see example).")
        sys.exit(1)

    if not dry_run and (not key or not ds_id):
        print("Error: Notion credentials missing for live publish.")
        sys.exit(1)

    success = 0
    for f in files:
        if publish_note(f, dry_run=dry_run, key=key, ds_id=ds_id, notion_cfg=notion_cfg):
            success += 1
        print()

    print(f"Done: {success}/{len(files)} published")
    if dry_run:
        print("(dry run — no changes made to Notion)")
