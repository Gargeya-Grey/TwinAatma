# Security Policy

## Local-first privacy

KnowledgeOS is designed so your vault — especially `People/Self.md` — can stay on your machine. The MCP Memory server and CLI read/write only within the configured vault root.

Treat the following as **highly sensitive**:

- `People/Self.md` (values, heuristics, anti-goals, active bets)
- `People/Self-Proposals/`
- Decision lessons and private research notes
- Any `knowledgeos.config.json` containing Notion keys

## Reporting issues

If you discover a path-traversal, accidental secret commit, or unsafe auto-write path, open a private report or GitHub security advisory if enabled. Do not file public issues that include personal vault contents.

## Safe defaults

- Inbox capture may auto-write.
- Self updates are proposal-only until `accept`.
- Notion publishing never runs through MCP.
- Do not commit `.env` files or API keys.

## Scope

This project does not currently offer multi-tenant cloud sync. If you expose the MCP server beyond localhost, you are responsible for authentication and network controls.
