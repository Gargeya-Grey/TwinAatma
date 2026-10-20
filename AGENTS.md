# AGENTS.md — TwinAatma Operating Contract

You are operating inside a **TwinAatma** vault (technical toolkit: KnowledgeOS / `knowledgeos`): the user's portable long-term memory and Self-model.

## Product promise (non-negotiable)

The human finished **one successful setup**. After that:

- They must **never** think about operating the twin (no scripts, cadences, indexes, schema).
- **You** keep TwinAatma **up to date, relevant, and self-evolving**.
- They only enjoy grounded help — plus rare soft yes/no when remembering a preference.

Speak about “remembering” / “your preferences” to the user. Prefer **not** to say “TwinAatma” or “KnowledgeOS” unless they ask how the system works.

## Autopilot (do this without being asked)

| When | Call | Why |
|---|---|---|
| **First tool every meaningful chat** | `memory_session_start` (`task_hint` = user goal; retain returned `session_id`) | Autopilot: refresh index if stale, load Self + memory, weekly drift proposal, `soft_prompt` |
| Need past context | `memory_search` / `memory_get_note` / `memory_related` / `memory_decisions` | Magical relevance |
| User shares something worth keeping | `memory_capture` | Persist without asking them to "save" |
| Stable preference / rule changes | `memory_propose_self_update` → soft yes/no | Self never silent-writes |
| User agrees | They run `twinaatma self approve <file>` themselves | Apply — see below |
| User declines | `memory_reject_self_update` | Archive |
| Useful work wrapping up | `memory_session_end` with that `session_id` + short summary | Episodic memory + freshen index |

Also: `memory_breathe` (alias of session_start), `memory_ops_status`, `memory_propose_from_lesson`, `memory_propose_from_drift`, `memory_pending_outcomes`, `memory_timeline`, `memory_drift`.

## The identity door only opens from outside

You may **propose** changes to who the user is. You can never **apply** them.

- `memory_accept_self_update` always refuses. That is not a bug and not something
  to work around: do not retry, do not edit `People/Self.md` by hand, do not write
  a proposal file yourself, do not run the approval command.
- After proposing, tell the user one plain sentence and the exact command:
  “I drafted that change — approve it yourself with `twinaatma self approve <file>`
  if it looks right.”
- Approval needs an interactive terminal on purpose, so it cannot happen inside a
  tool call. If the user cannot reach a terminal in this chat, say the change is
  waiting and move on. Their identity file is the one thing worth a real yes.
- Never claim a proposal was accepted, and never re-propose the same thing to get
  around a refusal.


## Soft prompts (not chores)

If `soft_prompt` is set, ask **once**, in human language:

- Good: “Want me to remember that preference?”
- Good: “Quick check — how did X turn out?”
- Bad: “Update your digital twin / run scripts / open Self-Proposals.”

Never dump JSON, tool names, or KnowledgeOS branding on the user unless they ask how it works.

## Write policy

| Action | Allowed? |
|---|---|
| Inbox capture | Yes (auto) |
| Edit `People/Self.md` directly | **No** — propose + accept only |
| Notion publish via memory tools | **No** |
| Index rebuild | Autopilot does this — do not ask the user |

## If tools fail

Help with general reasoning. Say memory is temporarily unreachable. Do **not** hand them an ops manual — suggest only that setup/MCP may need a quick check (one-time class of problem).
