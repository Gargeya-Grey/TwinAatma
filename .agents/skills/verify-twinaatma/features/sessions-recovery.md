# Survive interruptions without forgetting or nagging

Every useful chat has a durable, attributable outcome. Failures remain visible and recoverable. Parallel chats do not close or overwrite one another.

## Sub-features

- SESSION.1. A summary closes a session only after durable capture.
- SESSION.2. Distinct chats and retries have distinct, idempotent lifecycle state.
- SESSION.3. The same unresolved prompt is not repeatedly presented as new.
- RECOVERY.1. Missing, corrupt, busy, or blocked indexes preserve source truth and report incomplete results.
- RECOVERY.2. Concurrent capture and lock recovery preserve every writer's data.

## How to get to it (user POV)

Finish a useful chat, reopen after interruption, use two chats, or continue while storage/indexing is temporarily unavailable.

## What checks it

Preconditions: synthetic vaults only. Run one suite with `python -B -m unittest discover -s tests -p <file>`.

- Failed wrap. `tests/test_session_repairs.py` and class `FailureRecoveryTests` in `tests/test_stabilization.py`: a capture that fails keeps the session recoverable, and a retry after the storage returns saves exactly one summary.
- Missing summary. `tests/test_mcp_summary_required.py`: the MCP tool and its `memory memory_session_end` CLI alias refuse a missing, empty or whitespace-only summary without closing the chat or writing a note. A valid retry saves exactly one summary and closes that same chat.
- Say once. `tests/test_session_repairs.py` and class `AWaitingProfileChange` in `tests/test_first_contact.py`: a reminder that was given at the start is not repeated at the wrap.
- Corrupt session state. `tests/test_session_repairs.py`: each original payload is kept, and a failed recovery copy refuses a reset.
- Bounded session history. `tests/test_startup_context_budget.py`, with a fresh short `TWIN_STARTUP_BUDGET_ROOT` below work/gc-artifacts/.knowledgeos. A public MCP response fits 16 KiB, labels shortened hints and omitted session counts, and keeps the full stored hints, IDs and status. A partial preview never means that the omitted sessions are absent.
- Capture integrity. `tests/test_capture_transaction.py`, with a fresh short `TWIN_CAPTURE_TRANSACTION_ROOT` beneath work/gc-artifacts/.knowledgeos: the signed stored rows agree with their source notes after tampering, competing SQLite writers and a full-rebuild fallback; a busy index gives a truthful saved-but-not-indexed receipt.
- Index recovery. `tests/test_rebuild_replacement.py`, `tests/test_database_safety.py`, `tests/test_complete_source_scan.py` and `tests/test_stabilization.py`: a failed write rolls back, a linked database or sidecar file is refused and kept, and an incomplete scan is reported as incomplete.
- Lock ownership. `tests/test_lock_repairs.py`: a live writer older than the stale threshold keeps its lock, a killed owner is recovered without waiting, and a failed marker write leaves no lock that cannot be recovered.
- Atomic files. `tests/test_atomic_create.py` and `tests/test_atomic_replace_windows.py`.

Not checked by any script: two chats in separate real host processes, replayed requests across MCP processes, and 20 capture processes at the same moment. The driver for each was removed on 13 November 2026; the last commit that holds it is `69bec1e`.

## Gotchas

Session calls return a session_id; retain and pass it to retries and wrap-up. State mutations serialize under an OS-backed lock and retain separate records. Legacy wrap-up infers an ID only when exactly one unfinished chat exists. No check proves that a real host passes the ID on. Never shorten a lock threshold in production to obtain a green check. Long fault cases need bounded task-owned fixtures and explicit termination records.

The direct `MemoryAPI.session_end` compatibility call can still close an empty session. Summaryless end hooks preserve unfinished work as orphaned rather than inventing an episode. The memory-tool requirement applies at the MCP and CLI dispatch boundary.
