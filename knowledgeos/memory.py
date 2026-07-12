"""KnowledgeOS Memory API — shared by CLI and MCP.

All paths are sandboxed to the vault root. Self mutations are proposal-only
unless explicitly accepted.
"""
from __future__ import annotations

import datetime
import json
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from knowledgeos.parser import parse_frontmatter, split_frontmatter
from knowledgeos.self_model import load_self

SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._\- ]+")


class MemoryAPI:
    def __init__(self, vault: Path | str):
        self.vault = Path(vault).resolve()
        self.db_path = self.vault / "knowledge_index.db"
        self.proposals_dir = self.vault / "People" / "Self-Proposals"
        self.inbox = self.vault / "Inbox"
        self.self_path = self.vault / "People" / "Self.md"

    # --- sandbox ---

    def _resolve(self, rel_or_abs: str | Path) -> Path:
        raw = Path(rel_or_abs)
        path = raw if raw.is_absolute() else (self.vault / raw)
        path = path.resolve()
        try:
            path.relative_to(self.vault)
        except ValueError as e:
            raise PermissionError(f"Path escapes vault sandbox: {rel_or_abs}") from e
        return path

    def _rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.vault).as_posix()

    def _conn(self) -> sqlite3.Connection:
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"Index missing at {self.db_path}. Run: python scripts/rebuild_index.py"
            )
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    # --- tools ---

    def self_get(self) -> dict[str, Any]:
        if not self.self_path.exists():
            return {"error": "People/Self.md not found", "hint": "Run onboarding or init"}
        model = load_self(self.self_path)
        return {
            "path": self._rel(self.self_path),
            "frontmatter": model.frontmatter,
            "summary": model.summary(),
            "sections": model.sections,
        }

    def search(self, query: str, limit: int = 20) -> dict[str, Any]:
        from knowledgeos.search import blended_search

        return blended_search(self.db_path, query, limit)

    def related(self, path_or_id: str, hops: int = 1, limit: int = 30) -> dict[str, Any]:
        hops = 1 if hops not in (1, 2) else hops
        note_path = self._resolve_note(path_or_id)
        if not note_path:
            return {"error": f"note not found: {path_or_id}"}
        rel = self._rel(note_path)
        conn = self._conn()
        neighbors = set()
        frontier = {rel}
        for _ in range(hops):
            nxt = set()
            for src in frontier:
                rows = conn.execute(
                    """
                    SELECT destination FROM links WHERE source = ?
                    UNION
                    SELECT source FROM links WHERE destination = ?
                    """,
                    (src, src),
                ).fetchall()
                for r in rows:
                    dest = r[0]
                    if dest and dest not in neighbors and dest != rel:
                        neighbors.add(dest)
                        nxt.add(dest)
            frontier = nxt
        out = []
        for p in sorted(neighbors)[:limit]:
            row = conn.execute(
                "SELECT title, path, type, status, entity_id FROM notes WHERE path = ?",
                (p,),
            ).fetchone()
            if row:
                out.append(dict(row))
            else:
                out.append({"path": p, "title": Path(p).stem, "type": "", "status": ""})
        conn.close()
        return {"seed": rel, "hops": hops, "related": out}

    def get_note(self, path_or_id: str, max_chars: int = 12000) -> dict[str, Any]:
        path = self._resolve_note(path_or_id)
        if not path or not path.exists():
            return {"error": f"note not found: {path_or_id}"}
        text = path.read_text(encoding="utf-8", errors="replace")
        fm, body = split_frontmatter(text)
        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = True
        return {
            "path": self._rel(path),
            "frontmatter": fm,
            "body": body if not truncated else body[: max(0, max_chars - 500)],
            "truncated": truncated,
            "chars": path.stat().st_size,
        }

    def decisions(
        self,
        status: str | None = None,
        outcome_status: str | None = None,
        project: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        conn = self._conn()
        sql = "SELECT title, path, status, project, entity_id, outcome_status, review_after, lesson, updated FROM notes WHERE type = 'decision'"
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if outcome_status:
            sql += " AND outcome_status = ?"
            params.append(outcome_status)
        if project:
            sql += " AND project LIKE ?"
            params.append(f"%{project}%")
        sql += " ORDER BY updated DESC LIMIT ?"
        params.append(limit)
        try:
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        except sqlite3.OperationalError:
            # Older index without review_after/lesson
            sql = "SELECT title, path, status, project, entity_id, outcome_status, updated FROM notes WHERE type = 'decision'"
            params = []
            if status:
                sql += " AND status = ?"
                params.append(status)
            if outcome_status:
                sql += " AND outcome_status = ?"
                params.append(outcome_status)
            if project:
                sql += " AND project LIKE ?"
                params.append(f"%{project}%")
            sql += " ORDER BY updated DESC LIMIT ?"
            params.append(limit)
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        conn.close()
        return {"count": len(rows), "decisions": rows}

    def drift(self, days: int = 30) -> dict[str, Any]:
        """Best-effort drift using git log; falls back to updated frontmatter."""
        days = max(1, min(int(days), 365))
        git_dir = self.vault / ".git"
        result: dict[str, Any] = {"days": days, "source": None}
        if git_dir.exists():
            try:
                proc = subprocess.run(
                    [
                        "git",
                        "log",
                        f"--since={days}.days.ago",
                        "--name-only",
                        "--pretty=format:",
                    ],
                    cwd=str(self.vault),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if proc.returncode == 0:
                    counts: dict[str, int] = {}
                    for line in proc.stdout.splitlines():
                        line = line.strip().replace("\\", "/")
                        if line.endswith(".md"):
                            folder = line.split("/", 1)[0] if "/" in line else "(root)"
                            counts[folder] = counts.get(folder, 0) + 1
                    result["source"] = "git"
                    result["edits_by_folder"] = dict(
                        sorted(counts.items(), key=lambda x: -x[1])
                    )
                    result["hint"] = "Review Active Bets / heuristics if focus shifted."
                    return result
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                pass

        # Fallback: recently updated notes from index
        conn = self._conn()
        since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT title, path, type, updated FROM notes
                WHERE updated >= ? AND path NOT LIKE 'Templates/%'
                ORDER BY updated DESC LIMIT 40
                """,
                (since,),
            ).fetchall()
        ]
        conn.close()
        result["source"] = "index_updated"
        result["recent_notes"] = rows
        return result

    def capture(self, title: str, content: str = "", tags: list[str] | None = None) -> dict[str, Any]:
        """Auto-write allowed: create an Inbox draft note."""
        self.inbox.mkdir(parents=True, exist_ok=True)
        today = datetime.date.today().isoformat()
        safe = SAFE_NAME_RE.sub("", title).strip() or "capture"
        safe = safe.replace(" ", "-")[:60]
        filename = f"{today}-{safe}.md"
        path = self._resolve(self.inbox / filename)
        # collide-safe
        n = 2
        while path.exists():
            path = self._resolve(self.inbox / f"{today}-{safe}-{n}.md")
            n += 1
        tag_list = tags or ["inbox", "capture"]
        tags_yaml = "[" + ", ".join(tag_list) + "]"
        body = content.strip() or "_Captured via Memory API._"
        text = f"""---
type: research
title: {title}
description: Inbox capture — {title}
schema: knowledgeos-v0.2
status: draft
created: {today}
updated: {today}
timestamp: {today}T00:00:00Z
tags: {tags_yaml}
project:
---

# {title}

{body}

## Links
- [Inbox Index](_Index.md)
- [Self](../People/Self.md)
"""
        path.write_text(text, encoding="utf-8")
        return {"ok": True, "path": self._rel(path), "policy": "auto_write_inbox"}

    def propose_self_update(
        self,
        summary: str,
        section: str,
        proposed_markdown: str,
        rationale: str = "",
    ) -> dict[str, Any]:
        """Write a Self update proposal (does not mutate Self.md)."""
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_section = SAFE_NAME_RE.sub("", section).strip().replace(" ", "_") or "section"
        path = self.proposals_dir / f"{ts}-{safe_section}.md"
        today = datetime.date.today().isoformat()
        text = f"""---
type: research
title: Self proposal — {section}
description: Proposed Self.md update for section '{section}'.
schema: knowledgeos-v0.3
status: draft
created: {today}
updated: {today}
timestamp: {today}T00:00:00Z
tags: [self-proposal, ego-node]
project: KnowledgeOS
proposal_section: {section}
proposal_target: People/Self.md
---

# Self proposal — {section}

## Summary
{summary}

## Rationale
{rationale or "_None provided._"}

## Proposed markdown for section `{section}`

```markdown
{proposed_markdown.strip()}
```

## Accept

```bash
python -m knowledgeos memory accept_self_update --path {self._rel(path)}
```

Or MCP tool `memory_accept_self_update` with the proposal path.
"""
        path.write_text(text, encoding="utf-8")
        return {
            "ok": True,
            "proposal_path": self._rel(path),
            "policy": "proposal_only",
            "mutated_self": False,
        }

    def accept_self_update(self, proposal_path: str) -> dict[str, Any]:
        """Apply a Self proposal to People/Self.md (explicit accept)."""
        prop = self._resolve(proposal_path)
        if not prop.exists():
            return {"error": f"proposal not found: {proposal_path}"}
        text = prop.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        section = str(fm.get("proposal_section") or "").strip()
        if not section:
            return {"error": "proposal_section missing in frontmatter"}

        m = re.search(r"```markdown\n(.*?)```", text, re.S)
        if not m:
            return {"error": "could not find ```markdown block in proposal"}
        proposed = m.group(1).strip()

        if not self.self_path.exists():
            return {"error": "People/Self.md missing"}

        self_text = self.self_path.read_text(encoding="utf-8", errors="replace")
        new_text, ok = _replace_self_section(self_text, section, proposed)
        if not ok:
            return {
                "error": f"could not locate section '{section}' in Self.md",
                "hint": "Use canonical keys: heuristics, values, mental_models, anti_goals, active_bets, drift_log",
            }
        # bump updated
        today = datetime.date.today().isoformat()
        new_text = re.sub(
            r"^updated:.*$",
            f"updated: {today}",
            new_text,
            count=1,
            flags=re.M,
        )
        self.self_path.write_text(new_text, encoding="utf-8")
        # mark proposal accepted
        accepted = text.replace("status: draft", "status: refined", 1)
        accepted += f"\n\n## Applied\nAccepted on {today} into People/Self.md.\n"
        prop.write_text(accepted, encoding="utf-8")
        return {
            "ok": True,
            "self_path": self._rel(self.self_path),
            "proposal_path": self._rel(prop),
            "section": section,
            "policy": "explicit_accept",
        }

    def propose_note_update(
        self,
        path_or_id: str,
        summary: str,
        patch_markdown: str,
    ) -> dict[str, Any]:
        """Store a note update proposal under Inbox (does not mutate target)."""
        target = self._resolve_note(path_or_id)
        if not target:
            return {"error": f"note not found: {path_or_id}"}
        self.inbox.mkdir(parents=True, exist_ok=True)
        today = datetime.date.today().isoformat()
        ts = datetime.datetime.now().strftime("%H%M%S")
        out = self.inbox / f"{today}-proposal-{ts}.md"
        rel_target = self._rel(target)
        text = f"""---
type: research
title: Note proposal — {rel_target}
description: Proposed update for {rel_target}
schema: knowledgeos-v0.2
status: draft
created: {today}
updated: {today}
tags: [note-proposal]
proposal_target: {rel_target}
---

# Note proposal — {rel_target}

## Summary
{summary}

## Proposed content

```markdown
{patch_markdown.strip()}
```

Manual apply: review and edit `{rel_target}` (auto-apply not enabled for notes in v1).
"""
        out.write_text(text, encoding="utf-8")
        return {
            "ok": True,
            "proposal_path": self._rel(out),
            "target": rel_target,
            "policy": "proposal_only",
        }

    def timeline(self, days: int = 7, limit: int = 40) -> dict[str, Any]:
        days = max(1, min(int(days), 365))
        since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        conn = self._conn()
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT title, path, type, status, updated, entity_id
                FROM notes
                WHERE (created >= ? OR updated >= ?)
                  AND path NOT LIKE 'Templates/%'
                ORDER BY updated DESC
                LIMIT ?
                """,
                (since, since, limit),
            ).fetchall()
        ]
        conn.close()
        return {"since": since, "count": len(rows), "notes": rows}

    def bootstrap_context(self, task_hint: str = "", limit: int = 8) -> dict[str, Any]:
        """Subconscious load: Self + active work + relevant search."""
        ctx: dict[str, Any] = {
            "task_hint": task_hint,
            "self": self.self_get(),
            "active_projects": [],
            "pending_decision_outcomes": [],
            "relevant": {},
            "stale_warnings": [],
        }
        try:
            conn = self._conn()
            ctx["active_projects"] = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT title, path, status, updated, entity_id FROM notes
                    WHERE type='project' AND status='active' AND path NOT LIKE 'Templates/%'
                    ORDER BY updated DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            ]
            ctx["pending_decision_outcomes"] = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT title, path, outcome_status, updated FROM notes
                    WHERE type='decision' AND (outcome_status='pending' OR outcome_status='' OR outcome_status IS NULL)
                      AND path NOT LIKE 'Templates/%'
                    ORDER BY updated DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            ]
            # Stale: active projects not updated in 21+ days
            cutoff = (datetime.date.today() - datetime.timedelta(days=21)).isoformat()
            ctx["stale_warnings"] = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT title, path, updated FROM notes
                    WHERE type='project' AND status='active'
                      AND updated != '' AND updated < ?
                    ORDER BY updated ASC LIMIT 10
                    """,
                    (cutoff,),
                ).fetchall()
            ]
            conn.close()
        except FileNotFoundError as e:
            ctx["index_error"] = str(e)

        if task_hint.strip():
            ctx["relevant"] = self.search(task_hint, limit=limit)
        return ctx

    def ops_status(self) -> dict[str, Any]:
        """Plain-language hygiene report for agents (not a user chore list)."""
        from knowledgeos import evolution

        pending = evolution.pending_outcome_reviews(self)
        open_props = [
            p
            for p in evolution.list_open_proposals(self)
            if str(p.get("status", "")).lower() not in ("archived", "accepted", "rejected")
        ]
        needs: list[str] = []
        if pending:
            needs.append(
                f"{len(pending)} past decision(s) still need an outcome "
                "(ask the human in plain language only if relevant)."
            )
        if open_props:
            needs.append(
                f"{len(open_props)} preference update(s) await a soft yes/no "
                '("Want me to remember that?").'
            )
        try:
            ctx = self.bootstrap_context(limit=5)
            stale = ctx.get("stale_warnings") or []
            if stale:
                needs.append(
                    f"{len(stale)} active project(s) look stale — mention only if advising on them."
                )
        except Exception:
            stale = []

        due = bool(needs)
        return {
            "attention_needed": due,
            "plain_language": needs
            or ["Twin looks current enough — just help the human; capture important things."],
            "pending_outcomes_count": len(pending),
            "open_proposals_count": len(open_props),
            "pending_outcomes": pending[:8],
            "open_proposals": open_props[:8],
            "agent_instruction": (
                "Do not dump this JSON on the user. Surface at most one short plain-language "
                "question when a human decision is actually needed. You own cadence — they do not."
            ),
        }

    def session_start(self, task_hint: str = "", limit: int = 8) -> dict[str, Any]:
        """Autopilot breath: freshen index, load Self/context, light evolution, soft prompt."""
        from knowledgeos.autopilot import breathe

        return breathe(self, task_hint=task_hint, limit=limit)

    def session_end(self, summary: str = "", capture_title: str = "") -> dict[str, Any]:
        """End-of-session: optional Inbox capture + remaining twin work."""
        from knowledgeos.autopilot import mark_session_ended, soft_prompt_for_human

        result: dict[str, Any] = {"ritual": "session_end", "captured": None}
        text = (summary or "").strip()
        if text:
            title = (capture_title or "").strip() or f"Session {datetime.date.today().isoformat()}"
            result["captured"] = self.capture(
                title,
                f"## Session summary\n\n{text}\n",
                tags=["session", "episodic"],
            )
        ops = self.ops_status()
        soft = soft_prompt_for_human(ops, orphan_unsaved=False)
        result["ops"] = {
            "attention_needed": ops["attention_needed"],
            "plain_language": ops["plain_language"],
            "pending_outcomes_count": ops["pending_outcomes_count"],
            "open_proposals_count": ops["open_proposals_count"],
            "open_proposals": ops["open_proposals"],
        }
        result["soft_prompt"] = soft
        result["ask_human"] = (
            soft
            or "If nothing pending, continue helping — do not invent chores or mention KnowledgeOS."
        )
        mark_session_ended(self.vault)
        # Freshen index after captures so next chat stays relevant
        from knowledgeos.autopilot import ensure_index_fresh, load_state

        result["freshness"] = ensure_index_fresh(self.vault, load_state(self.vault))
        return result

    # --- helpers ---

    def _resolve_note(self, path_or_id: str) -> Path | None:
        # By path
        try:
            p = self._resolve(path_or_id)
            if p.exists() and p.suffix.lower() == ".md":
                return p
            if not path_or_id.endswith(".md"):
                p2 = self._resolve(path_or_id + ".md")
                if p2.exists():
                    return p2
        except PermissionError:
            return None
        except Exception:
            pass
        # By entity_id via index
        if self.db_path.exists():
            conn = self._conn()
            row = conn.execute(
                "SELECT path FROM notes WHERE entity_id = ? OR path = ?",
                (path_or_id, path_or_id),
            ).fetchone()
            conn.close()
            if row:
                return self._resolve(row["path"])
        return None


def _snippet(text: str, query: str, radius: int = 90) -> str:
    low = text.lower()
    q = query.lower()
    i = low.find(q)
    if i < 0:
        return text[: radius * 2].replace("\n", " ")
    start = max(0, i - radius)
    end = min(len(text), i + len(query) + radius)
    return text[start:end].replace("\n", " ")


def _replace_self_section(self_text: str, section_key: str, new_body: str) -> tuple[str, bool]:
    """Replace content under a Self section heading matched by kos marker or alias."""
    from knowledgeos.self_model import SECTION_ALIASES

    aliases = SECTION_ALIASES.get(section_key, [section_key])
    lines = self_text.splitlines(keepends=True)
    # Find ## headings
    heading_idxs = [i for i, ln in enumerate(lines) if ln.startswith("## ")]

    def norm(h: str) -> str:
        t = re.sub(r"^#+\s*", "", h).strip()
        t = re.sub(r"^[^\w]+", "", t, flags=re.UNICODE)
        return t.lower()

    target_i = None
    for i in heading_idxs:
        h = norm(lines[i])
        # marker on next lines
        window = "".join(lines[i : i + 3])
        if f"kos:section={section_key}" in window:
            target_i = i
            break
        if any(a in h for a in aliases):
            target_i = i
            break
    if target_i is None:
        return self_text, False

    # end at next ## or EOF
    end_i = len(lines)
    for j in heading_idxs:
        if j > target_i:
            end_i = j
            break

    # Keep heading + optional kos marker line(s), replace rest
    keep_until = target_i + 1
    if keep_until < end_i and "kos:section=" in lines[keep_until]:
        keep_until += 1

    replacement = new_body.strip() + "\n\n"
    new_lines = lines[:keep_until] + [replacement] + lines[end_i:]
    return "".join(new_lines), True


TOOL_SPECS = [
    {
        "name": "memory_self_get",
        "description": "Return the Ego Node (People/Self.md) with parsed heuristics, values, anti-goals, active bets, drift.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "memory_search",
        "description": "Search the KnowledgeOS vault (titles, tags, projects, descriptions, body).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_related",
        "description": "Graph neighbors for a note path or entity id (1 or 2 hops).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path_or_id": {"type": "string"},
                "hops": {"type": "integer", "default": 1},
                "limit": {"type": "integer", "default": 30},
            },
            "required": ["path_or_id"],
        },
    },
    {
        "name": "memory_get_note",
        "description": "Fetch a note by vault-relative path or kos entity id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path_or_id": {"type": "string"},
                "max_chars": {"type": "integer", "default": 12000},
            },
            "required": ["path_or_id"],
        },
    },
    {
        "name": "memory_decisions",
        "description": "List decision notes, optionally filtered by status, outcome_status, project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "outcome_status": {"type": "string"},
                "project": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "memory_drift",
        "description": "Recent cognitive drift summary (git edits by folder, or recent updates).",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 30}},
        },
    },
    {
        "name": "memory_capture",
        "description": "Capture a raw thought into Inbox/ (auto-write allowed).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title"],
        },
    },
    {
        "name": "memory_propose_self_update",
        "description": "Propose a Self.md section update (does NOT mutate Self until accept).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "section": {
                    "type": "string",
                    "description": "heuristics|values|mental_models|anti_goals|active_bets|drift_log",
                },
                "proposed_markdown": {"type": "string"},
                "rationale": {"type": "string"},
            },
            "required": ["summary", "section", "proposed_markdown"],
        },
    },
    {
        "name": "memory_accept_self_update",
        "description": "Explicitly accept a Self proposal and patch People/Self.md.",
        "inputSchema": {
            "type": "object",
            "properties": {"proposal_path": {"type": "string"}},
            "required": ["proposal_path"],
        },
    },
    {
        "name": "memory_propose_note_update",
        "description": "Propose an update to any note (stored in Inbox; manual apply).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path_or_id": {"type": "string"},
                "summary": {"type": "string"},
                "patch_markdown": {"type": "string"},
            },
            "required": ["path_or_id", "summary", "patch_markdown"],
        },
    },
    {
        "name": "memory_timeline",
        "description": "Notes created/updated within a recent time window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 7},
                "limit": {"type": "integer", "default": 40},
            },
        },
    },
    {
        "name": "memory_bootstrap_context",
        "description": "Subconscious load: Self + active projects + pending outcomes + optional search for a task hint.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_hint": {"type": "string"},
                "limit": {"type": "integer", "default": 8},
            },
        },
    },
    {
        "name": "memory_pending_outcomes",
        "description": "List decisions awaiting outcome review (pending / overdue review_after).",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "memory_reject_self_update",
        "description": "Reject a Self proposal without mutating People/Self.md.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "proposal_path": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["proposal_path"],
        },
    },
    {
        "name": "memory_propose_from_drift",
        "description": "Create a Drift Log Self proposal from recent git/index drift (proposal only).",
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 30}},
        },
    },
    {
        "name": "memory_propose_from_lesson",
        "description": "Create a heuristics Self proposal from a closed decision's lesson (proposal only).",
        "inputSchema": {
            "type": "object",
            "properties": {"path_or_id": {"type": "string"}},
            "required": ["path_or_id"],
        },
    },
    {
        "name": "memory_list_self_proposals",
        "description": "List Self proposal files under People/Self-Proposals/.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "memory_session_start",
        "description": (
            "REQUIRED first tool every meaningful chat. Autopilot breath: refreshes the "
            "search index if stale, loads Self + relevant memory, runs light weekly evolution, "
            "returns soft_prompt (ask once in plain language). User must never manage this."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_hint": {"type": "string"},
                "limit": {"type": "integer", "default": 8},
            },
        },
    },
    {
        "name": "memory_session_end",
        "description": (
            "Call when useful work wraps up. Captures summary to Inbox, refreshes index, "
            "returns soft_prompt if a remember-this confirmation is pending."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "capture_title": {"type": "string"},
            },
        },
    },
    {
        "name": "memory_ops_status",
        "description": (
            "Agent hygiene report (pending outcomes, open Self proposals). "
            "Do not dump on user — surface only needed yes/no questions."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "memory_breathe",
        "description": "Alias of memory_session_start — explicit autopilot tick.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_hint": {"type": "string"},
                "limit": {"type": "integer", "default": 8},
            },
        },
    },
]


def dispatch(api: MemoryAPI, name: str, arguments: dict[str, Any] | None = None) -> Any:
    from knowledgeos import evolution

    args = arguments or {}
    mapping = {
        "memory_self_get": lambda: api.self_get(),
        "memory_search": lambda: api.search(args.get("query", ""), int(args.get("limit", 20))),
        "memory_related": lambda: api.related(
            args.get("path_or_id", ""), int(args.get("hops", 1)), int(args.get("limit", 30))
        ),
        "memory_get_note": lambda: api.get_note(
            args.get("path_or_id", ""), int(args.get("max_chars", 12000))
        ),
        "memory_decisions": lambda: api.decisions(
            args.get("status"),
            args.get("outcome_status"),
            args.get("project"),
            int(args.get("limit", 50)),
        ),
        "memory_drift": lambda: api.drift(int(args.get("days", 30))),
        "memory_capture": lambda: api.capture(
            args.get("title", "capture"),
            args.get("content", ""),
            args.get("tags"),
        ),
        "memory_propose_self_update": lambda: api.propose_self_update(
            args.get("summary", ""),
            args.get("section", ""),
            args.get("proposed_markdown", ""),
            args.get("rationale", ""),
        ),
        "memory_accept_self_update": lambda: api.accept_self_update(args.get("proposal_path", "")),
        "memory_propose_note_update": lambda: api.propose_note_update(
            args.get("path_or_id", ""),
            args.get("summary", ""),
            args.get("patch_markdown", ""),
        ),
        "memory_timeline": lambda: api.timeline(int(args.get("days", 7)), int(args.get("limit", 40))),
        "memory_bootstrap_context": lambda: api.bootstrap_context(
            args.get("task_hint", ""), int(args.get("limit", 8))
        ),
        "memory_pending_outcomes": lambda: {
            "count": len(evolution.pending_outcome_reviews(api)),
            "outcomes": evolution.pending_outcome_reviews(api),
        },
        "memory_reject_self_update": lambda: evolution.reject_proposal(
            api, args.get("proposal_path", ""), args.get("reason", "")
        ),
        "memory_propose_from_drift": lambda: evolution.propose_from_drift(
            api, int(args.get("days", 30))
        ),
        "memory_propose_from_lesson": lambda: evolution.propose_from_decision_lesson(
            api, args.get("path_or_id", "")
        ),
        "memory_list_self_proposals": lambda: {
            "proposals": evolution.list_open_proposals(api)
        },
        "memory_session_start": lambda: api.session_start(
            args.get("task_hint", ""), int(args.get("limit", 8))
        ),
        "memory_session_end": lambda: api.session_end(
            args.get("summary", ""), args.get("capture_title", "")
        ),
        "memory_ops_status": lambda: api.ops_status(),
        "memory_breathe": lambda: api.session_start(
            args.get("task_hint", ""), int(args.get("limit", 8))
        ),
    }
    if name not in mapping:
        return {"error": f"unknown tool: {name}"}
    return mapping[name]()
