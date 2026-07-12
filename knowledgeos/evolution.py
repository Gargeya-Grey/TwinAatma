"""Evolution helpers: turn drift/outcomes into Self proposals (never silent writes)."""
from __future__ import annotations

import datetime
from typing import Any

from knowledgeos.memory import MemoryAPI
from knowledgeos.parser import parse_frontmatter


def pending_outcome_reviews(api: MemoryAPI, today: str | None = None) -> list[dict[str, Any]]:
    today = today or datetime.date.today().isoformat()
    conn = api._conn()
    rows = conn.execute(
        """
        SELECT title, path, outcome_status, review_after, lesson, updated
        FROM notes
        WHERE type = 'decision'
          AND path NOT LIKE 'Templates/%'
          AND (IFNULL(outcome_status,'') = '' OR outcome_status = 'pending')
        ORDER BY
          CASE WHEN IFNULL(review_after,'') = '' THEN 1 ELSE 0 END,
          review_after ASC,
          updated DESC
        """
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        ra = (d.get("review_after") or "").strip()
        d["overdue"] = bool(ra and ra <= today)
        d["awaiting"] = True
        out.append(d)
    return out


def decisions_with_lessons(api: MemoryAPI) -> list[dict[str, Any]]:
    conn = api._conn()
    rows = conn.execute(
        """
        SELECT title, path, outcome_status, lesson, updated
        FROM notes
        WHERE type = 'decision'
          AND path NOT LIKE 'Templates/%'
          AND IFNULL(lesson,'') != ''
          AND outcome_status IN ('confirmed', 'invalidated', 'superseded')
        ORDER BY updated DESC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def propose_from_decision_lesson(api: MemoryAPI, path: str) -> dict[str, Any]:
    note = api.get_note(path)
    if note.get("error"):
        return note
    fm = note.get("frontmatter") or {}
    lesson = (fm.get("lesson") or "").strip()
    if not lesson:
        body = note.get("body") or ""
        if "## Lesson" in body:
            chunk = body.split("## Lesson", 1)[1]
            lesson = chunk.split("##", 1)[0].strip()
            lesson = "\n".join(
                ln.lstrip("- ").strip()
                for ln in lesson.splitlines()
                if ln.strip() and not ln.strip().startswith("<!--")
            ).strip()
    if not lesson:
        return {"error": "no lesson found on decision", "path": path}

    title = fm.get("title") or path
    bullet = f"* **From decision [{title}]({path})**: {lesson}"
    return api.propose_self_update(
        summary=f"Promote lesson from decision '{title}' into heuristics",
        section="heuristics",
        proposed_markdown=bullet,
        rationale=f"Decision outcome closed with a lesson. Path: {path}",
    )


def propose_from_drift(api: MemoryAPI, days: int = 30) -> dict[str, Any]:
    drift = api.drift(days=days)
    today = datetime.date.today().isoformat()
    if drift.get("source") == "git":
        folders = drift.get("edits_by_folder") or {}
        top = list(folders.items())[:5]
        md = (
            f"| Focus drift ({days}d) | Top edited folders: "
            + ", ".join(f"{k} ({v})" for k, v in top)
            + f" | {today} | memory_drift |"
        )
        summary = "Record recent semantic drift in Drift Log"
    else:
        recent = drift.get("recent_notes") or []
        titles = ", ".join((r.get("title") or r.get("path", "")) for r in recent[:5]) or "(none)"
        md = f"| Activity window | Recent notes: {titles} | {today} | index_updated |"
        summary = "Record recent update activity in Drift Log"
    return api.propose_self_update(
        summary=summary,
        section="drift_log",
        proposed_markdown=md,
        rationale=(
            "Auto-generated from drift signals. Review carefully: accepting replaces "
            "the Drift Log section body after the kos marker — merge manually if you "
            "need to keep prior rows."
        ),
    )


def list_open_proposals(api: MemoryAPI) -> list[dict[str, Any]]:
    props = []
    if not api.proposals_dir.exists():
        return props
    for path in sorted(api.proposals_dir.glob("*.md")):
        fm = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        props.append(
            {
                "path": api._rel(path),
                "title": fm.get("title", path.name),
                "status": fm.get("status", ""),
                "section": fm.get("proposal_section", ""),
            }
        )
    return props


def reject_proposal(api: MemoryAPI, proposal_path: str, reason: str = "") -> dict[str, Any]:
    prop = api._resolve(proposal_path)
    if not prop.exists():
        return {"error": f"proposal not found: {proposal_path}"}
    text = prop.read_text(encoding="utf-8", errors="replace")
    today = datetime.date.today().isoformat()
    text = text.replace("status: draft", "status: archived", 1)
    text = text.replace("status: refined", "status: archived", 1)
    text += f"\n\n## Rejected\nRejected on {today}. {reason or '_No reason given._'}\n"
    prop.write_text(text, encoding="utf-8")
    return {
        "ok": True,
        "proposal_path": api._rel(prop),
        "mutated_self": False,
        "policy": "explicit_reject",
    }
