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
- Capture race. Start 20 same-title captures with distinct bodies simultaneously. Require 20 complete files and all bodies recalled after restart. Keep source filenames and tool receipts for correlation.
- Index recovery. Follow [source graph and recovery](../references/source-graph-recovery.md) for the six index cases and both native lock/fault journeys. In a fixture, remove or corrupt the generated index, hold a real SQLite write lock, and obstruct a rebuild path separately. Require current source quotes, visible incompleteness where necessary, no deletion of a live database, and autonomous recovery after releasing the obstruction.
- Lock ownership. Keep a real writer alive beyond the stale threshold and start another. Require no lock theft or replacement-lock removal by the old owner. Terminate the owner, then verify bounded recovery using ownership evidence. An old timestamp alone is insufficient.

## Gotchas

Session calls return a session_id; retain and pass it to retries and wrap-up. State mutations serialize under an OS-backed lock and retain separate records. Legacy wrap-up infers an ID only when exactly one unfinished chat exists. The concurrency driver exercises this source MCP contract. The genuine Codex CLI driver separately checks returned IDs and persisted summaries across two concurrent host processes; desktop and other host propagation remain unverified. Never shorten a lock threshold in production to obtain a green check. Long fault cases need bounded task-owned fixtures and explicit termination records.

The direct `MemoryAPI.session_end` compatibility call can still close an empty session. Summaryless end hooks preserve unfinished work as orphaned rather than inventing an episode. The memory-tool requirement applies at the MCP and CLI dispatch boundary.
