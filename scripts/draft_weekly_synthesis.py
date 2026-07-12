#!/usr/bin/env python
"""Draft a weekly synthesis note from indexed KnowledgeOS activity."""
from __future__ import annotations

import datetime
import sqlite3
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
if str(VAULT) not in sys.path:
    sys.path.insert(0, str(VAULT))

from knowledgeos.evolution import pending_outcome_reviews  # noqa: E402
from knowledgeos.memory import MemoryAPI  # noqa: E402

DB = VAULT / "knowledge_index.db"


def main() -> int:
    if not DB.exists():
        print(f"Error: {DB} not found. Run: python scripts/rebuild_index.py", file=sys.stderr)
        return 1

    today = datetime.date.today()
    since = today - datetime.timedelta(days=7)
    out = VAULT / "Research" / "Synthesis" / f"{today.isoformat()}-weekly-draft.md"

    conn = sqlite3.connect(DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    recent = conn.execute(
        """
        SELECT title, path, type, status, updated
        FROM notes
        WHERE path NOT LIKE 'Templates/%'
          AND (created >= ? OR updated >= ?)
        ORDER BY updated DESC
        """,
        (since.isoformat(), since.isoformat()),
    ).fetchall()
    decisions = [r for r in recent if r["type"] == "decision"]
    projects = conn.execute(
        """
        SELECT title, path, status, updated
        FROM notes
        WHERE type = 'project' AND path NOT LIKE 'Templates/%'
        ORDER BY updated DESC
        """
    ).fetchall()
    conn.close()

    api = MemoryAPI(VAULT)
    try:
        pending = pending_outcome_reviews(api)
    except Exception:
        pending = []

    title = f"Weekly Synthesis Draft — {today}"
    description = f"Auto-drafted weekly synthesis covering {since} to {today}."
    lines = [
        "---",
        "type: synthesis",
        f"title: {title}",
        f"description: {description}",
        "schema: knowledgeos-v0.3",
        "status: draft",
        f"created: {today}",
        f"updated: {today}",
        f"timestamp: {today.isoformat()}T00:00:00Z",
        "tags: [weekly, synthesis, auto-draft]",
        "project: KnowledgeOS",
        "---",
        f"# {title}",
        "",
        f"Period: {since} → {today}",
        "",
        "## Operating Loop Checklist",
        "",
        "Canonical loop: **Capture → Clarify → Connect → Decide → Execute → Record Outcome → Review → Update Self**",
        "",
        "- [ ] Capture: Inbox triaged (`python scripts/daily_capture_report.py`)",
        "- [ ] Clarify: raw notes typed + linked",
        "- [ ] Connect: orphans resolved (`python scripts/validate_schema.py`)",
        "- [ ] Decide: important choices logged in `Decisions/`",
        "- [ ] Execute: next actions moved outside vault if needed",
        "- [ ] Record Outcome: fill `actual_outcome` / `outcome_status` / `lesson`",
        "- [ ] Review: alignment + drift (`python scripts/check_alignment.py`)",
        "- [ ] Update Self: accept/reject proposals under `People/Self-Proposals/`",
        "",
        "## New / Updated Notes",
        "",
    ]
    for r in recent:
        lines.append(f"- [{r['title']}](../../{r['path']}) — {r['type']} / {r['status']}")
    lines += ["", "## Decisions this week", ""]
    if decisions:
        for r in decisions:
            lines.append(f"- [{r['title']}](../../{r['path']})")
    else:
        lines.append("- No explicit decisions logged this week.")

    lines += ["", "## Decisions due for outcome review", ""]
    if pending:
        for r in pending:
            flag = "OVERDUE" if r.get("overdue") else "awaiting"
            ra = r.get("review_after") or "—"
            lines.append(
                f"- [{r['title']}](../../{r['path']}) — {flag}; review_after={ra}; "
                f"outcome_status={r.get('outcome_status') or 'pending'}"
            )
        lines += [
            "",
            "After closing an outcome with a lesson:",
            "```bash",
            "python -m knowledgeos memory memory_propose_from_lesson --path-or-id Decisions/your-decision.md",
            "```",
        ]
    else:
        lines.append("- None pending.")

    lines += ["", "## Active Projects", ""]
    for r in projects:
        lines.append(f"- [{r['title']}](../../{r['path']}) — {r['status']}")
    lines += [
        "",
        "## Self proposals",
        "",
        "```bash",
        "python -m knowledgeos memory memory_list_self_proposals",
        "python -m knowledgeos memory memory_propose_from_drift",
        "```",
        "",
        "## Patterns / Synthesis",
        "",
        "_Fill with human/AI synthesis._",
        "",
        "## Next Week Focus",
        "",
        "- ",
        "",
    ]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
