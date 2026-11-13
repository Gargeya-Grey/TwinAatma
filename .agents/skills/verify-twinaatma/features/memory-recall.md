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

## What checks it

Preconditions: a synthetic person and a task-owned vault. Run one suite with `python -B -m unittest discover -s tests -p <file>`.

- Storage. `first_day.py` and class `McpEndToEndTests` in `tests/test_core.py`: a real capture file, recall after a server restart, and a recalled session summary.
- External edit. `tests/test_request_freshness.py` and `tests/test_source_provenance.py`: an edit, an addition and a removal are seen on the next request, also at the same size with a restored modification time.
- Startup work lists. `tests/test_ops_project_freshness.py`: pending decisions in the startup context, and project and decision types, statuses and outcomes read from the source while indexing is busy.
- Supporting passages. `tests/test_task_excerpts.py`: the current source hash, exact excerpt offsets, an explicit truncation flag and at most 1,200 UTF-8 bytes per excerpt.
- Plain questions. `tests/test_first_contact.py` (class `PlainQuestionSearch`), `tests/test_recall_repairs.py` and `tests/test_startup_relevance.py`: `ranked` holds notes with every word, `possibly_related` holds partial matches, and an unknown question finds nothing.
- Other words and languages. Startup search expands each task word through the built-in concept lexicon (`knowledgeos/concepts.py`: synonyms and translations in nine languages) and ranks words and expansions in one bm25 query; CJK and kana expansions match by substring. A long word also matches its first five letters. `tests/test_concept_expansion.py` and `tests/test_concepts_lexicon.py` require a German note for an English "coffee" hint, a Japanese note for "pottery", an exact rare word ahead of an expansion, and no expansion in direct `search`.
- Vocabulary regressions. `tests/test_multilingual_handoff.py` (the Hindi handoff, literal current and history quotations) and `tests/test_context_recall_regressions.py` (four retired cases). These 38-note and 82-note fixtures do not replace the 126-note evaluation.
- Graph truth. `tests/test_graph_ambiguity.py` and `tests/test_recall_repairs.py`: a Markdown link resolves to its local sibling, an ambiguous wikilink names every candidate, and a fenced example creates no relation.
- Census. `tests/test_note_census_types.py`, `tests/test_template_census.py`, `tests/test_generated_census.py` and `tests/test_complete_source_scan.py`: tooling, templates and generated reports are not personal memory, and an unreadable source is never reported as a complete empty result.
- Recall evaluation. `python -B .agents/skills/verify-twinaatma/scripts/quality.py --output work/gc-artifacts/.knowledgeos/<new-name>` asks all 108 frozen v3 cases against the real startup context: 72 earlier cases and 36 held-out cases that an author with no access to the product wrote. Every fixture keeps all 126 notes. Each split needs every critical source and literal claim in the first eight rows and at least 90 percent of the other sources. It takes about 17 minutes and is not part of the suite. Tune only on the development cases.

Not checked by any script: a grounded answer in a host chat (a source path and a matching quotation for each remembered claim), a correction made in conversation, and capture that follows the retention policy by meaning. The driver for each was removed on 13 November 2026; the last commit that holds it is `69bec1e`.

## Gotchas

An exact-token check does not measure answer relevance or usefulness. Natural task hints now filter conversational filler and retain relevance ordering; the focused recall regression proves specific examples, not general semantic retrieval. Raw Inbox notes are unreviewed evidence, not confirmed identity. The signed remembering policy defines forgetting and historical corrections; a source check does not prove what a real host chat does.
