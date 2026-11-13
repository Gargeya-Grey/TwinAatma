# Try TwinAatma in ten minutes

This page is for a person who uses the toolkit for the first time and tells us what
happened. It takes about ten minutes. You need a terminal, Python 3.9 or newer, and
Claude Code. The same steps work with Codex: write `codex` where a step says
`claude-code`.

Do each step as written. If a step fails, stop there and send the report at the end.
A failed step is the most useful result you can give us.

## The steps

**1. Install.**

```bash
pip install git+https://github.com/Gargeya-Grey/TwinAatma
twinaatma --version
```

Expected: a version number.

**2. Make your vault.** A vault is a folder of plain text notes that you own.

```bash
twinaatma init brain --name "Your Name"
cd brain
```

Expected: a new folder `brain` with `People/Self.md` in it.

**3. Connect your assistant.**

```bash
twinaatma setup-host --host claude-code --global
```

Expected: a line that starts with "Registered vault". For Claude Code this step also
adds two entries under `hooks` in `~/.claude/settings.json`. Add `--print` to see what
the step would do without doing it.

**4. First chat.** Start Claude Code in any other folder. Say this, with your own facts:

> Remember that my staging database is on the Frankfurt cluster. Also, I always want
> answers in short sentences.

Expected: the assistant says that it saved the fact. It also says that a change to
your profile waits, and names one command.

**5. Decide the profile change.** In a terminal:

```bash
twinaatma self review
```

Expected: you see the rule the assistant drafted. `y` applies it, `d` discards it.
Nothing changes your profile without this step.

**6. Second chat.** Close the first chat. Start a new one in another folder. Ask:

> Where is my staging database?

Expected: the answer, and you did not say it again.

**7. Check.**

```bash
twinaatma doctor
```

Expected: no line that starts with a failure mark.

## To undo

```bash
claude mcp remove knowledgeos --scope user    # for Codex: codex mcp remove knowledgeos
pip uninstall twinaatma
```

Then delete the two entries that run `hook claude-code` from `~/.claude/settings.json`,
and delete the `brain` folder.

## What to send

Open an issue at <https://github.com/Gargeya-Grey/TwinAatma/issues> with the title
"First day report". Do not paste a note that you want to keep private.

1. Your system (Windows, macOS or Linux) and the output of `python --version`.
2. The assistant and its version.
3. The number of the last step that worked.
4. For a failed step: the command and the exact message.
5. The minutes it took.
6. One sentence: would you use it next week? Why, or why not?
