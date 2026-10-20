"""Evolution helpers: turn drift/outcomes into Self proposals (never silent writes)."""
from __future__ import annotations

import datetime
import re
from dataclasses import asdict, dataclass
from typing import Any

from knowledgeos.memory import MemoryAPI
from knowledgeos.parser import parse_frontmatter


def pending_outcome_reviews(api: MemoryAPI, today: str | None = None) -> list[dict[str, Any]]:
    today = today or datetime.date.today().isoformat()
    return _open_decisions(api, today)


def outcome_review_due(row: dict[str, Any], today: str | None = None) -> bool:
    """Unreviewed decisions need explicit review intent before spending attention."""
    outcome = str(row.get("outcome_status") or "").strip()
    if outcome not in ("", "pending"):
        return False
    review_after = row.get("review_after")
    if review_after is not None and not isinstance(review_after, str):
        return False
    review_after = (review_after or "").strip()
    if not review_after:
        return outcome == "pending"
    try:
        review_date = datetime.date.fromisoformat(review_after)
        current_date = datetime.date.fromisoformat(today) if today else datetime.date.today()
    except (TypeError, ValueError):
        return False
    return review_after == review_date.isoformat() and review_date <= current_date


def _open_decisions(api: MemoryAPI, today: str) -> list[dict[str, Any]]:
    """Decisions still awaiting an outcome, read from the notes.

    The `outcome_status = 'pending'` test used to be SQL against the index. That column is
    stored in a database inside the vault, so it is a claim, not a fact — and it is also
    simply stale whenever another process holds the index. The reviewer closed a decision,
    and in the same session `memory_pending_outcomes` reported it pending, `ops_status`
    told the agent "1 past decision(s) still need an outcome", and the soft prompt asked
    the human "Quick check — how did Pick vendor turn out?" about work they had finished.

    That is the one thing the product promises never to do: spend the human's attention on
    a question they already answered. So the filter moves to the files.
    """
    conn = api._conn()
    rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT title, path, type, outcome_status, review_after, lesson, updated
            FROM notes
            WHERE type = 'decision' AND path NOT LIKE 'Templates/%'
            """
        ).fetchall()
    ]
    conn.close()
    out: list[dict[str, Any]] = []
    for row in api._refresh_rows(api._live_rows(rows), ""):
        if row.get("type") != "decision":
            continue
        outcome = str(row.get("outcome_status") or "").strip()
        if outcome not in ("", "pending"):
            continue
        review_after = str(row.get("review_after") or "").strip()
        row["overdue"] = bool(review_after and outcome_review_due(row, today))
        row["awaiting"] = True
        out.append(row)
    out.sort(key=lambda r: (bool((r.get("review_after") or "").strip()), r.get("updated") or ""))
    return out


def decisions_with_lessons(api: MemoryAPI) -> list[dict[str, Any]]:
    conn = api._conn()
    rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT title, path, type, outcome_status, lesson, updated
            FROM notes
            WHERE type = 'decision' AND path NOT LIKE 'Templates/%'
            ORDER BY updated DESC
            """
        ).fetchall()
    ]
    conn.close()
    out = []
    for row in api._refresh_rows(api._live_rows(rows), ""):
        if row.get("type") != "decision":
            continue
        if not str(row.get("lesson") or "").strip():
            continue
        if str(row.get("outcome_status") or "") not in (
            "confirmed",
            "invalidated",
            "superseded",
        ):
            continue
        out.append(row)
    return out


def _statement(text: str) -> str:
    from knowledgeos.gate import learning_claim_key

    return learning_claim_key(text)


@dataclass(frozen=True)
class _DecisionEvidence:
    source_id: str
    path: str
    title: str
    outcome: str
    lesson: str
    actual_outcome: str
    before: str
    after: str

    def ledger_source(self) -> dict[str, str]:
        return {
            "id": self.source_id,
            "path": self.path,
            "outcome": self.outcome,
            "lesson": _statement(self.lesson),
            "actual_outcome": _statement(self.actual_outcome),
            "before": _statement(self.before),
            "after": _statement(self.after),
        }


def _evidence(note: dict[str, Any], path: str) -> _DecisionEvidence:
    from knowledgeos.indexer import _as_text

    fm = note.get("frontmatter") or {}
    source_path = note.get("path") or path
    def scalar(key: str) -> str:
        value = fm.get(key)
        return value.strip() if isinstance(value, str) else ""

    return _DecisionEvidence(
        scalar("id") or "path:" + source_path,
        source_path, _as_text(fm.get("title")) or source_path,
        scalar("outcome_status"), _as_text(fm.get("lesson")).strip(),
        scalar("actual_outcome"), scalar("belief_before"), scalar("belief_after"),
    )


def _already_in_self(api: MemoryAPI, statement: str) -> bool:
    from knowledgeos.gate import section_body

    text = api.self_path.read_text(encoding="utf-8")
    body = section_body(text, "heuristics") or ""
    wanted = _statement(statement)
    return bool(wanted and any(_statement(line) == wanted for line in body.splitlines()))


def _propose_learning(api: MemoryAPI, statement: str, sources: list[_DecisionEvidence], **proposal: Any) -> dict[str, Any]:
    from knowledgeos import gate

    if _already_in_self(api, statement):
        return {"ok": True, "proposed": False, "mutated_self": False, "suppression": "already_in_self"}
    result = gate.propose(
        api.vault, api.self_path, api.proposals_dir,
        learning_evidence={
            "version": 1, "claim": _statement(statement),
            "sources": [source.ledger_source() for source in sources],
        },
        **proposal,
    )
    if "error" not in result and "suppression" not in result:
        result["proposed"] = True
    result["evidence"] = [asdict(source) for source in sources]
    return result


def _corroborated_changes(api: MemoryAPI) -> list[list[_DecisionEvidence]]:
    notes = []
    for row in api.decisions(limit=10000).get("decisions", []):
        note = api.get_note(row["path"])
        if not note.get("error"):
            notes.append(note)
    superseded = set()
    for note in notes:
        fm = note.get("frontmatter") or {}
        outcome = fm.get("outcome_status")
        if not isinstance(outcome, str) or outcome not in {"confirmed", "invalidated", "superseded"}:
            continue
        refs = fm.get("supersedes") or []
        if isinstance(refs, str):
            refs = [refs]
        if isinstance(refs, list):
            superseded.update(ref.strip().strip("[]") for ref in refs if isinstance(ref, str))
    sources = [_evidence(note, note["path"]) for note in notes]
    counts: dict[str, int] = {}
    for source in sources:
        counts[source.source_id] = counts.get(source.source_id, 0) + 1
    groups: dict[tuple[str, str], list[_DecisionEvidence]] = {}
    targets: dict[str, set[str]] = {}
    for source in sources:
        if source.outcome not in {"confirmed", "invalidated"}:
            continue
        if source.source_id in superseded or source.path in superseded:
            continue
        if counts[source.source_id] != 1 or not re.fullmatch(r"kos:decision:[a-z0-9][a-z0-9_-]*", source.source_id):
            continue
        before, after = _statement(source.before), _statement(source.after)
        if not before or not after or before == after or _statement(source.lesson) != after or not _statement(source.actual_outcome):
            continue
        targets.setdefault(before, set()).add(after)
        groups.setdefault((before, after), []).append(source)
    return [
        sorted(sources, key=lambda source: source.path)
        for (before, _after), sources in sorted(groups.items())
        if len(targets[before]) == 1 and len(sources) >= 2 and len({_statement(source.actual_outcome) for source in sources}) >= 2
    ]


def propose_from_decision_lesson(api: MemoryAPI, path: str) -> dict[str, Any]:
    note = api.get_note(path)
    if note.get("error"):
        return note
    fm = note.get("frontmatter") or {}
    from knowledgeos.indexer import _as_text

    if _as_text(fm.get("type")).strip() != "decision":
        return {"error": "lesson source must be a decision", "path": path}
    outcome = _as_text(fm.get("outcome_status")).strip()
    if outcome not in {"confirmed", "invalidated", "superseded"}:
        return {"error": "decision outcome must be completed before proposing its lesson", "path": path}

    lesson = _as_text(fm.get("lesson")).strip()
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

    source = _evidence(note, path)
    source_path, title = source.path, source.title
    bullet = f"* **From decision [{title}]({source_path})**: {lesson}"
    source = _DecisionEvidence(source.source_id, source.path, source.title, source.outcome, lesson, source.actual_outcome, source.before, source.after)
    return _propose_learning(
        api, lesson, [source],
        summary=f"Promote lesson from decision '{title}' into heuristics",
        section="heuristics",
        proposed_markdown=bullet,
        rationale=(f"Decision outcome '{outcome}' records this lesson. Source: {source_path}. "
                   "This single recorded outcome does not establish a general belief; review before adopting."),
        mode="append",
    )


def propose_from_drift(api: MemoryAPI, days: int = 30) -> dict[str, Any]:
    drift = api.drift(days=days)
    result = {
        "ok": True,
        "proposed": False,
        "mutated_self": False,
        "semantic_change_assessed": False,
        "reason": (
            "Edit counts and update dates describe activity only. No corroborated "
            "explicit before/after change was found, so no identity change has been inferred."
        ),
        "activity": drift,
    }
    for field in ("index_frozen", "index_blocked", "index_frozen_note", "error"):
        if field in drift:
            result[field] = drift[field]
    if drift.get("error"):
        return result
    suppressed = []
    for sources in _corroborated_changes(api):
        first = sources[0]
        links = "; ".join(f"[{source.title}]({source.path}) ({source.outcome})" for source in sources)
        proposal = _propose_learning(
            api, first.after, sources,
            summary="Review a recorded possible preference change",
            section="drift_log", mode="append",
            proposed_markdown=(f"* **Possible change, uncertain**: recorded before: {first.before}; "
                               f"recorded after: {first.after}. Sources: {links}."),
            rationale=(
                "At least two completed decisions with unique stable IDs record this explicit before/after change, "
                "the matching lesson, and distinct outcome narratives. This is recorded corroboration, "
                "not independent verification of the outcomes or your current belief. Matching wording groups "
                "claims only; this suggestion is uncertain and needs your review.\n" +
                "\n".join(f"Source: {source.path}; outcome ({source.outcome}): {source.actual_outcome}; lesson: {source.lesson}" for source in sources)
            ),
        )
        combined = {
            **result, **proposal, "semantic_change_assessed": True,
            "reason": proposal.get("reason") or "Completed decision records contain an explicit possible change; the suggestion remains uncertain.",
        }
        if proposal.get("proposed") or proposal.get("error"):
            return api._note_frozen(combined)
        suppressed.append(combined)
    return api._note_frozen(suppressed[0] if suppressed else result)


def _proposal_status(fm: dict, text: str) -> str:
    """Normalized proposal status. Old DBs used 'refined' for accepted proposals."""
    status = str(fm.get("status") or "").strip().lower()
    if status == "refined" and "## Applied" in text:
        return "accepted"
    if "## Applied" in text and status in {"", "draft"}:
        return "accepted"
    if "## Rejected" in text and status in {"", "draft", "refined"}:
        return "archived"
    return status


def is_open_proposal(fm: dict, text: str) -> bool:
    return _proposal_status(fm, text) == "draft"


def list_open_proposals(api: MemoryAPI) -> list[dict[str, Any]]:
    """Draft proposals that the gate would accept right now (ledger-backed only)."""
    from knowledgeos import gate

    return gate.list_open(api.vault)


def list_all_proposals(api: MemoryAPI) -> dict[str, Any]:
    """Open (trusted) proposals plus files the ledger does not know about."""
    from knowledgeos import gate

    return {
        "open": gate.list_open(api.vault),
        "untrusted": gate.untrusted_proposals(api.vault, api.proposals_dir),
    }


def reject_proposal(api: MemoryAPI, proposal_path: str, reason: str = "") -> dict[str, Any]:
    return api.reject_self_update(proposal_path, reason)
