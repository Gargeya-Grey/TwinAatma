#!/usr/bin/env python3
"""Test Notion API connection - list accessible pages"""
import json, os, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _notion_env

KEY = _notion_env.get_notion_key()

req = urllib.request.Request(
    'https://api.notion.com/v1/search',
    data=json.dumps({'query': '', 'page_size': 10}).encode(),
    headers={
        'Authorization': f'Bearer {KEY}',
        'Notion-Version': '2025-09-03',
        'Content-Type': 'application/json'
    }
)
resp = urllib.request.urlopen(req)
data = json.loads(resp.read())
results = data.get('results', [])

if not results:
    print('No pages or databases found.')
    print('The integration has no access to any pages yet.')
    print()
    print('To fix: In Notion, open your page "Idea Vault and Execution Engine",')
    print('click "..." (top right) scroll down to "Connections"')
    print('find your integration name and toggle it ON.')
else:
    for r in results:
        tid = r.get('id', '')
        obj = r.get('object', '')
        title = ''
        if r.get('title'):
            for t in r['title']:
                title += t.get('text', {}).get('content', '')
        elif r.get('properties'):
            for p in r['properties'].values():
                t = p.get('title', [])
                if t:
                    title = t[0].get('text', {}).get('content', '')
                    break
        if r.get('properties', {}).get('title'):
            for t in r['properties']['title'].get('title', []):
                title += t.get('text', {}).get('content', '')
        print(f'  [{obj}] {title}  ({tid})')