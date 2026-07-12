"""Intelligence layer: generated views, tensions, weekly brief, trajectory."""
from __future__ import annotations

import datetime
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from knowledgeos.evolution import list_open_proposals, pending_outcome_reviews
from knowledgeos.memory import MemoryAPI
from knowledgeos.parser import parse_frontmatter
from knowledgeos.self_model import load_self


def _conn(api: MemoryAPI) -> sqlite3.Connection:
    return api._conn()


def stale_active_projects(api: MemoryAPI, days: int = 21) -> list[dict[str, Any]]:
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    conn = _conn(api)
    rows = conn.execute(
        """
        SELECT title, path, updated, status FROM notes
        WHERE type='project' AND status='active' AND path NOT LIKE 'Templates/%'
          AND updated != '' AND updated < ?
        ORDER BY updated ASC
        """,
        (cutoff,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def orphan_notes(api: MemoryAPI) -> list[dict[str, Any]]:
    conn = _conn(api)
    rows = conn.execute(
        """
        SELECT n.title, n.path, n.type, n.status
        FROM notes n
        LEFT JOIN links l ON l.source = n.path OR l.destination = n.path
        WHERE n.path NOT LIKE 'Templates/%'
          AND n.type NOT IN ('index', 'moc')
          AND n.path NOT LIKE 'README.md'
        GROUP BY n.path
        HAVING COUNT(l.id) = 0
        ORDER BY n.type, n.title
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def unreviewed_beliefs(api: MemoryAPI, days: int = 60) -> list[dict[str, Any]]:
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    conn = _conn(api)
    rows = conn.execute(
        """
        SELECT title, path, last_reviewed, confidence, updated
        FROM notes
        WHERE type='belief' AND path NOT LIKE 'Templates/%'
          AND (IFNULL(last_reviewed,'') = '' OR last_reviewed < ?)
        ORDER BY last_reviewed ASC, updated ASC
        """,
        (cutoff,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def emerging_themes(api: MemoryAPI, days: int = 30, limit: int = 15) -> list[dict[str, Any]]:
    """Tag velocity from notes updated in window."""
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    conn = _conn(api)
    rows = conn.execute(
        """
        SELECT tags FROM notes
        WHERE path NOT LIKE 'Templates/%'
          AND (created >= ? OR updated >= ?)
          AND IFNULL(tags,'') != ''
        """,
        (since, since),
    ).fetchall()
    conn.close()
    counter: Counter[str] = Counter()
    for (tags,) in rows:
        if isinstance(tags, str):
            parts = re.split(r"[,\[\]]", tags)
            for p in parts:
                t = p.strip().lower()
                if t and t not in {"tags", ""}:
                    counter[t] += 1
    return [{"tag": k, "count": v} for k, v in counter.most_common(limit)]


def find_tensions(api: MemoryAPI) -> list[dict[str, Any]]:
    """Heuristic tension flags — no NLP."""
    tensions: list[dict[str, Any]] = []
    vault = api.vault

    # 1) Frontmatter supersedes/invalidates pointing at existing notes
    for path in vault.rglob("*.md"):
        if any(p in path.parts for p in (".git", "Templates", "node_modules")):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = parse_frontmatter(text)
        rel = api._rel(path)
        for field in ("invalidates", "supersedes"):
            val = fm.get(field)
            if not val:
                continue
            targets = val if isinstance(val, list) else [val]
            for t in targets:
                t = str(t).strip()
                if not t:
                    continue
                tensions.append(
                    {
                        "kind": field,
                        "source": rel,
                        "target": t,
                        "note": f"{rel} declares {field}: {t}",
                    }
                )

        # 2) Explicit contradicts in body/relations text
        if re.search(r"contradicts?:", text, re.I) or "type: contradicts" in text.lower():
            tensions.append(
                {
                    "kind": "contradicts_mention",
                    "source": rel,
                    "target": "",
                    "note": f"{rel} mentions contradicts relation",
                }
            )

    # 3) Invalidated decisions still linked from active projects
    conn = _conn(api)
    rows = conn.execute(
        """
        SELECT d.title AS decision, d.path AS dpath, p.title AS project, p.path AS ppath
        FROM notes d
        JOIN links l ON l.destination = d.path OR l.source = d.path
        JOIN notes p ON (p.path = l.source OR p.path = l.destination)
        WHERE d.type='decision' AND d.outcome_status='invalidated'
          AND p.type='project' AND p.status='active'
          AND p.path != d.path
        """
    ).fetchall()
    conn.close()
    for r in rows:
        tensions.append(
            {
                "kind": "active_project_links_invalidated_decision",
                "source": r["ppath"],
                "target": r["dpath"],
                "note": f"Active project '{r['project']}' still linked to invalidated decision '{r['decision']}'",
            }
        )

    return tensions


def knowledge_gaps(api: MemoryAPI) -> list[dict[str, Any]]:
    """Active projects with few concept links."""
    conn = _conn(api)
    projects = conn.execute(
        """
        SELECT title, path FROM notes
        WHERE type='project' AND status='active' AND path NOT LIKE 'Templates/%'
        """
    ).fetchall()
    gaps = []
    for p in projects:
        concept_links = conn.execute(
            """
            SELECT COUNT(*) FROM links l
            JOIN notes n ON n.path = l.destination OR n.path = l.source
            WHERE (l.source = ? OR l.destination = ?)
              AND n.type = 'concept'
              AND n.path != ?
            """,
            (p["path"], p["path"], p["path"]),
        ).fetchone()[0]
        if concept_links < 2:
            gaps.append(
                {
                    "title": p["title"],
                    "path": p["path"],
                    "concept_links": concept_links,
                }
            )
    conn.close()
    return gaps


def write_intelligence_views(api: MemoryAPI) -> dict[str, str]:
    """Write generated MOC views. Returns map of view -> path."""
    today = datetime.date.today()
    out_paths: dict[str, str] = {}
    moc = api.vault / "MOCs"

    def write(name: str, title: str, body_lines: list[str]) -> None:
        path = moc / name
        lines = [
            "---",
            "type: moc",
            f"title: {title}",
            f"description: Generated intelligence view — {title}.",
            "schema: knowledgeos-v0.3",
            "status: active",
            f"created: {today}",
            f"updated: {today}",
            f"timestamp: {today.isoformat()}T00:00:00Z",
            "tags: [moc, generated, intelligence]",
            "project: KnowledgeOS",
            "---",
            f"# {title}",
            "",
            f"Auto-generated {today}. Do not hand-edit; regenerate via `python scripts/update_mocs.py`.",
            "",
            *body_lines,
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        out_paths[title] = api._rel(path)

    # Stale projects
    stale = stale_active_projects(api)
    lines = ["## Stale active projects (>21 days)", ""]
    if stale:
        for r in stale:
            lines.append(f"- [{r['title']}](../{r['path']}) — updated {r.get('updated')}")
    else:
        lines.append("- None.")
    write("_MOC_Stale_Projects.md", "Stale Projects", lines)

    # Orphans
    orphans = orphan_notes(api)
    lines = ["## Orphan notes (no links)", ""]
    if orphans:
        for r in orphans[:50]:
            lines.append(f"- [{r['title']}](../{r['path']}) — {r.get('type')}")
        if len(orphans) > 50:
            lines.append(f"- …and {len(orphans) - 50} more")
    else:
        lines.append("- None.")
    write("_MOC_Orphans.md", "Orphan Notes", lines)

    # Beliefs
    beliefs = unreviewed_beliefs(api)
    lines = ["## Beliefs needing review", ""]
    if beliefs:
        for r in beliefs:
            lines.append(
                f"- [{r['title']}](../{r['path']}) — last_reviewed={r.get('last_reviewed') or '—'}; "
                f"confidence={r.get('confidence') or '—'}"
            )
    else:
        lines.append("- None (or no belief notes yet).")
    write("_MOC_Belief_Reviews.md", "Belief Reviews", lines)

    # Themes
    themes = emerging_themes(api)
    lines = ["## Emerging tags (30 days)", ""]
    if themes:
        for t in themes:
            lines.append(f"- `{t['tag']}` — {t['count']}")
    else:
        lines.append("- None.")
    write("_MOC_Emerging_Themes.md", "Emerging Themes", lines)

    # Tensions
    tensions = find_tensions(api)
    lines = ["## Tension flags (heuristic)", ""]
    if tensions:
        for t in tensions[:40]:
            lines.append(f"- **{t['kind']}**: {t['note']}")
    else:
        lines.append("- None detected.")
    write("_MOC_Tensions.md", "Tensions", lines)

    return out_paths


def weekly_intelligence_report(api: MemoryAPI, days: int = 7) -> Path:
    today = datetime.date.today()
    since = today - datetime.timedelta(days=days)
    conn = _conn(api)
    decisions = [
        dict(r)
        for r in conn.execute(
            """
            SELECT title, path, outcome_status, updated FROM notes
            WHERE type='decision' AND path NOT LIKE 'Templates/%'
              AND (created >= ? OR updated >= ?)
            ORDER BY updated DESC
            """,
            (since.isoformat(), since.isoformat()),
        ).fetchall()
    ]
    closed = [
        dict(r)
        for r in conn.execute(
            """
            SELECT title, path, outcome_status, lesson, updated FROM notes
            WHERE type='decision' AND path NOT LIKE 'Templates/%'
              AND outcome_status IN ('confirmed','invalidated','superseded')
              AND updated >= ?
            ORDER BY updated DESC
            """,
            (since.isoformat(),),
        ).fetchall()
    ]
    conn.close()

    drift = api.drift(days=days)
    pending = pending_outcome_reviews(api)
    proposals = [p for p in list_open_proposals(api) if p.get("status") == "draft"]
    gaps = knowledge_gaps(api)
    themes = emerging_themes(api, days=days)
    tensions = find_tensions(api)
    stale = stale_active_projects(api)

    out = api.vault / "Research" / "Synthesis" / f"{today.isoformat()}-intelligence-brief.md"
    lines = [
        "---",
        "type: synthesis",
        f"title: Weekly Intelligence Brief — {today}",
        f"description: Auto-generated intelligence brief for {since} → {today}.",
        "schema: knowledgeos-v0.3",
        "status: draft",
        f"created: {today}",
        f"updated: {today}",
        f"timestamp: {today.isoformat()}T00:00:00Z",
        "tags: [weekly, intelligence, auto-draft]",
        "project: KnowledgeOS",
        "---",
        f"# Weekly Intelligence Brief — {today}",
        "",
        f"Period: {since} → {today}",
        "",
        "## Top decisions (touched this week)",
        "",
    ]
    if decisions:
        for r in decisions:
            lines.append(
                f"- [{r['title']}](../../{r['path']}) — outcome={r.get('outcome_status') or 'pending'}"
            )
    else:
        lines.append("- None.")

    lines += ["", "## Outcomes confirmed / invalidated", ""]
    if closed:
        for r in closed:
            lesson = (r.get("lesson") or "")[:120]
            lines.append(
                f"- [{r['title']}](../../{r['path']}) — `{r.get('outcome_status')}` — {lesson}"
            )
    else:
        lines.append("- None this week.")

    lines += ["", "## Focus drift", ""]
    if drift.get("source") == "git":
        for folder, count in list((drift.get("edits_by_folder") or {}).items())[:10]:
            lines.append(f"- `{folder}` — {count} edits")
    else:
        lines.append(f"- Source: {drift.get('source')}")
        for r in (drift.get("recent_notes") or [])[:8]:
            lines.append(f"- [{r.get('title')}](../../{r.get('path')})")

    lines += ["", "## Emerging themes", ""]
    if themes:
        for t in themes[:10]:
            lines.append(f"- `{t['tag']}` × {t['count']}")
    else:
        lines.append("- None.")

    lines += ["", "## Pending Self proposals", ""]
    if proposals:
        for p in proposals:
            lines.append(f"- [{p['title']}](../../{p['path']}) — section `{p.get('section')}`")
    else:
        lines.append("- None open.")

    lines += ["", "## Open outcome loops", ""]
    if pending:
        for r in pending:
            flag = "OVERDUE" if r.get("overdue") else "awaiting"
            lines.append(f"- [{r['title']}](../../{r['path']}) — {flag}")
    else:
        lines.append("- None.")

    lines += ["", "## Knowledge gaps (active projects with <2 concept links)", ""]
    if gaps:
        for g in gaps:
            lines.append(
                f"- [{g['title']}](../../{g['path']}) — concept_links={g['concept_links']}"
            )
    else:
        lines.append("- None.")

    lines += ["", "## Stale active projects", ""]
    if stale:
        for r in stale:
            lines.append(f"- [{r['title']}](../../{r['path']}) — updated {r.get('updated')}")
    else:
        lines.append("- None.")

    lines += ["", "## Tension flags", ""]
    if tensions:
        for t in tensions[:20]:
            lines.append(f"- **{t['kind']}**: {t['note']}")
    else:
        lines.append("- None detected.")

    lines += [
        "",
        "## Next actions",
        "",
        "- Review Outcomes Dashboard",
        "- Accept/reject Self proposals",
        "- Close overdue decision outcomes",
        "",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def learning_trajectory_report(api: MemoryAPI) -> Path:
    today = datetime.date.today()
    out = api.vault / "Research" / "Synthesis" / f"{today.isoformat()}-learning-trajectory.md"
    lines = [
        "---",
        "type: synthesis",
        f"title: Learning Trajectory — How my thinking changed",
        "description: Timeline of Self drift log entries and major decisions.",
        "schema: knowledgeos-v0.3",
        "status: draft",
        f"created: {today}",
        f"updated: {today}",
        f"timestamp: {today.isoformat()}T00:00:00Z",
        "tags: [trajectory, self, decisions, intelligence]",
        "project: KnowledgeOS",
        "---",
        "# Learning Trajectory — How my thinking changed",
        "",
        f"Generated {today}.",
        "",
        "## Self Drift Log",
        "",
    ]
    if api.self_path.exists():
        model = load_self(api.self_path)
        drift = model.sections.get("drift_log") or "_No drift log section._"
        lines.append(drift)
    else:
        lines.append("_Self.md missing._")

    conn = _conn(api)
    decisions = conn.execute(
        """
        SELECT title, path, created, updated, outcome_status, lesson
        FROM notes
        WHERE type='decision' AND path NOT LIKE 'Templates/%'
        ORDER BY COALESCE(NULLIF(updated,''), created) ASC
        """
    ).fetchall()
    conn.close()

    lines += ["", "## Decision timeline", ""]
    for r in decisions:
        when = r["updated"] or r["created"] or "—"
        lesson = (r["lesson"] or "").strip()
        lesson_bit = f" — lesson: {lesson[:100]}" if lesson else ""
        lines.append(
            f"- **{when}** — [{r['title']}](../../{r['path']}) "
            f"(`{r['outcome_status'] or 'pending'}`){lesson_bit}"
        )

    lines += [
        "",
        "## Reading this",
        "",
        "This is not a list of notes. It is evidence of how beliefs and choices evolved.",
        "Promote durable lessons into Self heuristics via proposals.",
        "",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
