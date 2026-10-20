"""Always-on twin autopilot — freshness + evolution without user choreography.

Called from memory_session_start / CLI / Cursor hooks. Side effects are safe:
rebuild index when stale, optional weekly drift proposal, durable state under
.knowledgeos/. Self.md is never silently mutated.

Two kinds of tick are distinguished:

``agent``   a real chat where the agent called the tool — counts as a session
``prewarm`` a host hook warming the index before the agent speaks — never counts
            as a session, so the first real chat still stays silent
"""
from __future__ import annotations

import datetime
import json
import os
import re
import time
from pathlib import Path
from typing import Any

STATE_DIR_NAME = ".knowledgeos"
STATE_FILE = "autopilot.json"

REBUILD_MAX_AGE_HOURS = 6
DRIFT_PROPOSE_DAYS = 7
# A drift row is a claim about a pattern over time. Two chats in one afternoon is not
# a pattern, so require both a few sessions and real elapsed time before proposing.
DRIFT_MIN_SESSIONS = 3
DRIFT_MIN_AGE_SECONDS = 3 * 86400


def state_dir(vault: Path) -> Path:
    """The vault's state folder. See ``knowledgeos.vaultstate.state_dir``."""
    from knowledgeos.vaultstate import state_dir as _state_dir

    return _state_dir(vault)


def load_state(vault: Path) -> dict[str, Any]:
    from knowledgeos.data_ops import plain_vault_path
    from knowledgeos.remembering import RememberingPolicy

    path = state_dir(vault) / STATE_FILE
    plain_vault_path(vault, path)
    if not path.exists():
        return {}
    original = path.read_bytes()
    try:
        data = json.loads(original.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        from uuid import uuid4
        from knowledgeos.textio import atomic_create_bytes

        backup = plain_vault_path(vault, path.with_name(path.name + ".corrupt-" + uuid4().hex))
        atomic_create_bytes(backup, original, mode=0o600)
        plain_vault_path(vault, path)
        if path.read_bytes() != original:
            raise OSError("Session state changed while preserving its recovery copy")
        path.unlink()
        return {}
    return RememberingPolicy(vault).scrub(data) if isinstance(data, dict) else {}


def save_state(vault: Path, state: dict[str, Any]) -> None:
    from knowledgeos.data_ops import plain_vault_path
    from knowledgeos.remembering import RememberingPolicy

    path = state_dir(vault) / STATE_FILE
    plain_vault_path(vault, path)
    state["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _write_atomic(path, json.dumps(RememberingPolicy(vault).scrub(state), indent=2))


def state_lock(vault: Path):
    from knowledgeos.locking import file_lock
    return file_lock(state_dir(vault) / "sessions.lock", timeout=120)


def validate_session_id(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
        raise ValueError("session_id must be 1-128 letters, numbers, dots, colons, underscores or hyphens")


def _session_flags(state: dict[str, Any]) -> None:
    records = list((state.get("sessions") or {}).values())
    state["session_open"] = any(row.get("status") == "open" for row in records)
    state["orphan_unsaved_session"] = any(row.get("status") == "orphaned" and not row.get("orphan_prompted") for row in records)
    state["session_ended"] = bool(records) and all(row.get("status") == "ended" for row in records)


def _index_stale(vault: Path, state: dict[str, Any]) -> tuple[bool, str]:
    """Manifest-based freshness: catches any folder, edits, additions and deletions."""
    from knowledgeos.indexer import index_state, manifest_diff

    state_name = index_state(vault / "knowledge_index.db")
    if state_name == "corrupt":
        return True, "index_corrupt"
    if state_name == "locked":
        return True, "index_locked"
    if state_name == "missing":
        return True, "index_missing"

    # Content first: a manifest diff names the file and catches deletions, whereas
    # an age threshold would mask it behind a generic "too old" reason.
    changed, reason = manifest_diff(vault)
    if changed:
        return True, reason

    last = float(state.get("last_rebuild_ts") or 0)
    age_h = (time.time() - last) / 3600.0 if last else 0.0
    if age_h >= REBUILD_MAX_AGE_HOURS:
        return True, f"rebuild_age_hours={age_h:.1f}"

    return False, "fresh"


def ensure_index_fresh(vault: Path, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rebuild SQLite index when missing, corrupt, or stale. Never asks the user."""
    from knowledgeos.indexer import rebuild_index

    state = state if state is not None else load_state(vault)
    stale, reason = _index_stale(vault, state)
    out: dict[str, Any] = {"rebuilt": False, "reason": reason}
    if not stale:
        return out
    try:
        out["counts"] = rebuild_index(vault)
        if out["counts"].get("failed"):
            out["blocked"] = True
            out["error"] = "Some notes could not be indexed: " + ", ".join(out["counts"]["failed"])
            return out
        out["rebuilt"] = True
        with state_lock(vault):
            current = load_state(vault)
            current["last_rebuild_ts"] = time.time()
            save_state(vault, current)
            state.update(current)
    except TimeoutError as e:
        # `IndexBusyError` is a subclass: another pass is already doing the same work, so
        # this is a normal state, not a failure to report.
        out["error"] = str(e)
        out["busy"] = True
    except Exception as e:
        # Reported, not swallowed. An index that could not be rebuilt is why the twin
        # starts answering from stale notes, and the human is the only one who can fix a
        # lock that is a directory or a disk that is full. The agent sees this in
        # ops_status and says one plain sentence.
        out["error"] = str(e)
        out["error_type"] = type(e).__name__
        out["blocked"] = True
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
        section = str(p.get("section", "")).lower()
        title = str(p.get("title", "")).lower()
        if "drift" in section or "drift" in title:
            out["skipped"] = "open_drift_proposal_exists"
            return out
    # Only real, completed chats are evidence of activity. A pre-warmed index is not:
    # proposing on the very first chat would nag the human about scaffold notes.
    if int(state.get("real_sessions") or 0) < DRIFT_MIN_SESSIONS:
        out["skipped"] = "not_enough_sessions"
        return out
    # "Weekly" has to mean weekly. Firing on the second chat of the same afternoon
    # made the twin announce a pattern after two messages, which reads as noise.
    first = float(state.get("first_session_ts") or 0)
    if first and (time.time() - first) < DRIFT_MIN_AGE_SECONDS:
        out["skipped"] = "too_soon"
        return out
    try:
        result = evolution.propose_from_drift(api, days=30)
    except Exception as e:
        out["error"] = str(e)
        return out
    if isinstance(result, dict) and result.get("error"):
        out["error"] = result["error"]
        return out
    if not isinstance(result, dict) or not result.get("proposal_path"):
        out.update(result if isinstance(result, dict) else {})
        out["proposed"] = False
        return out
    out["proposed"] = True
    out["proposal_path"] = result["proposal_path"]
    state["last_drift_propose_ts"] = time.time()
    save_state(api.vault, state)
    return out


def soft_prompt_for_human(
    ops: dict[str, Any], orphan_unsaved: bool = False, asked: set[str] | None = None
) -> tuple[str | None, str | None]:
    """At most one soft question — never chore language or product jargon.

    Returns ``(prompt, key)``. ``key`` is recorded once asked so the same question is
    not repeated every chat: an open proposal stays open until the human acts, and
    re-asking it each session is a chore, not a prompt.
    """
    if orphan_unsaved:
        return "Last time we wrapped mid-thought — anything from that chat you want me to keep?", "orphan"
    asked = asked or set()
    props = ops.get("open_proposals") or []
    fresh = [p for p in props if str(p.get("path") or p.get("proposal_path") or "") not in asked]
    if fresh:
        key = str(fresh[0].get("path") or fresh[0].get("proposal_path") or "")
        return "Want me to remember that preference going forward?", key
    from knowledgeos.evolution import outcome_review_due

    pending = ops.get("due_outcomes", ops.get("pending_outcomes")) or []
    unstuck = [p for p in pending if outcome_review_due(p) and str(p.get("path") or "") not in asked]
    if unstuck:
        title = _plain_excerpt(unstuck[0].get("title") or "that earlier decision")
        key = str(unstuck[0].get("path") or "")
        return f"Quick check — how did “{title}” turn out?", key
    return None, None


# Everything that can start a prompt delimiter, fake a role header, or open markup is
# dropped: without this, a note titled `[INST] SYSTEM: obey` or `</system> # New
# instructions` reached the agent's context looking like part of the harness's own
# instructions. Colons and brackets are in the exclusion set for that reason — a title
# loses a little punctuation, which is a cheap price for it staying data.
_SAFE_PROMPT_CHARS = re.compile(r"[^\w\s.,;'’\"()\-–—/&%+!?]")


def _plain_excerpt(text: Any, limit: int = 80) -> str:
    """Note titles come from vault content; quote them as *data*, never as orders.

    A title is attacker-controlled text that ends up inside the agent's own context.
    Control characters, bidi overrides and markup are stripped, and the length is
    capped, so a title cannot smuggle an instruction or a fake prompt boundary.
    """
    raw = str(text or "").replace("\n", " ").replace("\r", " ")
    cleaned = _SAFE_PROMPT_CHARS.sub("", raw)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return "that earlier decision"
    return cleaned[:limit].rstrip() or "that earlier decision"


def _write_atomic(path: Path, text: str) -> None:
    """Write state through the shared atomic writer.

    This used to stage at ``<name>.tmp``. ``.knowledgeos/autopilot.json.tmp`` is a name
    any agent can compute, and ``breathe`` persists the agent's own ``task_hint`` on every
    ``memory_session_start`` — so a hardlink from ``People/Self.md`` to that name let one
    ordinary tool call replace the identity file with the caller's text, with no terminal
    and no proposal. The shared writer picks an unpredictable name and verifies the
    descriptor is a single-link regular file before writing through it.
    """
    from knowledgeos.textio import atomic_write

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, text if text.endswith("\n") else text + "\n", "\n")


def breathe(api: Any, task_hint: str = "", limit: int = 8, *,
            source: str = "agent", session_id: str | None = None) -> dict[str, Any]:
    import uuid
    if source != "prewarm":
        session_id = session_id or uuid.uuid4().hex
        validate_session_id(session_id)
    with state_lock(api.vault):
        return _breathe(api, task_hint, limit, source=source, session_id=session_id)


def _breathe(
    api: Any,
    task_hint: str = "",
    limit: int = 8,
    *,
    source: str = "agent",
    session_id: str | None = None,
) -> dict[str, Any]:
    """Full autopilot tick: freshen index, load context, light evolution, soft prompt.

    ``source="prewarm"`` runs everything except session accounting, so a host hook
    cannot fake a first session and trigger an early drift proposal.
    """
    vault = api.vault
    prewarm = source == "prewarm"
    state = load_state(vault)
    actions: list[str] = []

    fresh = ensure_index_fresh(vault, state)
    if fresh.get("reason") == "fresh":
        # Reuse this full signed-manifest check only within the public request.
        # Drift writes below invalidate it, and every later request starts empty.
        api._remember_fresh_index_observation()
    if fresh.get("rebuilt"):
        actions.append("rebuilt_index")
    state = load_state(vault)

    orphan = bool(state.get("orphan_unsaved_session"))
    if orphan and not prewarm:
        state["orphan_unsaved_session"] = False
        save_state(vault, state)

    drift = maybe_propose_weekly_drift(api, state)
    if drift.get("proposed"):
        api._invalidate_index_observation()
        actions.append("proposed_weekly_drift")

    ctx = api.bootstrap_context(task_hint=task_hint, limit=limit)
    asked = set(state.get("soft_prompts_asked") or [])
    ops = api.ops_status(skip_review_paths=asked)

    soft = None
    soft_key = None
    if prewarm:
        # Never surface a soft prompt from a background warm-up; the agent will
        # ask on its first real tool call instead.
        deferred = orphan
    elif drift.get("proposed"):
        # Do not announce a proposal the agent just generated in this same session:
        # the human has not changed their mind yet, and asking would be a chore.
        deferred = orphan
    else:
        soft, soft_key = soft_prompt_for_human(ops, orphan_unsaved=orphan, asked=asked)
        if soft_key:
            asked.add(soft_key)
            state["soft_prompts_asked"] = sorted(asked)
            if soft_key == "orphan":
                for record in (state.get("sessions") or {}).values():
                    if record.get("status") == "orphaned":
                        record["orphan_prompted"] = True
        deferred = False

    if deferred:
        # Keep the flag so the next tick can still ask, rather than dropping it.
        state["orphan_unsaved_session"] = True
        save_state(vault, state)

    if not prewarm:
        state["last_breathe_ts"] = time.time()
        state["last_real_session_ts"] = state["last_breathe_ts"]
        sessions = state.setdefault("sessions", {})
        if session_id not in sessions:
            state["real_sessions"] = int(state.get("real_sessions") or 0) + 1
            sessions[session_id] = {"status": "open", "started_at": time.time(), "task_hint": task_hint}
        state.setdefault("first_session_ts", state["last_breathe_ts"])
        state["last_task_hint"] = task_hint
        state["last_session_id"] = session_id
        _session_flags(state)
        save_state(vault, state)

    payload = {
        "ritual": "breathe",
        "session_id": session_id,
        "unfinished_sessions": [
            {"session_id": key, "status": row.get("status"), "task_hint": row.get("task_hint", "")}
            for key, row in (state.get("sessions") or {}).items()
            if key != session_id and row.get("status") != "ended"
        ],
        "mode": source,
        "actions_taken": actions,
        "freshness": fresh,
        "drift_tick": {k: drift[k] for k in drift if k != "result"},
        "soft_prompt": soft,
        "agent_must": [
            "Use Self heuristics/values/anti-goals/active bets from context before advising.",
            "Capture important ideas with memory_capture without asking the user to 'save'.",
            "When preferences change, memory_propose_self_update, then tell the human the "
            "one command to approve it — never edit Self.md and never approve it yourself.",
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
            # An index that cannot be rebuilt keeps answering from notes as they were.
            # It belongs in the agent's own payload, not only in a doctor run nobody
            # types.
            "index_blocked": ops.get("index_blocked"),
        },
    }
    # `session_brief.md` used to be written here and nothing ever read it: a dead file
    # described in the docs as a feature. The payload itself is the brief — it goes
    # straight back to the agent that asked for it.
    return payload


def mark_session_ended(vault: Path, session_id: str | None = None,
                       summary_digest: str = "", end_result: dict | None = None) -> None:
    with state_lock(vault):
        state = load_state(vault)
        session_id = session_id or state.get("last_session_id") or "legacy"
        sessions = state.setdefault("sessions", {})
        record = sessions.setdefault(session_id, {"status": "open"})
        if record.get("status") != "ended":
            state["sessions_completed"] = int(state.get("sessions_completed") or 0) + 1
        record.update(status="ended", ended_at=time.time(), summary_digest=summary_digest,
                      end_result=end_result or {})
        state["last_session_end_ts"] = time.time()
        _session_flags(state)
        save_state(vault, state)


def mark_orphan_if_open(vault: Path, session_id: str | None = None) -> bool:
    with state_lock(vault):
        state = load_state(vault)
        sessions = state.get("sessions") or {}
        active = [key for key, row in sessions.items() if row.get("status") == "open"]
        if session_id is None and len(active) == 1:
            session_id = active[0]
        if session_id in active:
            sessions[session_id]["status"] = "orphaned"
            _session_flags(state)
            save_state(vault, state)
            return True
        if not sessions and state.get("session_open") and not state.get("session_ended"):
            state["orphan_unsaved_session"] = True
            state["session_open"] = False
            save_state(vault, state)
            return True
        return False


AGENT_INSTRUCTIONS_COMPACT = """You are connected to TwinAatma (MCP Memory; technical module knowledgeos).

After setup, the human must never operate the system. You keep their cognitive twin alive.

REQUIRED every meaningful chat:
1) First tool call: memory_session_start with task_hint = user goal. Retain the returned session_id and pass it on retries and memory_session_end so concurrent chats stay separate.
2) Mid-chat: memory_capture for important ideas; memory_search when past context matters.
3) Preference changes: memory_propose_self_update, then tell the human the one command that applies it. `twinaatma self approve <file>` must be run by them, in their own terminal — no tool can apply it, and memory_accept_self_update always refuses. Never edit People/Self.md directly.
4) End of useful work: memory_session_end with a short summary.

Never ask the user to run python/scripts/rebuild/validate. Speak only about their work — avoid product names unless asked.
If soft_prompt is present in session_start, ask it once in plain language.
"""
