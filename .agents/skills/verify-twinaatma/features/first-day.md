# The first day

A new person installs once, connects the hosts they chat in, brings in what another assistant already knows, and has a useful first chat. Nothing reaches their profile without their own decision in a terminal.

## Sub-features

- DAY.1. The first chat of an empty profile asks one plain question, once, and carries the steps the agent follows.
- DAY.2. `twinaatma import` turns an assistant export or agent files into ordinary notes, withholds what the remembering policy refuses, and is safe to repeat.
- DAY.3. Rule-like lines become one profile draft. `twinaatma self review` decides every waiting draft in one sitting, in a real terminal only.
- DAY.4. `memory_search` keeps `ranked` for notes that hold every word. Notes that hold some words go in `possibly_related`, with a note that says so.
- DAY.5. Starter pages, templates and undecided drafts are not offered as memory. A search that names one on purpose still finds it.
- DAY.6. `setup-host --global` registers the vault for every project through the host's own command (Claude Code, Codex). `--host claude-code --write` writes the project `.mcp.json`.

## How to get to it (user POV)

`pip install`, `twinaatma init brain`, `cd brain`, `twinaatma setup-host --host claude-code --global`, `twinaatma import <file>`, `twinaatma self review`, then chat.

## Driving it with CLI and host traces

Preconditions: a new task-owned output directory. The driver sets its own `KNOWLEDGEOS_STATE_DIR`.

- Source journey. Run `python -B .agents/skills/verify-twinaatma/scripts/first_day.py --output <new-dir>`. It drives the real command line and the real MCP stdio server on a synthetic vault: init, first chat, capture, dry run, import, repeated import, review refusal, second chat, three searches, agent approval refusal, both user-level command lines, the Claude Code project file and doctor. It prints one PASS or FAIL line per check and writes `report.json`. It makes no model call, so it earns no host acceptance credit.
- Unit suites. `python -B -m unittest discover -s tests -p "test_first_contact.py"`, and the same for `test_import_memory.py`, `test_import_command.py` and `test_user_level_setup.py`.
- Owner review. `self review` needs a real console. A person runs it; the suites patch the console check and type `y`, `d` and `n`. Never answer a real approval prompt from an agent.
- User-level setup. The suites replace the host command with a recorder. To prove a real registration, a person runs `twinaatma setup-host --host claude-code --global` and then `claude mcp get knowledgeos`. An agent must not change the owner's host configuration without being asked.
- Genuine host chat. Start a new session in the connected host with a fresh vault. Require the first-run question once, a capture, and after an import a grounded answer that quotes an imported note. Retain the tool trace.

## Gotchas

`ranked` staying empty for a plain question is intended; read `possibly_related`. Recall is lexical with concept clusters: a question that shares no word and no cluster with the note finds nothing ("which database" does not find a note that only says "Postgres"). The policy withholds what it recognises as a credential; it does not judge every sensitive sentence. On Windows `--global` starts the host only when its command is an `.exe`; for a script wrapper it prints the line to run. The host refuses a second registration under the same name; the message names the remove command.
