# Keep identity grounded and owner approved

The assistant can suggest identity changes. Only the owner applies a reviewed change through the independent approval path.

## Sub-features

- IDENTITY.1. Unknown preferences remain unknown after cold start.
- IDENTITY.2. Proposing, refusing, and rejecting preserve Self bytes.
- IDENTITY.3. Reader and writer agree on canonical sections, including renamed headings.
- IDENTITY.4. Applied bytes match the owner's reviewed diff and base.
- IDENTITY.5. Tampering, stale bases, and invalid approval state fail closed.

## How to get to it (user POV)

Ask what the assistant knows about you. Express a stable preference. Review a proposed change in your own terminal, or decline it. The memory tool that accepts Self updates intentionally refuses.

## Driving it with MCP and owner evidence

Preconditions: use the helper's synthetic identity. Keep the real owner's Self file untouched.

- Proposal boundary. Run the core driver. Require an actual proposal, an MCP error on tool acceptance, recorded rejection, and unchanged Self hash.
- Cold start. Initialize with a name alone and ask about the person's ranked values. Require unknown or clearly marked examples, not attributed template values.
- Section agreement. In a synthetic fixture, rename visible section headings while retaining canonical `kos:section` markers. Call `memory_self_get` and `memory_session_start`. Require every known section to remain visible and proposals to target the same section. Test duplicate markers as an invalid document.
- Authentic preview. In a synthetic fixture, create a proposal through the public proposer, edit its body or displayed summary, and call the read-only preview. Require refusal before a diff is shown and exact preservation of the edited input and Self bytes. Restore the original proposal and require a valid preview. A stale target section, unsafe identity file or malformed patch also refuses. Preview tests never establish owner approval.
- Integrity. Use existing identity corpus scenarios and additional fixture cases for edited proposals, stale Self bases, invalid signatures, replay, links, and loss of off-vault state. Verify refusal against before/after hashes, not error text alone.
- Human approval. The owner independently runs `twinaatma self approve <proposal>` in their own terminal after reading the diff. Use decline and approval cases on synthetic identity. Capture the actual displayed diff, owner decision, receipt, and resulting bytes. An agent never supplies the answer or runs this approval command. Leave this gate NOT CHECKED until independent owner evidence exists.

Use [the source identity recipe](../references/source-identity-quality.md) for the
repeatable unknown and canonical journeys. Literal section bodies, persisted
proposal content and duplicate-marker refusals remain separate from human approval.

## Gotchas

A simulated TTY in tests proves a function path, not human consent. Terminal presence is a deployment trust assumption. Arbitrary owner-level shell or terminal control can bypass that assumption, as README documents. Do not claim stronger isolation than the deployment enforces. Proposal-only memory operations remain available when the human approval gate is pending.

Use [complete alternative-writer preservation](../references/source-identity-writers.md) for native Windows/Linux aliases, actual public writers and all reused source families. Include both focused reports in the cumulative score. This source outcome leaves independent approval pending.
