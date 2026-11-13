# Verification feature map

Read the relevant feature before driving the system. Each feature file names the checks that exist and the journeys that no check drives.

| Feature | Gates | Checks that exist | Not checked by any script |
|---|---|---|---|
| [The first day](first-day.md) | SETUP, MEMORY, IDENTITY | `first_day.py` through the real command line and MCP server; first-contact, import, review-command, hook and user-level setup suites | A real host chat in Claude Code and Codex; a real owner review; a real user-level registration |
| [Setup and portability](setup-portability.md) | SETUP, PORT | init, doctor and host configuration suites; same-device move and reconnect suites; `package_smoke.py` on wheels and binaries in CI | A host chat from an installed package, desktop and other hosts, speed at 10,000 notes, upgrade from an older release, restore on a second device |
| [Capture and grounded recall](memory-recall.md) | MEMORY, QUALITY | capture, freshness, startup context, graph and concept suites; the 108-case recall evaluation `quality.py` | Answer quality in a host chat, corrections in conversation, selective capture by meaning |
| [Identity and consent](identity-consent.md) | IDENTITY | proposal, refusal, rejection, preview and alternative-writer suites; `first_day.py` compares the profile after every stage | An owner's approval in their own terminal |
| [Sessions and recovery](sessions-recovery.md) | SESSION, RECOVERY | session, summary, startup budget, capture transaction, lock, index and database suites | Session IDs in real hosts, wider crash recovery |
| [Learning and open loops](learning-outcomes.md) | LEARNING | outcome recording, follow-up, evidence and project precision suites | The outcome loop in a host chat, a week of real use |
| [Privacy and data operations](privacy-data.md) | PRIVACY, DATA | remembering-policy, privacy reader, export, maintenance, census and generated-writer suites | Privacy by meaning, data operations from an installed package, real publishing |

## Preconditions

Place generated fixture folders below a `.knowledgeos` component that the note census excludes. Use a unique synthetic vault and an isolated `KNOWLEDGEOS_STATE_DIR`. Preserve uncommitted work. A source-only script under `scripts/` often binds its vault to the checkout and not to `--vault`; run it only in a complete task-owned copy after you read how it finds its vault.

## Evidence rules

An entry point that was not run stays NOT CHECKED, also when another entry point passed. A missing capability is FAIL when it is tested against its stated outcome. An unavailable outside prerequisite is BLOCKED or NOT CHECKED, with the reason.

The drivers for the journeys in the last column were removed on 13 November 2026. The last commit that holds them is `69bec1e`.
