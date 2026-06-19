---
type: decision
title: Refinement Bar for Notion Publishing
description: Decision log for Refinement Bar for Notion Publishing.
schema: knowledgeos-v0.2
status: active
created: 2026-06-18
updated: 2026-06-18
tags: [knowledgeos, notion, refinement-bar, publishing]
project: KnowledgeOS
timestamp: 2026-06-18T00:00:00Z
---
# Refinement Bar for Notion Publishing

## Context
KnowledgeOS separates Obsidian as the thinking layer and Notion as the execution/publishing layer. The system needs a clear standard for when notes are allowed to leave the thinking layer.

## Alternatives Considered
1. Publish any note with useful content.
2. Publish only polished public-facing notes.
3. Publish operationally useful notes once they meet a minimum refinement bar.

## Decision
Use option 3: a note can be published when it is operationally useful, linked, and stable enough to support execution.

## Refinement Bar
A note can become `status: refined` when it has:
- a clear purpose or question
- substantive content beyond placeholders
- at least one link to a project, MOC, concept, decision, or source
- explicit implications, next actions, or decisions when applicable
- stable enough wording to be useful outside the immediate moment

Only then should it set:

```yaml
publish_to_notion: true
```

## Reasoning
This keeps Obsidian safe for rough thinking while preventing Notion from filling with half-formed notes. It also gives Hermes a clear rule when deciding whether to publish.

## Expected Outcome
The Notion execution layer stays cleaner and higher-signal while KnowledgeOS remains useful for raw capture and synthesis.

## Actual Outcome
_To revisit after several publish cycles._

## Related Notes
- [[../README|KnowledgeOS README]]
- [[connect-notion-execution-layer|Connect Notion as Execution Layer]]
- [[../Projects/knowledgeos|KnowledgeOS Project]]
