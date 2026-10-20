# Creation assessment, 18 October 2026

The implementation has strong file-truth and identity-proposal defenses, but it has not demonstrated the complete one-setup memory experience. The missing proof includes genuine host use and relevant answers across chats. Several concrete data-preservation and recovery problems also remain.

This assessment covers the installed package's source, CLI and MCP entry points, host hooks, initialization, identity gate, index/search/autopilot, graph/schema/validation, intelligence reports, packaging/CI, primary tests, and auxiliary scripts. It does not claim line-by-line inspection of every file or private note. Product code and preexisting uncommitted work were preserved. No external publishing or real identity approval occurred.

## Evidence binding

The inspected base revision was `e831fdc1a2070acb15eafe3b6e331d3ec07d071a`, with substantial preexisting dirty and untracked product work. This is an assessment of that working tree, not just the committed revision. Driver reports record selected source hashes and the dirty-tree inventory. The earlier baseline logs lack a contemporaneous source manifest, so their binding is limited to the session's inspected tree.

The available session did not expose the project's memory tools. The required first memory call could not be made. This demonstrates a connection gap in this session, not why the host failed to expose them.

## Actual checks

| Check | Result | Scope |
|---|---|---|
| `python -B tests/test_core.py` | FAIL. 200 tests, one failure, one skip. | The destructive-approval screen test expected exit 1, received 2 at the noninteractive-terminal precheck. This is an uncovered test-harness assumption, not evidence of unsafe approval. |
| `python -B tests/test_docs.py` | PASS. 12 tests. | Documented-name/packaging contracts only. |
| `python -B tests/test_stabilization.py` | PASS. 21 tests. | Existing stabilization and verifier checks. |
| `python -B tests/score.py --json` | FAIL. Reported 92.5/100 with two failed approval-screen scenarios and three skips. | Both failed scenarios stop before screen rendering at the same noninteractive CLI guard. The corpus score is not an ideal-product score. |
| New core driver | PASS. 14 assertions on first execution. | Real source CLI and NDJSON MCP subprocesses in an isolated synthetic vault. Capture/restart/read, proposal refusal/rejection, unchanged Self, edit/removal freshness, summary recall, sentinel and source checks. |
| New failure driver | FAIL on two product acceptance cases. | Repeated soft prompt and successful session closure after failed capture, reproduced through real MCP and a task-owned filesystem obstruction. Four setup/isolation assertions passed. |

Baseline logs are under [the retained baseline directory](../../../../work/gc-artifacts/ideal-verification-20261018/baseline). Initial core proof is [this report](../../../../work/gc-artifacts/ideal-verification-20261018/.knowledgeos/journeys/20261018-212524-61b6e7fa/report.json). Initial red proof is [this report](../../../../work/gc-artifacts/ideal-verification-20261018/.knowledgeos/journeys/20261018-212524-d2e00e9f/report.json). Their neighboring transcripts contain requests and responses. Task-owned fixture directories were relocated beneath .knowledgeos after a census defect was found; relocation.json retains original-to-current paths and confirms unchanged file hashes. Original transcripts still name their original execution paths. Final handoff evidence may add later runs without replacing these.

## Findings that should determine the first work

| Priority | Finding and consequence | Evidence strength and source | Acceptance gate |
|---|---|---|---|
| P0 | Legacy export can remove identity or selected source before collecting notes. An existing `--out People` or `--out Concepts` passes the descendant check, then `rmtree` runs. String-prefix containment also confuses sibling paths. | Static. `scripts/export_bundle.py:81-103`. Not executed against the working vault. | DATA, IDENTITY |
| P0 | Link-maintenance scans all Markdown and writes directly, including Self and proposal evidence. This bypasses the project's identity-change contract. | Static. `scripts/refactor_links.py:42,103-106`. Auxiliary script, not an MCP acceptance bypass. | IDENTITY, DATA |
| P1 | The index treats agent skill documents and ordinary task fixtures as notes. Nested synthetic Self IDs can contaminate personal-memory context on a later refresh. | Static, read-only census confirmed. `knowledgeos/indexer.py:37-51,206-224`. This task moved its own fixture subtrees beneath an excluded .knowledgeos directory; the broader .agents exclusion remains unfixed. | DATA, IDENTITY |
| P1 | A failed summary capture still marks the chat ended, clears unfinished-work signals, and returns protocol success. | Reproduced through real MCP with an obstructed synthetic Inbox. `knowledgeos/memory.py:1040-1068`, `autopilot.py:336-343`. | SESSION, RECOVERY |
| P1 | Host reconfiguration replaces unreadable existing JSON with a fresh document. Unrelated servers/settings can be lost. | Static plus an in-memory mocked-write probe. `knowledgeos/host_setup.py:104-115`. No live config overwritten. | SETUP, DATA |
| P1 | Same-title capture chooses a free filename before a later truncating write. Concurrent callers can select and overwrite the same path. | Static race. `knowledgeos/memory.py:684-688,720-721`, `textio.py:22-27`. Concurrency was not run. | MEMORY, RECOVERY |
| P1 | All chats share unlocked read/modify/write state and global open/ended flags. Separate chats and retries cannot be distinguished. Atomic replacement does not prevent lost updates. | Static. `knowledgeos/autopilot.py:41-62,246-297,336-343`; public session calls at `memory.py:1030-1036` have no session ID. | SESSION |
| P1 | A new Self attributes ranked values, heuristics, models, and anti-goals without collecting them from the owner. Template beliefs can be mistaken for facts about the person. | Static product-integrity gap. `knowledgeos/init_vault.py:155-177`. | IDENTITY, QUALITY |
| P1 | Reader and gate disagree on canonical markers after a section heading is renamed. The gate accepts the marker, while Self context can omit the section. | Static plus an isolated in-memory parser comparison. `knowledgeos/self_model.py:53-78`, `gate.py:379-397`. | IDENTITY, QUALITY |
| P1 | Generated source-install hooks use `-P` even for the documented installed Python 3.9/3.10 path. Those interpreters do not support it. | Static plus version-mocked config generation. `init_vault.py:268-272`, `host_setup.py:33-37`, README lines 42-44. No real 3.9 execution. | SETUP |
| P1 | Report generators write predictable files directly and can follow links or overwrite edited reports. Their safeguards differ from hardened core memory writes. | Static. `knowledgeos/intelligence.py:209,230,330,432-433,439,496-497`; `scripts/experiment_dashboard.py:7,38`; `outcomes_dashboard.py:16,83`. | DATA, IDENTITY |
| P1 | Root-first relative-link resolution and a last-writer-wins basename lookup can associate a note with the wrong project. | Static. `knowledgeos/links.py:28-30,41-52`, used by `memory.py:466-469` and `indexer.py:888-891`. | MEMORY, QUALITY |
| P2 | The same unresolved preference prompt is returned at startup and wrap because wrap ignores persisted prompt history. | Reproduced through real MCP. `knowledgeos/memory.py:1055`; startup history in `autopilot.py:277-281`. | SESSION |
| P2 | Natural task hints become a literal AND of the first 12 words. FTS ranking is later flattened to a constant score and alphabetic tie-breaking. Exact-token checks conceal the relevance gap. | Static design gap. `knowledgeos/search.py:31-43,128-134,193-214`; startup query at `memory.py:967-968`. | QUALITY |
| P2 | Drift counts edited folders or recent notes, then proposes identity drift. It does not establish a semantic belief change or distinguish formatting churn. | Static product gap. `knowledgeos/memory.py:633-668`, `evolution.py:118-144`. | LEARNING |
| P2 | Initialization can record failed rebuild/validation but exit zero. The nested report is more honest than the CLI exit status. | Static plus a mocked initializer boundary probe. `init_vault.py:587-604`, `__main__.py:527-531`. | SETUP, RECOVERY |
| P2 | Doctor can warn about malformed hooks and still report overall success. It does not establish host discovery or usable executable paths. | Static. `knowledgeos/doctor.py:35-42,343-353,380-383`. | SETUP |
| P2 | Lock expiry uses age without a renewing ownership proof. A slow live holder can lose its lock, then remove a replacement owner's lock during cleanup. | Static. `knowledgeos/indexer.py:31-33,785-807`; `gate.py:49,331-347`. | RECOVERY |
| P2 | Validation counts link-shaped strings but does not validate targets; normal status/date/tag contracts are incomplete. A broken link can look like a connected note. | Static. `knowledgeos/validator.py:59,106-107`; status definitions in `schema.py:40`. | DATA, MEMORY |
| P2 | Optional Notion publishing creates new pages on retry, truncates content, and can print total failure while exiting successfully. | Static. `scripts/publish_to_notion.py:143,175-202,313-321`; `notion_bridge.py:85,89`. No network calls. | Optional adapter gate |
| P2 | Git-hook setup overwrites an existing pre-commit hook and ignores custom hook locations. | Static. `scripts/setup_git_hooks.py:23,43`. | DATA |
| P2 | Portability currently covers owned Markdown, while host paths and signing state require separate handling. Working-system portability is narrower than content portability. | Declared limitation. `host_setup.py:71-78`, `init_vault.py:530-533`, README lines 365-368. | PORT |

P0 marks potential destructive behavior that deserves containment before wider use. It is not a claim of an exploited vulnerability or current data loss. These source-only scripts may be excluded or retired from the supported product instead of expanded. Making the installed toolkit larger is not required by this assessment.

## Why the existing green numbers were insufficient

The scenario corpus is valuable regression evidence. It weights identity safety and approval fidelity at 55%, vault/read truth at 30%, autopilot at 10%, and install/ops at 5% in `tests/spec/__init__.py:56-69`. It has no direct measure of answer usefulness, natural-language recall quality, capture judgment, or human effort.

The existing stabilization review explicitly excludes real-host integration, actual owner-terminal approval, broad concurrency/scale, and several platform/runtime checks at `tests/reviews/stabilization-2026-10-18.md:75-85`. Package smoke executes generated hooks and examines their output; it does not prove a host consumed that output or an assistant used the right remembered fact.

The ideal contract therefore adds host and conversation evidence instead of replacing the existing tests. The new failing journeys demonstrate the distinction. The storage loop can pass while interruption recovery and prompt behavior fail.

## What deserves keeping

File-derived reads reduce trust in the disposable index. Frozen-index metadata makes incomplete results visible. Signed proposal state and stale-base checks provide a useful integrity boundary. MCP Self acceptance intentionally refuses. Fresh-vault fixtures, package-artifact checks, and mutation checks are substantial foundations.

The identity boundary remains a trust assumption when an agent has arbitrary owner-level filesystem or terminal authority. README already states this limitation. Preserve the current human approval contract and describe the deployment honestly.

## Next action

Start with data-preservation cases and durable session completion, then exact installed-host proof, then retrieval/answer quality. The [ideal contract](ideal-system.md) gives dependency order and completion criteria. No product repair, commit, deployment, or real preference update was performed in this task.
