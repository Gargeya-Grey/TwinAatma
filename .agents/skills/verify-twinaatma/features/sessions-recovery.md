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

## Driving it with MCP and isolated process failures

Preconditions: synthetic vaults only. Record child PIDs, ownership, and exact fixture mutations.

- Failed wrap. Run the failure driver. It replaces only its fixture Inbox directory with a retained obstruction file, calls real MCP session_end, then restores the Inbox. Require an error visible at the protocol boundary and unfinished/recoverable session state. Restore storage and require an idempotent retry to save exactly one summary before closing.
- Missing summary. The MCP tool and its `memory memory_session_end` CLI alias require a nonempty summary. Run `python -B -m unittest discover -s tests -p test_mcp_summary_required.py -v`. Require missing, empty and whitespace-only summaries to return an error without closing the chat or writing a note. A valid retry must save exactly one summary and close that same chat. A null or malformed host capture receipt must fail summary acceptance while the remaining host checks still run.
- Ask once. The failure driver creates a proposal, starts a chat that receives its soft prompt, and wraps the chat. Require no duplicate prompt at wrap. Extend through a fresh chat and decline according to the explicit reminder policy.
- Concurrent chats. Open A and B through separate MCP processes. Capture in each. End A and terminate B. Require both captures, A complete, and B alone unfinished. Replay requests and require no duplicate episodes or counter inflation. If the API cannot identify sessions or retries, record a failed capability gate.
- Bounded session history. Run `python -B -X utf8 -m unittest discover -s tests -p test_startup_context_budget.py` with a fresh short `TWIN_STARTUP_BUDGET_ROOT` below work/gc-artifacts/.knowledgeos. Check long and escaped/multibyte prior hints, many unfinished sessions, large response metadata, prewarm IDs, and the 1,000-row serialization control. Public MCP responses must fit 16 KiB, label shortened hints and omitted session counts, preserve full stored hints/IDs/status and identity, and retain replay/end idempotence. The direct MemoryAPI counting control bounds history serialization work without using wall-clock thresholds. A partial preview never means omitted sessions are absent. These checks support existing session/resource outcomes and award no independent host or full resource-budget credit.
- Capture race. Start 20 same-title captures with distinct bodies simultaneously. Require 20 complete files and all bodies recalled after restart. Keep source filenames and tool receipts for correlation.
- Capture integrity. Run `python -B -X utf8 -m unittest discover -s tests -p test_capture_transaction.py -v` with a fresh short `TWIN_CAPTURE_TRANSACTION_ROOT` beneath work/gc-artifacts/.knowledgeos. Require the signed stored rows to agree with their source notes after pre-lock tampering, competing SQLite writers, and full-rebuild fallback. Check current authority after waiting, released ownership before fallback, truthful durable-but-unindexed busy receipts, rollback and idempotent retry. Retain real writer/holder PIDs and exits. A read that rederives correct source text does not by itself prove stored index integrity. The legacy regression bodies using focused fixtures do not prove full initialization. Python 3.9 source-operation checks remain separate from installed-package and generated-hook acceptance.
- Index recovery. Follow [source graph and recovery](../references/source-graph-recovery.md) for the six index cases and both native lock/fault journeys. In a fixture, remove or corrupt the generated index, hold a real SQLite write lock, and obstruct a rebuild path separately. Require current source quotes, visible incompleteness where necessary, no deletion of a live database, and autonomous recovery after releasing the obstruction.
- Lock ownership. Keep a real writer alive beyond the stale threshold and start another. Require no lock theft or replacement-lock removal by the old owner. Terminate the owner, then verify bounded recovery using ownership evidence. An old timestamp alone is insufficient.

## Gotchas

Session calls return a session_id; retain and pass it to retries and wrap-up. State mutations serialize under an OS-backed lock and retain separate records. Legacy wrap-up infers an ID only when exactly one unfinished chat exists. The concurrency driver exercises this source MCP contract. The genuine Codex CLI driver separately checks returned IDs and persisted summaries across two concurrent host processes; desktop and other host propagation remain unverified. Never shorten a lock threshold in production to obtain a green check. Long fault cases need bounded task-owned fixtures and explicit termination records.

The direct `MemoryAPI.session_end` compatibility call can still close an empty session. Summaryless end hooks preserve unfinished work as orphaned rather than inventing an episode. The memory-tool requirement applies at the MCP and CLI dispatch boundary.
