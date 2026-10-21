# The ideal system and its acceptance contract

The outcome is simple. After one successful setup, an assistant helps the person using accurate, relevant memories, carries useful work across conversations, and learns from outcomes. The person does not manage indexes, schemas, scripts, or cadences. Identity changes remain theirs to approve.

This contract describes observable outcomes rather than a mandated architecture. It follows the current AGENTS.md product promise and identity boundary. The named thresholds below are proposed engineering acceptance targets, not preexisting user-approved service guarantees. Keep them explicit when changing them.

## Judge the complete product

Separate three layers of proof.

1. Storage and tools work. Notes persist, reads reflect source files, refusal boundaries hold, and failures are truthful.
2. The installed integration works. The actual supported host discovers tools, calls them at the right points, and carries state across genuine chats.
3. The help is useful. The assistant recalls relevant evidence, handles changes and uncertainty, captures selectively, and reduces human effort.

A passing lower layer cannot substitute for a higher one. A 100/100 regression corpus means its applicable assertions passed. It cannot certify a useful, private, continuously working assistant.

Use one result row per case with its gate ID, entry point, platform/artifact, preconditions, action, literal expected result, actual result, verdict, and evidence path. For a mandatory gate, missing proof prevents overall acceptance. Preserve separate safety and quality results instead of one weighted product score.

## Mandatory gates

| Gate | Acceptance cases and observable result | Required evidence |
|---|---|---|
| SETUP | A clean install becomes usable through the documented setup. Each advertised runtime generates runnable hooks. Valid foreign host configuration survives a merge; unreadable configuration is preserved with an honest failure. Required post-init failures exit nonzero. | Exact wheel/binary hash and isolated install, CLI transcript, generated-config hashes, actual host tool discovery and first memory call. |
| MEMORY | A useful fact captured in chat A appears in chat B after process/host restart. Direct reads match source bytes. External edits/removals appear without human index commands. Similar names and relative links identify the correct note. | Persisted note and retrieval trace, exact source comparisons, before/after edit evidence, literal graph-neighbor expectations. |
| QUALITY | Normal task phrasing retrieves the right facts despite distractors. Answers distinguish current, historical, inferred, and unknown information. Corrections change later advice without inventing user identity. | A fixed labeled corpus and held-out host conversations, ranked context, source attribution, final answers, explicit correctness review. |
| IDENTITY | Initial unknowns remain unknown. Proposals and rejections preserve Self. Readers and writers agree on section identity. Only independent owner approval applies the exact reviewed change to the expected base. All other write paths preserve identity. | Self hashes, proposal/ledger integrity results, stale-base/tamper cases, independent human terminal evidence, maintenance-script invariance. |
| SESSION | Each distinct chat retains its own lifecycle. Replayed starts/ends do not duplicate episodes. One unfinished chat remains recoverable after another ends. Prompt history follows the same rule at start and wrap. | Two concurrent real processes plus host traces, session/request correlation, episode counts, interruption/restart results. |
| RECOVERY | Failed captures never masquerade as remembered work. Missing/corrupt indexes rebuild; busy/blocked indexes disclose incompleteness. Concurrent writers preserve all captures. Lock recovery respects live ownership. Recovery retries converge without lost or duplicated memory. | Real task-owned filesystem/database failures, before/after source hashes, protocol error flags, retained unfinished work, PID/lock evidence and recovery traces. |
| LEARNING | Decisions can acquire outcomes, outcomes support attributed lessons, and lessons inform later help. Mechanical edits do not become asserted belief changes. Rejected proposals require genuinely new evidence before reconsideration. | Synthetic longitudinal decision/outcome records plus representative host conversations, source-linked proposals, rejection and recurrence checks. |
| PRIVACY | Capture and retention follow an explicit policy. Synthetic secrets and third-party details are handled according to it. Untrusted notes remain evidence rather than instructions. Local verification performs no unauthorized external publishing. | Allowed/forbidden capture ledger, note/context/log/bundle inspection, adversarial note cases, verified dry-run transport behavior where relevant. |
| DATA | Every supported data operation preserves identity, sources, unrelated output, existing hooks, and user edits. Exports refuse overlap. Generated reports use contained, atomic writes and preserve originals on failure. Validation distinguishes valid links/schema from broken data. Tool instructions and synthetic fixtures never become personal memories. | Isolated full-copy script runs, complete before/after inventories, collision/link/hardlink tests where supported, exit codes and diagnostics. |
| PORT | Content survives moving and restoring. Operational wiring and approval-state dependencies are explicit. Missing signing state causes a recoverable refusal rather than silent approval or corruption. Upgrades preserve working data and declared compatibility. | Same-device move and clean-device restore, artifact versions/hashes, host reconnection, note/link comparisons, pending-proposal outcomes. |

The optional Notion adapters need their own release gate when used or advertised as supported. Dry-run sends no requests; retry converges on one remote page; long content is not silently truncated; failures return failure status. No authenticated external test is authorized by this skill alone. For a core local release, record this adapter as outside the release scope and preserve its known risks.

## Proposed quality and effort targets

Build a versioned evaluation set before optimizing search. Include at least 30 labeled cases, with natural task hints, paraphrases, contextual preferences, changed facts, multilingual examples, ambiguous names, irrelevant chatter, and questions with no supporting evidence. Keep a held-out portion. Label expected sources, disallowed claims, and expected capture behavior before observing outputs.

Initial targets for discussion and measurement are:

- Every remembered factual claim in the acceptance conversations has an identifiable supporting source or an explicit uncertainty label. Zero invented personal facts.
- Every critical user fact in the fixed set is available in the startup context. At least 90% of noncritical expected sources appear in the first eight retrieved notes. Report missed cases and both denominators.
- An unsupported personal question leads to an honest unknown in every such case.
- A representative week includes at least 20 useful conversations, reopenings, and two simultaneous chats. It requires zero user index/schema/cadence chores and zero repeated prompts for the same unchanged unresolved item.
- Measure startup, capture, and recall latency at 100, 1,000, and 10,000 synthetic notes on a named machine. Record repeated samples, context bytes, and p50/p95. The owner approved the Balanced budget for the current Windows laptop on 2026-10-19: at every scale, p95 startup <=5 seconds, capture and recall <=2 seconds, memory-process peak RAM <=256 MiB, and context <=16 KiB, excluding model response time. Retain exact device inventory, complete sample distributions and peak-process observations against the current product. Approval and its native user-message provenance are retained in `work/gc-artifacts/.knowledgeos/resource-budget-20261019/approved-budget.json`; agreement alone provides no performance acceptance.

The 20-chat run measures operation while the host is active. Idle-time work is not promised by an installed scheduler today. If offline/idle learning becomes a requirement, define the process owner, trigger, permissions, and independent acceptance case first.

## The product decisions that remain open

These decisions cannot be established by reading the current code.

- What information is worth remembering automatically, and which secrets or sensitive third-party facts must be excluded?
- How are temporary preferences, corrections, superseded facts, and explicit forgetting represented and propagated to derived evidence?
- What counts as enough evidence for an identity suggestion? When may a declined or unanswered suggestion return?
- Which host/runtime/device combinations and source-only scripts are supported for release?
- What recovery and approval behavior is expected when two devices diverge or signing state is missing?
- The intended-device budget is agreed above; fresh measurements and conformance remain required.

Use conservative defaults in isolated evaluation and label them as assumptions. Keep the current independent terminal approval boundary. Do not silently substitute chat consent for it. These open choices do not block the concrete safety, durability, or host-discovery tests already specified.

## Work backwards in dependency order

| Order | Required user outcome | First failing proof to establish | Completion condition |
|---|---|---|---|
| 1 | Trying the product cannot destroy or misattribute personal data. | Export overlap, maintenance writes to Self, report path links, config preservation, cold-start identity. | Every supported writer preserves protected originals or is removed from the supported release with explicit scope. Unknown identity stays unknown. |
| 2 | "I remembered it" means it was durably saved. | Failed summary, concurrent same-title captures, request retry, distinct chat lifecycle, prompt-once. | Recovery, concurrency, idempotency, and prompt journeys pass through public commands/protocols. |
| 3 | One successful setup connects the real assistant. | Exact installed artifact, runtime-generated hooks, real host discovery, normal start/end calls, upgrade preservation. | A supported-host matrix has actual traces, including a clean install and restart. |
| 4 | Advice recalls the right current evidence. | Natural-language retrieval, canonical Self reading, relative links, contradictions, abstention. | The labeled retrieval set and held-out answers meet explicit grounding and relevance targets. |
| 5 | Memory becomes more useful over time. | Outcomes close correctly, lessons cite evidence, formatting churn creates no belief proposal. | Longitudinal journeys pass without invented personal change or repeated chores. |
| 6 | The system remains trustworthy after growth or relocation. | Scale measurements, degraded operation, clean restore, approval-state loss, two-device divergence. | Measured device targets and the chosen portability policy pass on the declared release matrix. |

Each implementation task should name one failed gate, a reproducer, the smallest change, and its proof. Re-run the affected regressions and journey before broadening scope. Keep architectural choices subordinate to these outcomes. This document does not authorize a rewrite, deployment, commit, or change to the owner's identity.

## Starting evidence and coverage

The [creation assessment](current-assessment.md) records actual source checks and their limitations. The feature map routes each gate to its entry points. The bundled helper implements a narrow source subset. Host acceptance, real human approval, longitudinal usefulness, privacy policy, clean-device restore, and scale remain separate work.

## Remembering policy approved 19 October 2026

The owner explicitly approved automatic remembering of useful project facts and preferences; exclusion of credentials and sensitive third-party details from notes, summaries, context, logs and exports; historical attribution for superseded facts; retention until an explicit forgetting request; and exclusion from future recall and exports after forgetting while preserving source notes unless deletion is requested. Identity application still requires independent owner-terminal approval. Authorization is retained in `work/gc-artifacts/.knowledgeos/privacy-policy-20261019/approved-policy.json`. This decision does not establish implementation acceptance or change any of the fixed 54 criteria.

## Device divergence policy approved 21 October 2026

The owner chose device-local identity. The sync tool owns note conflicts, and TwinAatma never merges note text. Conflict copies stay as separate sources that doctor flags. An identity proposal can be approved only on the device that made it; on another device it is refused with a hint to propose again there. A ledger from another device fails closed, and doctor explains why. Identity application still requires independent owner-terminal approval. The owner first selected "shared signing state" by mistake and corrected it in the same session; the receipt `work/gc-artifacts/.knowledgeos/divergence-policy-20261021/approved-policy.json` retains both. This decision does not establish implementation acceptance or change any of the fixed 54 criteria.

## Pre-ledger drafts after upgrade, approved 21 October 2026

The owner chose refusal with a hint. An identity proposal written before the signed proposal ledger existed (revision e831fdc and earlier) stays unapprovable after an upgrade: no unsigned file may reach the approval prompt. The draft file is kept unchanged, Self is unchanged, and the refusal tells the person to propose the change again on this device. The upgrade journey's case `upgrade.pre_ledger_draft_refused_with_hint` checks exactly this. The receipt `work/gc-artifacts/.knowledgeos/old-draft-policy-20261021/approved-policy.json` retains the question and the answer. This decision does not establish implementation acceptance or change any of the fixed 54 criteria.
