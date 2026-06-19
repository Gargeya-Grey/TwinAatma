#!/usr/bin/env python
"""Draft a weekly synthesis note from indexed KnowledgeOS activity."""
from pathlib import Path
import sqlite3, datetime
VAULT=Path(__file__).resolve().parent.parent
DB=VAULT/'knowledge_index.db'
today=datetime.date.today(); since=today-datetime.timedelta(days=7)
out=VAULT/'Research'/'Synthesis'/f'{today.isoformat()}-weekly-draft.md'
conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
recent=conn.execute("select title,path,type,status,updated from notes where path not like 'Templates/%' and (created>=? or updated>=?) order by updated desc",(since.isoformat(),since.isoformat())).fetchall()
decisions=[r for r in recent if r['type']=='decision']
projects=conn.execute("select title,path,status,updated from notes where type='project' and path not like 'Templates/%' order by updated desc").fetchall()
lines=['---','type: synthesis','status: draft',f'created: {today}',f'updated: {today}','tags: [weekly, synthesis, auto-draft]','project: KnowledgeOS','---',f'# Weekly Synthesis Draft — {today}','',f'Period: {since} → {today}','','## New / Updated Notes','']
for r in recent:
    rel=r['path'][:-3] if r['path'].endswith('.md') else r['path']
    lines.append(f"- [[../../{rel}|{r['title']}]] — {r['type']} / {r['status']}")
lines += ['','## Decisions','']
if decisions:
    for r in decisions:
        rel=r['path'][:-3] if r['path'].endswith('.md') else r['path']
        lines.append(f"- [[../../{rel}|{r['title']}]]")
else: lines.append('- No explicit decisions logged this week.')
lines += ['','## Active Projects','']
for r in projects:
    rel=r['path'][:-3] if r['path'].endswith('.md') else r['path']
    lines.append(f"- [[../../{rel}|{r['title']}]] — {r['status']}")
lines += ['','## Patterns / Synthesis','','_Fill with human/AI synthesis._','','## Next Week Focus','','- ','']
out.parent.mkdir(parents=True,exist_ok=True); out.write_text('\n'.join(lines),encoding='utf-8')
print(f'Wrote {out}')
