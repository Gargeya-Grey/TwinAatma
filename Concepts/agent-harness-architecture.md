---
type: concept
title: Agent Harness Architecture
description: Concept note for Agent Harness Architecture.
schema: knowledgeos-v0.2
status: active
created: 2026-06-14
updated: 2026-06-14
tags: [agent-architecture, harness, systems-design, AI-infrastructure, concept]
project: AI-Systems
timestamp: 2026-06-18T00:00:00Z
---

# Agent Harness Architecture

## Definition

An **agent harness** is the operational infrastructure surrounding the AI model loop — everything that is NOT the model itself. It includes permission gates, tool execution, context management, session persistence, recovery logic, and extension mechanisms.

The model reasons. The harness does everything else.

## Core Principles

1. **The model is a commodity.** Frontier models converge on raw ability. The harness is the differentiator.
2. **Maximum model latitude, maximum harness rigor.** Give the model freedom to decide within a tightly engineered deterministic system.
3. **Layered defense over binary gates.** Instead of asking the model "can I do this?", design automated systems that compensate for the model's limitations.
4. **Context cost is a first-class design constraint.** Every extension mechanism, every storage decision, every delegation pattern must be evaluated by its token cost.
5. **Friction is a feature.** Session-scoped permissions that expire are intentional. They force re-authorization and reduce blast radius.
6. **Subagents are opaque.** Delegated work returns summaries, not full transcripts. Sidechain storage keeps context lean.

## The 7 Systems of a Harness

1. **Core Loop** — Simple while-true: call model, run tools, repeat.
2. **Permission System** — Multi-mode gates with automated ML classification.
3. **Context Management** — Multi-layer compaction pipeline triggered by budget thresholds.
4. **Tool Execution** — Deterministic tool harness with error recovery.
5. **Extension Mechanisms** — Ordered by context cost (hooks → skills → plugins → MCP).
6. **Subagent Delegation** — Isolated execution with summary-only returns.
7. **Session Persistence** — Append-oriented storage; data survives, permissions don't.

## Comparison of Agent Design Approaches

| Dimension | Claude Code | LangGraph | Devin |
|-----------|------------|-----------|-------|
| Architecture | Model in rich harness | Explicit state machine | Heavy planner + scaffolding |
| Model Latitude | Maximum | Constrained by graph | Constrained by planner |
| Engineering Focus | Harness quality | Routing logic | Planning framework |

## Related Concepts
- [[Claude Code Architecture Deep Dive]] — the research this concept is derived from
- Permission Systems
- Context Compaction
- Tool-Use Architecture

## Key Sources
- arXiv:2604.14228 — "Dive into Claude Code" (UCL, Apr 2026)
- Claude Code (Anthropic) — reverse-engineered source code analysis

## Notes
- This concept challenges the prevailing focus on "which model" and redirects attention to "what systems surround the model."
- For educational and workspace agents, this means: invest in the application harness, not just the base model.
- The 5-layer compaction pipeline is directly applicable to long conversational sessions.
- The permission system with graduated modes maps well to user roles.