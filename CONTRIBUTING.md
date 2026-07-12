# Contributing to KnowledgeOS

Thanks for helping. Keep changes aligned with the north star: **portable Self-memory**, not another note UI.

## Principles

1. Markdown + frontmatter remain the source of truth.
2. Indexes, Notion, embeddings (if any) are derived.
3. Self.md mutates only via explicit accept of proposals.
4. Prefer Python stdlib for core paths; optional deps must be clearly optional.
5. Schema changes are additive when possible (`knowledgeos-v0.x`).

## Dev loop

```bash
python scripts/doctor.py
python scripts/rebuild_index.py
python scripts/validate_schema.py
python scripts/smoke_test.py
python -m unittest discover -s tests -v
```

## Pull requests

- Name the phase/checklist item from `Decisions/strategic-implementation-plan-v1.md` when relevant.
- Include schema/template/validator updates together for new fields.
- Do not commit `knowledge_index.db`, `knowledgeos.config.json`, or API keys.
- Prefer small, reviewable diffs.

## MCP / Memory tools

New MCP tools need:

- entry in `knowledgeos/memory.py` (`TOOL_SPECS` + `dispatch`)
- write-policy classification (auto / proposal / never)
- vault path sandboxing via `MemoryAPI._resolve`
