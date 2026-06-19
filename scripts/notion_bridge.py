#!/usr/bin/env python3
"""Add KnowledgeOS properties to the Notion database + publish note"""
import json, os, sys, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _notion_env

KEY = _notion_env.get_notion_key()
DS_ID = _notion_env.DS_ID

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

def update_database():
    """Add Obsidian Link and Note Type properties to the database"""
    print("Adding KnowledgeOS properties to database...")
    ds = notion_api('GET', f'data_sources/{DS_ID}')
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
        result = notion_api('PATCH', f'data_sources/{DS_ID}', {'properties': props_to_add})
        for k in props_to_add:
            print(f"  Added: {k}")
    else:
        print("  All KnowledgeOS properties already exist.")
    print()

def publish_note_to_notion(note_data):
    """Publish an Obsidian note to the Notion database."""
    properties = {
        'Idea': {'title': [{'text': {'content': note_data.get('title', 'Untitled')}}]},
    }

    if note_data.get('category'):
        properties['Category'] = {'multi_select': [{'name': c} for c in note_data['category']]}
    if note_data.get('status'):
        properties['Status'] = {'select': {'name': note_data['status']}}
    if note_data.get('priority'):
        properties['Priority'] = {'select': {'name': note_data['priority']}}
    if note_data.get('next_action'):
        properties['Next Action'] = {'rich_text': [{'text': {'content': note_data['next_action'][:2000]}}]}
    if note_data.get('context'):
        properties['Context'] = {'select': {'name': note_data['context']}}
    if note_data.get('obsidian_link'):
        properties['Obsidian Link'] = {'url': note_data['obsidian_link']}
    if note_data.get('note_type'):
        properties['Note Type'] = {'select': {'name': note_data['note_type']}}

    body = {
        'parent': {'type': 'data_source_id', 'data_source_id': DS_ID},
        'properties': properties,
    }

    if note_data.get('body'):
        body['children'] = [
            {'object': 'block', 'type': 'paragraph', 'paragraph': {
                'rich_text': [{'text': {'content': note_data['body'][:1990]}}]
            }}
        ]

    result = notion_api('POST', 'pages', body)
    page_id = result.get('id', '')
    page_url = result.get('url', result.get('public_url', ''))
    print(f"  Published to Notion: {page_url}")
    return page_id

if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'setup'

    if action == 'setup':
        update_database()
        print("Database ready for KnowledgeOS publishing.")
        print(f"  Database ID: {DS_ID}")
        print("  To publish: python3 scripts/notion_bridge.py publish '{\"title\":\"...\"}'")

    elif action == 'publish':
        import ast
        note_data_str = sys.argv[2] if len(sys.argv) > 2 else sys.stdin.read()
        try:
            note_data = json.loads(note_data_str)
        except json.JSONDecodeError:
            note_data = ast.literal_eval(note_data_str)
        publish_note_to_notion(note_data)