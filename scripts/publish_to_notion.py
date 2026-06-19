#!/usr/bin/env python3
"""
KnowledgeOS → Notion Publisher
Publishes refined Obsidian notes to the "Idea Vault & Execution Engine" database.

Usage:
  python3 scripts/publish_to_notion.py <path-to-note.md>
  python3 scripts/publish_to_notion.py --dry-run <path-to-note.md>

Only publishes notes with frontmatter containing:
  status: refined
  publish_to_notion: true
"""
import json, os, re, sys, urllib.request, urllib.error, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _notion_env

KEY = _notion_env.get_notion_key()
DS_ID = _notion_env.DS_ID
VAULT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def notion_api(method, path, data=None):
    req = urllib.request.Request(
        f'https://api.notion.com/v1/{path}',
        data=json.dumps(data).encode() if data else None,
        method=method,
        headers={
            'Authorization': f'Bearer {KEY}',
            'Notion-Version': '2025-09-03',
            'Content-Type': 'application/json'
        }
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())

def parse_frontmatter(content):
    """Extract YAML frontmatter from markdown."""
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)', content, re.DOTALL)
    if not m:
        return {}, content
    yaml_text = m.group(1)
    body = m.group(2)
    
    fm = {}
    for line in yaml_text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if ':' in line:
            key, _, val = line.partition(':')
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val.startswith('[') and val.endswith(']'):
                val = [v.strip() for v in val[1:-1].split(',') if v.strip()]
            fm[key] = val
    return fm, body

def publish_note(filepath, dry_run=False):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    fm, body = parse_frontmatter(content)
    
    title = fm.get('title') or os.path.splitext(os.path.basename(filepath))[0]
    rel_path = os.path.relpath(filepath, VAULT_DIR)
    
    status = fm.get('status', 'draft')
    publish = fm.get('publish_to_notion', 'false')
    if status != 'refined' or publish != 'true':
        print(f"SKIP: {rel_path}")
        print(f"  status={status}, publish_to_notion={publish}")
        print(f"  Set status=refined and publish_to_notion=true to publish")
        return False
    
    tags = fm.get('tags', '')
    if isinstance(tags, list):
        tag_list = tags
    elif isinstance(tags, str):
        tag_list = [t.strip() for t in tags.replace('[','').replace(']','').split(',') if t.strip()]
    else:
        tag_list = []
    
    category_map = {
        'ai': 'AI/Agents', 'agent': 'AI/Agents',
        'product': 'Platform', 'platform': 'Platform',
        'marketing': 'GTM', 'gtm': 'GTM', 'sales': 'GTM',
        'content': 'Content/Vlog', 'vlog': 'Content/Vlog',
        'ops': 'Ops/Systems', 'system': 'Ops/Systems', 'systems': 'Ops/Systems',
        'finance': 'Finance', 'fundraising': 'Finance',
        'health': 'Health',
        'learning': 'Learning', 'research': 'Learning',
    }
    categories = []
    seen = set()
    for t in tag_list:
        t_lower = t.lower().strip()
        mapped = category_map.get(t_lower)
        if mapped and mapped not in seen:
            categories.append(mapped)
            seen.add(mapped)
    
    if not categories:
        categories = ['Learning']
    
    status_map = {
        'active': 'Active',
        'draft': 'Dumped',
        'refined': 'Active',
        'archived': 'Archived',
    }
    notion_status = status_map.get(status, 'Active')
    
    notion_priority = 'Soon'
    if fm.get('priority') == 'now' or fm.get('priority') == '🔥 Now':
        notion_priority = 'Now'
    
    next_action = f"Review and process this note: {title}"[:2000]
    
    note_type = fm.get('type', 'concept')
    
    posix_rel_path = rel_path.replace('\\', '/')
    vault_name = os.path.basename(VAULT_DIR)
    obsidian_link = f"obsidian://open?vault={urllib.parse.quote(vault_name)}&file={urllib.parse.quote(posix_rel_path, safe='/')}"
    
    body_summary = body.strip()[:2000] if body else ''
    
    note_data = {
        'title': title,
        'category': categories,
        'status': f'⚡ {notion_status}',
        'priority': f'🔥 {notion_priority}',
        'context': '🧠 Deep Work',
        'next_action': next_action,
        'obsidian_link': obsidian_link,
        'note_type': note_type,
        'body': body_summary,
    }
    
    if dry_run:
        print(f"DRY RUN: Would publish {rel_path}")
        print(json.dumps(note_data, indent=2))
        return True
    
    try:
        result = notion_api('POST', 'pages', {
            'parent': {'type': 'data_source_id', 'data_source_id': DS_ID},
            'properties': {
                'Idea': {'title': [{'text': {'content': title[:2000]}}]},
                'Category': {'multi_select': [{'name': c} for c in categories]},
                'Status': {'select': {'name': f'⚡ {notion_status}'}},
                'Priority': {'select': {'name': f'🔥 {notion_priority}'}},
                'Context': {'select': {'name': '🧠 Deep Work'}},
                'Next Action': {'rich_text': [{'text': {'content': next_action}}]},
                'Obsidian Link': {'url': obsidian_link},
                'Note Type': {'select': {'name': note_type}},
            },
            'children': [{
                'object': 'block', 'type': 'paragraph',
                'paragraph': {'rich_text': [{'text': {'content': body_summary}}]}
            }] if body_summary else []
        })
        page_url = result.get('url', 'published')
        print(f"PUBLISHED: {rel_path}")
        print(f"  Notion: {page_url}")
        print(f"  Source: {obsidian_link}")
        return True
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if hasattr(e, 'read') else str(e)
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

if __name__ == '__main__':
    if not KEY:
        print("Error: NOTION_API_KEY not found")
        sys.exit(1)
    
    dry_run = '--dry-run' in sys.argv
    all_mode = '--all' in sys.argv
    files = [a for a in sys.argv[1:] if not a.startswith('--')]
    
    if all_mode:
        db_path = os.path.join(VAULT_DIR, 'knowledge_index.db')
        if not os.path.exists(db_path):
            print(f"Error: {db_path} not found. Please run python scripts/rebuild_index.py first.")
            sys.exit(1)
        import sqlite3
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            rows = cur.execute("SELECT path FROM notes WHERE status='refined'").fetchall()
            files = [os.path.join(VAULT_DIR, r[0]) for r in rows]
            conn.close()
        except Exception as e:
            print(f"Error querying database: {e}")
            sys.exit(1)
        if not files or files == [os.path.join(VAULT_DIR, '')]:
            print("No refined notes found. Mark notes with status=refined and publish_to_notion=true")
            sys.exit(0)
        print(f"Found {len(files)} refined notes to publish")
    
    if not files:
        print("Usage: python3 scripts/publish_to_notion.py [--dry-run] <note1.md> [note2.md ...]")
        print("Or:    python3 scripts/publish_to_notion.py [--dry-run] --all")
        print("\nScans frontmatter for: status=refined, publish_to_notion=true")
        sys.exit(1)
    
    success = 0
    for f in files:
        if publish_note(f, dry_run):
            success += 1
        print()
    
    print(f"Done: {success}/{len(files)} published")
    if dry_run:
        print("(dry run — no changes made to Notion)")