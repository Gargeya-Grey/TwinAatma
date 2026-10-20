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
from knowledgeos.remembering import RememberingPolicy, PolicyError
from pathlib import Path

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
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def parse_frontmatter(content):
    """Compatibility wrapper — returns (fm, body) like the old local parser."""
    # Policy reads preserve source bytes. The transport has always used logical
    # newlines, independently of the file's platform or mixed line endings.
    return split_frontmatter(content.replace("\r\n", "\n").replace("\r", "\n"))


def rich_text(text):
    chunks = [{"text": {"content": text[i:i + 2000]}} for i in range(0, len(text), 2000)]
    if len(chunks) > 100:
        raise ValueError("Text exceeds a single supported Notion request; refusing to truncate")
    return chunks


def _plain_text(chunks):
    return "".join(chunk.get("text", {}).get("content", chunk.get("plain_text", "")) for chunk in chunks)


def _property_value(prop):
    for kind in ("title", "rich_text"):
        if kind in prop:
            return _plain_text(prop[kind])
    if "multi_select" in prop:
        return sorted(option["name"] for option in prop["multi_select"])
    if "select" in prop:
        return (prop["select"] or {}).get("name")
    return prop.get("url")


def create_or_match_page(payload, source_link, link_prop, ds_id, key):
    """Converge retries; changed or ambiguous remote pages require manual reconciliation."""
    found = notion_api("POST", f"data_sources/{ds_id}/query", {
        "filter": {"property": link_prop, "url": {"equals": source_link}}, "page_size": 2,
    }, key=key)
    if "results" not in found:
        raise ValueError("Source identity lookup returned no results field")
    matches = found["results"]
    if found.get("has_more") or len(matches) > 1:
        raise ValueError("Multiple remote pages share this source; refusing to create or overwrite")
    if not matches:
        result = notion_api("POST", "pages", payload, key=key)
        if not result.get("id"):
            raise ValueError("Create response omitted page identity; retry will query before creating")
        return result
    page = matches[0]
    properties_match = all(
        _property_value(page.get("properties", {}).get(name, {})) == _property_value(prop)
        for name, prop in payload["properties"].items()
    )
    children = notion_api("GET", f"blocks/{page['id']}/children?page_size=100", key=key)
    blocks = children.get("results", [])
    body_matches = (
        "results" in children and not children.get("has_more")
        and all(block.get("type") == "paragraph" and not block.get("has_children") for block in blocks)
        and "".join(_plain_text(block["paragraph"]["rich_text"]) for block in blocks)
        == "".join(_plain_text(block["paragraph"]["rich_text"]) for block in payload["children"])
    )
    if not properties_match or not body_matches:
        raise ValueError("Existing page differs from source; refusing to overwrite or create a duplicate")
    return page


def publish_note(filepath, dry_run=False, key=None, ds_id=None, notion_cfg=None):
    notion_cfg = notion_cfg or {}
    try:
        content = RememberingPolicy(VAULT_DIR).read(Path(filepath).absolute(), historical=False)
        if content is None:
            raise PolicyError("Source note is unavailable or excluded by the remembering policy.")
    except (OSError, UnicodeError, PolicyError):
        print("FAILED: Source note is unavailable or excluded by the remembering policy.")
        return False

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

    next_action = f"Review and process this note: {title}"
    note_type = fm.get("type", "concept")
    posix_rel_path = rel_path.replace("\\", "/")
    vault_name = os.path.basename(VAULT_DIR)
    obsidian_link = (
        f"obsidian://open?vault={urllib.parse.quote(vault_name)}"
        f"&file={urllib.parse.quote(posix_rel_path, safe='/')}"
    )
    body_summary = body or ""

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

    try:
        payload = {
            "parent": {"type": "data_source_id", "data_source_id": ds_id},
            "properties": {
                title_prop: {"title": rich_text(title)},
                category_prop: {"multi_select": [{"name": c} for c in categories]},
                status_prop: {"select": {"name": f"{status_prefix}{notion_status}"}},
                priority_prop: {"select": {"name": f"{priority_prefix}{notion_priority}"}},
                context_prop: {"select": {"name": default_context}},
                next_action_prop: {"rich_text": rich_text(next_action)},
                link_prop: {"url": obsidian_link},
                type_prop: {"select": {"name": note_type}},
            },
            "children": [
                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [chunk]}}
                for chunk in rich_text(body_summary)
            ],
        }
        if dry_run:
            print(f"DRY RUN: Would publish {rel_path}")
            print(json.dumps(note_data, indent=2))
            return True
        result = create_or_match_page(payload, obsidian_link, link_prop, ds_id, key)
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
    """Select current opted-in source notes, independent of a stale index."""
    from knowledgeos.vault import Vault

    selected = []
    vault = Vault(VAULT_DIR)
    for path in vault.iter_markdown(skip_archive=True):
        if "Templates" in path.relative_to(vault.root).parts[:-1]:
            continue
        try:
            text = RememberingPolicy(VAULT_DIR).read(path, historical=False)
            if text is None:
                continue
            fm, _ = parse_frontmatter(text)
            if fm.get("status") == "refined" and _truthy(fm.get("publish_to_notion", False)):
                selected.append(str(path))
        except (OSError, UnicodeError):
            continue
    return sorted(selected)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    dry_run = "--dry-run" in argv
    all_mode = "--all" in argv
    files = [a for a in argv if not a.startswith("--")]

    key = None
    ds_id = None
    notion_cfg = _notion_env.get_notion_config()
    if not dry_run:
        key = _notion_env.get_notion_key()
        ds_id = _notion_env.get_notion_database_id()

    if all_mode:
        files = _collect_publish_candidates()
        if not files:
            print("No publishable notes found.")
            print("Mark notes with status=refined and publish_to_notion=true")
            return 0
        print(f"Found {len(files)} note(s) with status=refined and publish_to_notion=true")

    if not files:
        print("Usage: python scripts/publish_to_notion.py [--dry-run] <note1.md> [note2.md ...]")
        print("Or:    python scripts/publish_to_notion.py [--dry-run] --all")
        print("\nRequires: status=refined, publish_to_notion=true")
        print("Configure Notion via env or knowledgeos.config.json (see example).")
        return 1

    if not dry_run and (not key or not ds_id):
        print("Error: Notion credentials missing for live publish.")
        return 1

    success = 0
    for f in files:
        if publish_note(f, dry_run=dry_run, key=key, ds_id=ds_id, notion_cfg=notion_cfg):
            success += 1
        print()

    print(f"Done: {success}/{len(files)} published")
    if dry_run:
        print("(dry run — no changes made to Notion)")
    return 0 if success == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
