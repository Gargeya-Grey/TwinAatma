# Contributing to TwinAatma (`knowledgeos`)

Thanks for helping. Keep changes aligned with the north star: **portable Self-memory**,
not another note UI.

## Principles

1. Markdown + frontmatter remain the source of truth.
2. Indexes, Notion, embeddings (if any) are derived and disposable.
3. `People/Self.md` mutates only through the gate: signed ledger row → a human approves
   in a terminal. An agent calling a tool can never apply one.
4. Prefer the Python stdlib for core paths; optional deps must be clearly optional.
5. Schema changes are additive when possible (`knowledgeos-v0.x`).

## Dev loop

```bash
pip install -e .          # once; gives you the `twinaatma` console script
python -m knowledgeos doctor --vault <a-throwaway-vault>
python tests/test_core.py -v
python tests/test_docs.py -v
```

Do **not** run the suite with the repository as the vault. It is fine now (every test
builds its own vault in a temp dir) but the repository itself is a live vault, and the
`IsolationTests` case exists to keep it that way.

## Testing contract

Every guarantee in `README.md` must be backed by a test named after it. Three rules,
learned the expensive way:

- A test that writes a vault builds it in a temp directory. Never `MemoryAPI(ROOT)`.
- A gate test asserts **two** things: the error, and `sha256(People/Self.md)` unchanged.
  Use `support.SelfGuard`.
- If a guarantee is not in the test matrix, it does not exist.

## MCP / Memory tools

New MCP tools need:

- an entry in `knowledgeos/memory.py` (`TOOL_SPECS`) and in `dispatch` — `tests/test_docs.py`
  fails if the two lists diverge
- a write-policy classification (auto / proposal / never)
- vault path sandboxing via `MemoryAPI._resolve` (and, for Self, the ledger)
- a test in `tests/test_core.py`
- a docs line in `AGENTS.md` if the agent must change behaviour

## Self write path

All Self mutations go through `knowledgeos/gate.py`. Do not add a second writer.

- Proposal: append a signed ledger row (outside the vault) and render the markdown beside it.
- Apply: TTY check → signed ledger row → draft → body hash match → whole-file hash match →
  section digest match → shape check → atomic replace that preserves line endings.
- Never trust a frontmatter field for provenance; frontmatter is display, the ledger is truth.
- `gate.accept()` (the MCP path) always refuses. Do not add a bypass, and do not add a
  "confirmation code": a code returned in a tool result is read by the model.

## Pull requests

- Reference the decision note in `Decisions/` you are implementing.
- Include schema/template/validator updates together for new fields.
- Do not commit `knowledge_index.db`, `knowledge_index.db-*`, `.knowledgeos/`, or API keys.
- Prefer small, reviewable diffs.
