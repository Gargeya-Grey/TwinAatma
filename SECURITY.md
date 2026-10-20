# Security Policy

## Local-first privacy

KnowledgeOS is designed so your vault — especially `People/Self.md` — can stay on your machine. The MCP Memory server and CLI keep note operations within the configured vault root. Signed proposal state and keys are stored in the configured local state directory outside the vault. Host setup may update explicitly selected host configuration files.

Treat the following as **highly sensitive**:

- `People/Self.md` (values, heuristics, anti-goals, active bets)
- `People/Self-Proposals/`
- Decision lessons and private research notes
- Any `knowledgeos.config.json` containing Notion keys

## Reporting issues

If you discover a path-traversal, accidental secret commit, or unsafe auto-write path, open a private report or GitHub security advisory if enabled. Do not file public issues that include personal vault contents.

## Safe defaults

- Inbox capture may auto-write.
- Self updates are proposal-only until the owner runs `twinaatma self approve <file>` in an interactive terminal. MCP acceptance always refuses.
- Notion publishing never runs through MCP.
- Do not commit `.env` files or API keys.

## Scope

This project does not currently offer multi-tenant cloud sync. If you expose the MCP server beyond localhost, you are responsible for authentication and network controls.

## Trust boundary

The approval gate protects the supported tool path. It does not confine an agent
that can edit trusted installed code, the owner's identity file, or signing state
with owner-level filesystem access. Use host permissions to restrict those paths
when that is required. Local stdio MCP is not a remote authenticated service.

Generated reports replace only their own unchanged output. Exports refuse existing
output directories and linked paths. These protections do not define a complete
secret exclusion or retention policy; review selected content before external export.
