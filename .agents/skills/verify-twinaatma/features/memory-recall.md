# Remember useful facts and answer from them

Useful information persists across chats, and advice uses the right current evidence. The assistant recognizes uncertainty and corrections.

## Sub-features

- MEMORY.1. Capture persists and is retrievable in a fresh process.
- MEMORY.2. File edits and removals become visible without human index chores.
- QUALITY.1. Natural questions retrieve relevant evidence within a bounded context.
- QUALITY.2. Answers cite supporting notes, handle contradictions, and abstain when unsupported.
- QUALITY.3. Capture judgment follows an explicit retention policy.
- MEMORY.3. Relative and ambiguous links resolve to the right project or disclose ambiguity.

## How to get to it (user POV)

Share a useful fact in chat A. Ask about it indirectly in a fresh chat B. Correct an earlier fact. Edit a note in the normal editor. Use `memory_search`, `memory_get_note`, or their CLI fallback for diagnostics.

## Driving it with MCP and host chats

Preconditions: use a synthetic person and task-owned vault. Prepare expected facts and allowed captures before the run.

- Deterministic storage. Run the core driver. Require a real capture file, recall after server restart, a matching note body, and a recalled session summary.
- External edit. The core driver edits its captured file and moves it out of the vault. Require recall of the new content, exclusion of the old token, and exclusion after removal.
- Supporting passages. Place a useful fact after a long neutral introduction and ask a natural question. Require its current source hash, exact excerpt offsets, an explicit truncation flag and at most 1,200 UTF-8 bytes per excerpt. Include a heading followed by its supporting fact and a long multilingual paragraph. Repeat after a same-size edit with restored modification time. These development controls supplement the frozen corpus.
- Relevance. Seed a fixed corpus with terse facts, paraphrases, ambiguous names, multilingual notes, distractors, and old/new conflicts. In fresh host chats ask ordinary questions such as "Help me choose a keyboard for travel" after storing "I need a lightweight compact keyboard". Evaluate the entire startup context and final answer, not just an exact-token search.
- Other words and languages. Startup search also expands each task word through the built-in concept lexicon (`knowledgeos/concepts.py`: synonyms and translations in nine languages) and ranks words and expansions in one bm25 query; CJK and kana expansions match by substring. A long word also matches its first five letters. Run `python -B -m unittest tests.test_concept_expansion tests.test_concepts_lexicon`. Require a German note for an English "coffee" hint, a Japanese note for "pottery", an exact rare word ahead of an expansion, and no expansion in direct `search`. Tune only on development splits: `tests/fixtures/quality-dev2.json` is an independent development workload whose author never saw the frozen corpus.
- Genuine Codex example. The host driver captures a synthetic luggage allowance, then recalls it with its exact source in a new host process and abstains on an unsupported shoe size. These examples do not prove the labeled corpus or a correction lifecycle.
- Grounding. Require an identifiable source path and matching quote for every remembered factual assertion. For an unsupported personal question, require uncertainty without invented traits. For conflicting evidence, require explicit resolution or a clarifying question.
- Correction. Say "That earlier preference was only for the trip; my everyday preference is different." Verify the old claim remains attributable to its context and the current answer does not silently apply it globally.
- Graph truth. Run the complete graph journey in [source graph and recovery](../references/source-graph-recovery.md). Require explicit source, raw target and all candidate paths for ambiguous links, alongside any real neighbors. Seed root and project-local notes with the same filename. From a project note link to its local sibling with Markdown, then test explicit vault paths and ambiguous wikilinks. Call `memory_related` and require the literal expected neighbor paths. Fenced examples must not create false relations.
- Selective capture. Include a transient command, useful project decision, synthetic credential, and sensitive third-party detail. Compare persisted content against the explicit retention policy. Use the owner-approved policy recorded in the ideal-system contract; verify the allowed and forbidden persisted content independently.

Use [the source quality recipe](../references/source-identity-quality.md) to run
all frozen labels against actual startup context and retain development and held-out
metrics. Corpus validity does not imply retrieval or answer quality.

## Gotchas

The core driver's exact-token checks do not measure answer relevance or usefulness. Natural task hints now filter conversational filler and retain relevance ordering; the focused recall regression proves specific examples, not general semantic retrieval. Raw Inbox notes are unreviewed evidence, not confirmed identity. The signed remembering policy defines forgetting and historical corrections; source-policy proof and genuine-host behavior remain separate acceptance scopes.
