---
type: research
title: Claude Code Architecture: The Agent Harness Deep Dive
description: Research note for Claude Code Architecture: The Agent Harness Deep Dive.
schema: knowledgeos-v0.2
status: active
created: 2026-06-14
updated: 2026-06-14
tags: [agent-architecture, claude-code, harness, AI-systems, context-management, permissions]
project: knowledgeos
timestamp: 2026-06-18T00:00:00Z
---

# Claude Code Architecture: The Agent Harness Deep Dive

## Question

What makes Claude Code's agent architecture effective, and what design lessons can we extract for building AI-native products?

## Hypothesis

The quality of an AI agent is determined not by the model it uses, but by the **operational infrastructure (harness)** surrounding the model loop. Most engineering effort should go into the harness, not the model logic.

## Findings

### Key Statistic
- **1.6%** of Claude Code's codebase = AI decision logic
- **98.4%** = operational infrastructure (permissions, tools, recovery, persistence, context management)

### The Core Loop
- Simple `while-true`: call model → run tools → repeat.
- The model gets maximum decision latitude inside a rich deterministic harness.
- All engineering effort goes into the harness, not the model loop itself.

### The 7 Architectural Systems

**1. Permission System (7 modes + ML classifier)**
- 7 permission modes layered from permissive to restrictive.
- ML-based classifier predicts permission intent.
- Users approve 93% of prompts anyway, so architecture compensates with *automated* layers instead of more warnings.
- Resume does NOT restore session-scoped permissions. Trust is re-established every session. That friction is intentional — it forces re-authorization.

**2. 5-Layer Context Compaction Pipeline**
Each layer runs only when cheaper ones fail:
1. Budget reduction — trim within token budget
2. Snip — remove low-value content
3. Microcompact — aggressive targeted removal
4. Context collapse — structural compression
5. Auto-compact — last resort full compaction

**3. Four Extension Mechanisms (ordered by context cost)**
| Mechanism | Context Cost | Use Case |
|-----------|-------------|----------|
| Hooks | Zero | Simple callbacks |
| Skills | Low | Reusable instructions |
| Plugins | Medium | Integrated capabilities |
| MCP | High | External tool integration |

Each answers a different integration problem. The ordering is deliberate — pay only what you need.

**4. Subagent Delegation System**
- Subagents return only **summary text** to parent.
- Full transcripts live in **sidechain files** (not in parent context).
- Agent teams still cost ~7x tokens of a standard session.
- Worktree isolation — subagents operate in isolated environments.

**5. Tool Execution System**
- Rich deterministic tool harness with error recovery.
- Permission gates at every tool call boundary.
- Tool execution recovery logic (retry, fallback, abort).

**6. Session Persistence**
- Append-oriented session storage.
- Resume restores session data but NOT permissions.

**7. Comparison with OpenClaw**
- OpenClaw (multi-channel gateway) answers same design questions differently:
  - Per-action safety classification → perimeter-level access control
  - Single CLI loop → embedded runtime in gateway control plane
  - Context-window extensions → gateway-wide capability registration

### The Bet
> As frontier models converge on raw coding ability, **the quality of the harness becomes the differentiator, not the model.**

### Five Human Values Driving Architecture
1. Human decision authority
2. Safety and security
3. Reliable execution
4. Capability amplification
5. Contextual adaptability

## Sources
- **Paper:** "Dive into Claude Code: The Design Space of Today's and Future AI Agent Systems" — arXiv:2604.14228 (UCL, Apr 2026)
- **PDF:** [[../Assets/papers/claude-code-design-space-arxiv-2604.14228.pdf|Full Paper PDF]]
- **Tweet:** [@DailyDoseOfDS_](https://x.com/DailyDoseOfDS_/status/2065728394084626773) (Jun 13, 2026)
- **Article:** "The Anatomy of an Agent Harness" by Akshay (@akshay_pachaar)

## Open Questions
- How does the ML classifier for permissions work? Is it trainable per-instance?
- What triggers each level in the context compaction pipeline? Are thresholds dynamic?
- How do hooks achieve zero context cost vs skills at low cost?
- Can we design a simpler 3-layer permission model for education contexts?
- What does subagent delegation look like for tutoring vs coding?

## Related Concepts
- [[Agent Harness Architecture]]