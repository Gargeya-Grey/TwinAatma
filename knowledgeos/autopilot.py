"""Always-on twin autopilot — freshness + evolution without user choreography.

Called from memory_session_start / CLI / Cursor hooks. Side effects are safe:
rebuild index when stale, optional weekly drift proposal, durable state under
.knowledgeos/. Self.md is never silently mutated.
"""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

STATE_DIR_NAME = ".knowledgeos"
STATE_FILE = "autopilot.json"
BRIEF_FILE = "session_brief.md"

REBUILD_MAX_AGE_HOURS = 6
DRIFT_PROPOSE_DAYS = 7


def state_dir(vault: Path) -> Path:
    d = vault / STATE_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_state(vault: Path) -> dict[str, Any]:
    path = state_dir(vault) / STATE_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(vault: Path, state: dict[str, Any]) -> None:
    path = state_dir(vault) / STATE_FILE
    state["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _index_stale(vault: Path, state: dict[str, Any]) -> tuple[bool, str]:
    db = vault / "knowledge_index.db"
    if not db.exists():
        return True, "index_missing"
    last = float(state.get("last_rebuild_ts") or 0)
    age_h = (time.time() - last) / 3600.0 if last else 999.0
    if age_h >= REBUILD_MAX_AGE_HOURS:
        return True, f"rebuild_age_hours={age_h:.1f}"
    # Newer markdown than DB?
    db_mtime = db.stat().st_mtime
    for folder in ("Inbox", "Decisions", "People", "Projects", "Concepts"):
        root = vault / folder
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            try:
                if p.stat().st_mtime > db_mtime + 1:
                    return True, f"newer_than_index:{p.relative_to(vault).as_posix()}"
            except OSError:
                continue
    return False, "fresh"


def ensure_index_fresh(vault: Path, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rebuild SQLite index when missing or stale. Never asks the user."""
    state = state if state is not None else load_state(vault)
    stale, reason = _index_stale(vault, state)
    out: dict[str, Any] = {"rebuilt": False, "reason": reason}
    if not stale:
        return out
    script = vault / "scripts" / "rebuild_index.py"
    if not script.exists():
        out["error"] = "rebuild_index.py missing"
        return out
    try:
        r = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(vault),
            capture_output=True,
            text=True,
            timeout=180,
        )
        out["rebuilt"] = r.returncode == 0
        out["returncode"] = r.returncode
        if r.returncode != 0:
            out["stderr"] = (r.stderr or "")[-500:]
        else:
            state["last_rebuild_ts"] = time.time()
            save_state(vault, state)
    except Exception as e:
        out["error"] = str(e)
    return out


def maybe_propose_weekly_drift(api: Any, state: dict[str, Any]) -> dict[str, Any]:
    """At most once per DRIFT_PROPOSE_DAYS, create a drift Self proposal if activity exists."""
    from knowledgeos import evolution

    out: dict[str, Any] = {"proposed": False}
    last = float(state.get("last_drift_propose_ts") or 0)
    if last and (time.time() - last) < DRIFT_PROPOSE_DAYS * 86400:
        out["skipped"] = "not_due"
        return out
    open_props = evolution.list_open_proposals(api)
    for p in open_props:
        st = str(p.get("status", "")).lower()
        if st in ("archived", "accepted", "rejected"):
            continue
        section = str(p.get("section", "")).lower()
        title = str(p.get("title", "")).lower()
        if "drift" in section or "drift" in title:
            out["skipped"] = "open_drift_proposal_exists"
            return out
    try:
        result = evolution.propose_from_drift(api, days=30)
    except Exception as e:
        out["error"] = str(e)
        return out
    if isinstance(result, dict) and result.get("error"):
        out["error"] = result["error"]
        return out
    out["proposed"] = True
    out["result"] = {
        k: result.get(k)
        for k in ("path", "proposal_path", "ok", "summary")
        if isinstance(result, dict) and k in result
    }
    # propose_self_update may return proposal path under different keys
    if isinstance(result, dict):
        out["result"]["proposal_path"] = result.get("proposal_path") or result.get("path")
    state["last_drift_propose_ts"] = time.time()
    save_state(api.vault, state)
    return out


def soft_prompt_for_human(ops: dict[str, Any], orphan_unsaved: bool = False) -> str | None:
    """At most one soft question — never chore language or product jargon."""
    if orphan_unsaved:
        return "Last time we wrapped mid-thought — anything from that chat you want me to keep?"
    props = ops.get("open_proposals") or []
    if props:
        return "Want me to remember that preference going forward?"
    pending = ops.get("pending_outcomes") or []
    if pending:
        title = pending[0].get("title") or "that earlier decision"
        return f"Quick check — how did “{title}” turn out?"
    return None


def write_session_brief(vault: Path, payload: dict[str, Any]) -> Path:
    path = state_dir(vault) / BRIEF_FILE
    soft = payload.get("soft_prompt") or "_none_"
    actions = ", ".join(payload.get("actions_taken") or []) or "none"
    lines = [
        "# Twin session brief (TwinAatma autopilot)",
        "",
        "Agent: call `memory_session_start` if you have not this chat. Prefer MCP tools.",
        "Speak to the human only about their work. Do not mention product names, scripts, or hooks.",
        "",
        f"- Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
        f"- Actions taken: {actions}",
        f"- Soft prompt (ask at most once, in plain language): {soft}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def breathe(api: Any, task_hint: str = "", limit: int = 8) -> dict[str, Any]:
    """Full autopilot tick: freshen index, load context, light evolution, soft prompt."""
    vault = api.vault
    state = load_state(vault)
    actions: list[str] = []

    fresh = ensure_index_fresh(vault, state)
    if fresh.get("rebuilt"):
        actions.append("rebuilt_index")
    state = load_state(vault)

    orphan = bool(state.get("orphan_unsaved_session"))
    if orphan:
        state["orphan_unsaved_session"] = False
        save_state(vault, state)

    drift = maybe_propose_weekly_drift(api, state)
    if drift.get("proposed"):
        actions.append("proposed_weekly_drift")

    ctx = api.bootstrap_context(task_hint=task_hint, limit=limit)
    ops = api.ops_status()
    soft = soft_prompt_for_human(ops, orphan_unsaved=orphan)

    state["last_breathe_ts"] = time.time()
    state["last_task_hint"] = task_hint
    state["session_open"] = True
    state["session_ended"] = False
    save_state(vault, state)

    payload = {
        "ritual": "breathe",
        "actions_taken": actions,
        "freshness": fresh,
        "drift_tick": {k: drift[k] for k in drift if k != "result"},
        "soft_prompt": soft,
        "agent_must": [
            "Use Self heuristics/values/anti-goals/active bets from context before advising.",
            "Capture important ideas with memory_capture without asking the user to 'save'.",
            "When preferences change, memory_propose_self_update then ask the soft yes/no — never edit Self.md directly.",
            "If soft_prompt is set, ask it once in plain language (no product names).",
            "Near end of useful work, call memory_session_end with a short summary.",
        ],
        "user_experience_rule": (
            "The human finished setup. Never ask them to run toolkit commands, "
            "rebuild indexes, or manage cadences. Only help; keep the twin current yourself."
        ),
        "context": ctx,
        "ops": {
            "attention_needed": ops["attention_needed"],
            "plain_language": ops["plain_language"],
            "pending_outcomes_count": ops["pending_outcomes_count"],
            "open_proposals_count": ops["open_proposals_count"],
        },
    }
    brief = write_session_brief(vault, payload)
    payload["brief_path"] = str(brief.relative_to(vault)).replace("\\", "/")
    return payload


def mark_session_ended(vault: Path) -> None:
    state = load_state(vault)
    state["session_ended"] = True
    state["session_open"] = False
    state["last_session_end_ts"] = time.time()
    state["orphan_unsaved_session"] = False
    save_state(vault, state)


def mark_orphan_if_open(vault: Path) -> bool:
    """If a session started via autopilot but never ended, flag for next soft prompt."""
    state = load_state(vault)
    if state.get("session_open") and not state.get("session_ended"):
        state["orphan_unsaved_session"] = True
        state["session_open"] = False
        save_state(vault, state)
        return True
    return False


AGENT_INSTRUCTIONS_COMPACT = """You are connected to TwinAatma (MCP Memory; technical module knowledgeos).

After setup, the human must never operate the system. You keep their cognitive twin alive.

REQUIRED every meaningful chat:
1) First tool call: memory_session_start with task_hint = user goal (runs autopilot: freshen index, load Self, soft prompts).
2) Mid-chat: memory_capture for important ideas; memory_search when past context matters.
3) Preference changes: memory_propose_self_update → ask one soft yes/no ("Want me to remember that?"). On yes: memory_accept_self_update. Never edit People/Self.md directly.
4) End of useful work: memory_session_end with a short summary.

Never ask the user to run python/scripts/rebuild/validate. Speak only about their work — avoid product names unless asked.
If soft_prompt is present in session_start, ask it once in plain language.
"""
