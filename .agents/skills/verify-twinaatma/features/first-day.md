# The first day

A new person installs once, connects the hosts they chat in, brings in what another assistant already knows, and has a useful first chat. Nothing reaches their profile without their own decision in a terminal.

## Sub-features

- DAY.1. The first chat of an empty profile asks one plain question, once, and carries the steps the agent follows.
- DAY.2. `twinaatma import` turns an assistant export or agent files into ordinary notes, withholds what the remembering policy refuses, and is safe to repeat. A source file whose own frontmatter marks it private or not to be remembered is withheld whole. A source inside the vault, or a folder that holds the vault, is refused. One run writes at most 500 new notes and drafts at most 12 rules; it reports what is left, and the same command continues. Each note from a folder names its file.
- DAY.3. Rule-like lines become one profile draft. `twinaatma self review` decides every waiting draft in one sitting, in a real terminal only.
- DAY.4. `memory_search` keeps `ranked` for notes that hold every word. Notes that hold some words go in `possibly_related`, with a note that says so.
- DAY.5. Starter pages, templates and undecided drafts are not offered as memory. A search that names one on purpose still finds it.
- DAY.6. `setup-host --global` registers the vault for every project through the host's own command (Claude Code, Codex). `--host claude-code --write` writes the project `.mcp.json`.
- DAY.7. For Claude Code, `--global` also merges two hook entries into the person's `settings.json` (`--no-hooks` skips them). `twinaatma hook claude-code --vault <vault>` reads the event on stdin. On `SessionStart` it prints how to use the memory server and the approved profile. On `UserPromptSubmit` it prints the saved notes that match the prompt. It only reads, it uses the startup-context route, and it ends with exit code 0 and no output on every error.

## How to get to it (user POV)

`pip install`, `twinaatma init brain`, `cd brain`, `twinaatma setup-host --host claude-code --global`, `twinaatma import <file>`, `twinaatma self review`, then chat.

## Driving it with CLI and host traces

Preconditions: a new task-owned output directory. The driver sets its own `KNOWLEDGEOS_STATE_DIR`.

- Source journey. Run `python -B .agents/skills/verify-twinaatma/scripts/first_day.py --output <new-dir>`. It drives the real command line and the real MCP stdio server on a synthetic vault: init, first chat, capture, dry run, import, repeated import, review refusal, second chat, three searches, agent approval refusal, the Claude Code hook for both events, both user-level command lines, the Claude Code project file and doctor. It compares `People/Self.md` with its state right after init after every stage. It prints one PASS or FAIL line per check and writes `report.json`. It makes no model call, so it earns no host acceptance credit.
- Unit suites. `python -B -m unittest discover -s tests -p "test_first_contact.py"`, and the same for `test_import_memory.py`, `test_import_command.py` and `test_user_level_setup.py`.
- Owner review. `self review` needs a real console. A person runs it; the suites patch the console check and type `y`, `d` and `n`. Never answer a real approval prompt from an agent.
- Claude Code hook. `python -B -m unittest discover -s tests -p "test_claude_hook.py"` covers the hook text, the settings merge and the command. The suite moves the settings folder with `CLAUDE_CONFIG_DIR`. To see the hook in a real chat without a change to anyone's settings, write the output of `setup-host --host claude-code --global --print` (the JSON part) to a new file and start `claude --settings <that file>`. A hook entry needs the installed `twinaatma` command, so a source checkout prints the reason and sets none.
- User-level setup. The suites replace the host command with a recorder. To prove a real registration, a person runs `twinaatma setup-host --host claude-code --global` and then `claude mcp get knowledgeos`. An agent must not change the owner's host configuration without being asked, and that includes `~/.claude/settings.json`.
- Genuine host chat. Start a new session in the connected host with a fresh vault. Require the first-run question once, a capture, and after an import a grounded answer that quotes an imported note. Retain the tool trace.

## Gotchas

`ranked` staying empty for a plain question is intended; read `possibly_related`. Recall is lexical with concept clusters: a question that shares no word and no cluster with the note finds nothing ("which database" does not find a note that only says "Postgres"). The policy withholds what it recognises as a credential; it does not judge every sensitive sentence. On Windows `--global` starts the host only when its command is an `.exe`; for a script wrapper it prints the line to run. The host refuses a second registration under the same name; the message names the remove command. The hooks are still set in that case. The prompt hook starts a new process for each prompt and checks the index, so it adds about two seconds on a small vault; the entry carries a 20 second limit, and the host drops the output of a hook that reaches it. Claude Code reads its settings as strict JSON here: a settings file with comments, or a linked one, is left unchanged and the entries are printed for a paste.
