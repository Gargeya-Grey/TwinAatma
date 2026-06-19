#!/usr/bin/env python
"""Report notes that may be ready for refinement/publishing or need cleanup."""
from pathlib import Path
import re, sqlite3, json
VAULT=Path(__file__).resolve().parent.parent
DB=VAULT/'knowledge_index.db'
conn=sqlite3.connect(DB, timeout=30.0); conn.row_factory=sqlite3.Row
rows=conn.execute("select * from notes where path not like 'Templates/%' order by updated desc, path").fetchall()
report={"ready_candidates":[],"needs_links":[],"placeholders":[],"active_without_next_actions":[]}
for r in rows:
    path=VAULT/r['path']
    text=path.read_text(encoding='utf-8',errors='replace') if path.exists() else ''
    links=re.findall(r'\[\[[^\]]+\]\]', text)
    placeholders=len(re.findall(r'Placeholder|_To fill|To fill|TODO|\n-\s*$', text, re.I|re.M))
    has_next='Next Action' in text or 'Next Actions' in text or 'Next Steps' in text
    body_len=len(re.sub(r'^---.*?---','',text,flags=re.S).strip())
    item={"title":r['title'],"path":r['path'],"type":r['type'],"status":r['status']}
    if not links and r['type'] not in ('index','moc'):
        report['needs_links'].append(item)
    if placeholders:
        report['placeholders'].append(item|{"placeholder_hits":placeholders})
    if r['status']=='active' and r['type'] in ('project','experiment') and not has_next:
        report['active_without_next_actions'].append(item)
    if r['status']=='active' and links and body_len>1200 and placeholders==0:
        report['ready_candidates'].append(item)
print(json.dumps(report,indent=2))
