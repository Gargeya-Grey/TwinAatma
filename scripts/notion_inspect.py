#!/usr/bin/env python3
"""Inspect the Notion data source properties"""
import json, os, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _notion_env

KEY = _notion_env.get_notion_key()
DS_ID = _notion_env.get_notion_database_id()

req = urllib.request.Request(
    f'https://api.notion.com/v1/data_sources/{DS_ID}',
    headers={
        'Authorization': f'Bearer {KEY}',
        'Notion-Version': '2025-09-03'
    }
)
resp = urllib.request.urlopen(req)
data = json.loads(resp.read())

print("=== Data Source Info ===")
print(f"Title: {data.get('title', [{}])[0].get('text',{}).get('content','')}")
print(f"ID: {data.get('id','')}")
print(f"DB ID: {data.get('database_id','')}")
print()

print("=== Properties (Columns) ===")
props = data.get('properties', {})
for name, prop in props.items():
    ptype = prop.get('type', 'unknown')
    print(f"  {name} ({ptype})")
    if ptype == 'select' and prop.get('select',{}).get('options'):
        opts = [o['name'] for o in prop['select']['options']]
        print(f"    Options: {opts}")
    if ptype == 'multi_select' and prop.get('multi_select',{}).get('options'):
        opts = [o['name'] for o in prop['multi_select']['options']]
        print(f"    Options: {opts}")
print()

# Query existing items
print("=== First 3 Items ===")
q = urllib.request.Request(
    f'https://api.notion.com/v1/data_sources/{DS_ID}/query',
    data=json.dumps({'page_size': 3}).encode(),
    headers={
        'Authorization': f'Bearer {KEY}',
        'Notion-Version': '2025-09-03',
        'Content-Type': 'application/json'
    }
)
resp2 = urllib.request.urlopen(q)
items = json.loads(resp2.read())
for item in items.get('results', []):
    pid = item.get('id', '')
    props = item.get('properties', {})
    print(f"\n  Page: {pid}")
    for name, val in props.items():
        ptype = val.get('type', '')
        if ptype == 'title':
            text = ''.join(t.get('text',{}).get('content','') for t in val.get('title',[]))
            print(f"    Title: {text}")
        elif ptype == 'select':
            s = val.get('select')
            print(f"    {name}: {s.get('name','') if s else ''}")
        elif ptype == 'multi_select':
            ms = [x.get('name','') for x in val.get('multi_select',[])]
            print(f"    {name}: {ms}")
        elif ptype == 'rich_text':
            text = ''.join(t.get('text',{}).get('content','') for t in val.get('rich_text',[]))
            if text:
                print(f"    {name}: {text[:100]}")
        elif ptype == 'date':
            d = val.get('date')
            print(f"    {name}: {d.get('start','') if d else ''}")
        elif ptype == 'status':
            s = val.get('status')
            print(f"    {name}: {s.get('name','') if s else ''}")
        elif ptype == 'checkbox':
            print(f"    {name}: {val.get('checkbox')}")
        elif ptype == 'url':
            print(f"    {name}: {val.get('url','')}")
        elif ptype == 'files':
            files = val.get('files',[])
            print(f"    {name}: {len(files)} files")