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

## What checks it

Preconditions: a synthetic identity. Keep the real owner's Self file untouched. Run one suite with `python -B -m unittest discover -s tests -p <file>`.

- Proposal boundary. `first_day.py` and classes `SelfGateTests`, `GateLeverageTests` and `GateBoundaryTests` in `tests/test_core.py`: a real proposal, an error when a tool tries to accept it, a recorded rejection, and an unchanged Self hash.
- Cold start. `tests/test_setup_repairs.py`: setup with a name alone leaves every preference unknown.
- Section agreement. `tests/test_setup_repairs.py`: renamed section headings with their `kos:section` markers stay visible and writable; duplicate markers are an invalid document.
- Authentic preview. `tests/test_preview_authenticity.py`: an edited body, summary or display field, a stale target and a malformed patch are refused before a diff is shown, and the edited input and the Self bytes are kept. A preview test never establishes owner approval.
- Integrity. `tests/test_journey_gaps.py` (class `GateRefusalTests`), `tests/test_binding_guard.py` and `tests/test_proposal_validation.py`: a row that is not an open draft, a draft this install's ledger does not hold, a hard-linked identity and a malformed binding are refused, with a recovery hint where one exists.
- Other writers. `tests/test_alternative_writers.py`: init, legacy onboarding and the weekly draft refuse a linked identity file and keep an existing one.
- A draft is not a note. `tests/test_draft_is_not_memory.py`. See [the first day](first-day.md).
- Human approval. The owner runs `twinaatma self approve <proposal>` or `twinaatma self review` in their own terminal after reading the diff. The suites patch the console check and type the answer. An agent never supplies the answer and never runs the command. This gate stays NOT CHECKED until the owner's own evidence exists.

Not checked by any script: the refusals above against a hidden real console, where a case that reaches the prompt fails. The driver for each was removed on 13 November 2026; the last commit that holds it is `69bec1e`.

## Gotchas

A simulated TTY in tests proves a function path, not human consent. Terminal presence is a deployment trust assumption. Arbitrary owner-level shell or terminal control can bypass that assumption, as README documents. Do not claim stronger isolation than the deployment enforces. Proposal-only memory operations remain available when the human approval gate is pending.

## Journey fixes (21 October 2026)

- `gate.describe()` refuses every ledger row that is not an open draft (rejected, applied, superseded) before any diff or prompt, even when the file bytes were restored.
- The refusal for a proposal this install's ledger does not hold (also `reject`) now says: propose it again on this device, or restore the signing key backup.
- Approval needs a real console on Windows: `gate.is_real_console` checks `GetConsoleMode`, so stdin on the NUL device is refused with exit 2 like a pipe.
- A draft written before the signed ledger existed takes the same "not registered" refusal and hint; no migration, no new way to approve.
