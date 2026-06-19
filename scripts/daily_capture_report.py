#!/usr/bin/env python
"""Inspect Inbox notes and suggest processing actions."""
from pathlib import Path
import re, json
VAULT=Path(__file__).resolve().parent.parent
inbox=VAULT/'Inbox'
items=[]
for p in inbox.rglob('*.md'):
    if p.name=='_Index.md': continue
    text=p.read_text(encoding='utf-8',errors='replace')
    links=re.findall(r'\[\[[^\]]+\]\]',text)
    kind='research'
    low=text.lower()
    if 'decision' in low: kind='decision'
    elif 'meeting' in low or 'attendees' in low: kind='meeting'
    elif 'experiment' in low or 'hypothesis' in low: kind='experiment'
    elif 'project' in low or 'next action' in low: kind='project'
    items.append({'path':str(p.relative_to(VAULT)).replace('\\','/'),'suggested_type':kind,'has_links':bool(links),'chars':len(text)})
print(json.dumps({'inbox_items':items,'count':len(items)},indent=2))
