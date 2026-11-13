# Threat model and release bar

13 November 2026. This page says what TwinAatma defends against, what it does not,
and which findings stop a release. A review of the code is read against this page.

## Why this page exists

Three reviews in one day returned 7, 15 and 11 findings. A fourth, a fifth and a sixth,
read against this page, returned 6, 7 and 8 inside the bar. Many were real. Many others
asked the product to resist an attacker that it cannot resist by design. With no
stated limit, every review finds a new edge and every repair makes each request
slower. October went the same way with a proof count. A review without a stated
threat has no end.

## Who the product protects, and from whom

| Protected | From | How |
|---|---|---|
| The profile (`People/Self.md`) | An assistant that calls the memory tools or writes files in the vault | Assistants only draft. Approval needs a real terminal. The approval record is signed and lives outside the vault. |
| Notes marked private, credentials, forgotten text | Any assistant that reads memory | Every row is read from the note at the moment it is returned. The privacy rule refuses a value it does not know, and a metadata block it does not fully read. A text that comes into a tool is refused when it holds a marked metadata block, at its start or between two `---` lines further down. |
| The assistant's behaviour | Text planted in a note or an import | Notes and imports are evidence, never instructions. An imported rule is only a draft. |
| The search index | An agent that writes into the vault | The index is a cache. Each returned row is derived again from the file. |
| The person's notes | The toolkit itself | Setup never overwrites a file. The hooks change no note. |

The attacker in every row is **an assistant, or text that reaches an assistant**. It
can call the memory tools and it can write files inside the vault.

## What the host must do

The gate holds where the assistant cannot act as the person outside the vault. An
assistant with an unrestricted shell is a program that runs as the person: it can read
the signing key and write the approval record. The approval command refuses to run
without a terminal, which stops an assistant that follows its tools. It does not stop
a program that reads the key. So the host's own permission prompts are part of the
defence. A person who lets an assistant run any command without asking has given it
the door.

The approval record and the key live in the state folder, outside the vault. A backup
or a move must take that folder whole. Without it the toolkit trusts no earlier draft:
it reports each draft it cannot check, and a rule the person rejected can be drafted
again. Nothing reaches the profile without a new decision in a terminal.

## What the product does not defend against

- **A program that runs as the person outside the vault.** It can read every note,
  the signing key and the approval record. No local-first tool can stop it.
- **A second program that changes files during one command.** Import and the settings
  merge check the file they act on and act on that same file. A change made by another
  program in the instant between two steps is outside this model.
- **A person who edits their own files.** The person may edit a note, a draft or the
  profile by hand. The toolkit reports what it can no longer verify. It does not treat
  the person as an attacker.
- **Every sensitive sentence.** The policy withholds what is marked and what it
  recognises as a credential. It does not judge meaning. A private note that an
  assistant already holds and types again in another shape (a summary, a quotation, a
  table) is not recognised when it comes back in.
- **Every YAML parser.** The privacy reader is checked against one full YAML parser
  (PyYAML) on blocks changed at random. A block that this parser refuses cannot be
  judged by the check. The reader's own rule still applies to it: a block that it does
  not fully read keeps the note private. Metadata is the block that opens with `---` on
  the first line that holds anything, which is where note tools look for it. A text
  that opens another way has no metadata, also where a YAML parser would read its first
  lines as a document.

## Release bar

A finding stops a release when a person who uses the product as documented would meet
one of these:

1. The profile changes without the person's decision in a terminal.
2. An assistant is given a note that is marked private, a recognised credential, or
   forgotten text.
3. A note or the profile is lost or silently changed.
4. The first-day journey fails: install, connect, save a fact, get it back.
5. A document states a behaviour that the code does not have.

A finding outside this bar is recorded in the feature notes with its reason. It is
repaired when a user meets it, or when the repair is small and removes the cause.

A repair removes the cause for the whole kind of fault and adds the check that should
have found it. When the same kind of fault returns, the design is wrong: change the
rule so that the unknown case is refused, and do not add one more case to a list.
