"""Create a clean starter KnowledgeOS vault from the toolkit templates.

Safety contract (see Decisions/self-gate-and-index-integrity.md):

* ``init`` never overwrites a file that already exists in the target.
* ``--force`` on a non-empty directory means "fill in what is missing", not
  "reset what is there". Anything that would conflict is written beside the
  original as ``<name>.new`` and reported under ``conflicts``.
* ``--dry-run`` reports the plan and changes nothing.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import uuid
from pathlib import Path

from knowledgeos.data_ops import plain_vault_path
from knowledgeos.textio import atomic_create_bytes, atomic_write_bytes

STARTER_DIRS = [
    "Inbox",
    "Concepts",
    "Projects",
    "Experiments",
    "Research",
    "Research/Synthesis",
    "Decisions",
    "People",
    "People/Self-Proposals",
    "MOCs",
    "Templates",
    "Assets",
    "Archive",
]


class _Plan:
    """Collects intended writes so a dry run can print them and a real run can apply them."""

    def __init__(self, target: Path, dry_run: bool, source: Path) -> None:
        self.target = target
        self.source = source
        self.dry_run = dry_run
        self.created: list[str] = []
        self.conflicts: list[str] = []

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.target).as_posix()

    def write(self, path: Path, content: str, *, replace_state: bool = False) -> None:
        self._write(path, content, replace_state=replace_state)

    def _write(self, path: Path, content: str | bytes, *, replace_state: bool = False) -> None:
        payload = content.encode("utf-8") if isinstance(content, str) else content
        path = plain_vault_path(self.target, path)
        rel = self._rel(path)
        if path.exists():
            existing = path.read_bytes()
            if existing == payload or (
                isinstance(content, str)
                and existing.replace(b"\r\n", b"\n").replace(b"\r", b"\n") == payload
            ):
                return
            if replace_state:
                if self.dry_run:
                    return
                plain_vault_path(self.target, path)
                atomic_write_bytes(path, payload)
                self.created.append(rel)
                return
            self.conflicts.append(rel)
            beside = plain_vault_path(
                self.target, path.with_name(path.stem + ".new" + path.suffix)
            )
            if beside.exists():
                if beside.read_bytes() == payload:
                    return
                raise FileExistsError(f"Refusing to replace existing conflict file: {beside}")
            if self.dry_run:
                return
            atomic_create_bytes(beside, payload)
            return
        self.created.append(rel)
        if self.dry_run:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        plain_vault_path(self.target, path)
        atomic_create_bytes(path, payload)

    def copy(self, src: Path, dst: Path) -> None:
        src = plain_vault_path(self.source, src)
        self._write(dst, src.read_bytes())


def _index_note(title: str, folder_desc: str, today: str) -> str:
    return f"""---
type: index
title: {title}
description: {folder_desc}
schema: knowledgeos-v0.2
status: active
created: {today}
updated: {today}
timestamp: {today}T00:00:00Z
tags: [index]
---

# {title}

{folder_desc}

## Notes
- _(empty — capture into Inbox, then promote here)_
"""


def _moc(title: str, desc: str, today: str, body: str) -> str:
    return f"""---
type: moc
title: {title}
description: {desc}
schema: knowledgeos-v0.2
status: active
created: {today}
updated: {today}
timestamp: {today}T00:00:00Z
tags: [moc]
---

# {title}

{body}
"""


def _self_note(owner_name: str, today: str) -> str:
    title = f"Self ({owner_name})" if owner_name and owner_name != "Self" else "Self"
    return f"""---
type: person
title: {title}
description: Ego node for {owner_name} — heuristics, values, anti-goals, active bets, drift.
id: kos:person:self
schema: knowledgeos-v0.3
status: active
created: {today}
updated: {today}
timestamp: {today}T00:00:00Z
tags: [ego-node, core]
last_reviewed: {today}
---

# {title}

Identity layer for this vault. Agents load this before advising; propose edits only.

## Operating Heuristics & Rules of Thumb
<!-- kos:section=heuristics -->
Unknown. No owner-confirmed heuristics recorded yet.

## Values Hierarchy
<!-- kos:section=values -->
Unknown. No owner-confirmed values or ranking recorded yet.

## Mental Models
<!-- kos:section=mental_models -->
Unknown. No owner-confirmed mental models recorded yet.

## Anti-Goals
<!-- kos:section=anti_goals -->
Unknown. No owner-confirmed anti-goals recorded yet.

## Active Bets
<!-- kos:section=active_bets -->
Unknown. No owner-confirmed strategic bets recorded yet.

## Drift Log
<!-- kos:section=drift_log -->
| Topic | Shift Observed | Date Flagged | Evidence |
|---|---|---|---|
| — | Vault initialized | {today} | init |
"""


def _quote_arg(value: str) -> str:
    """Keep a literal path intact through the platform's host shell."""
    import os
    import shlex

    if os.name != "nt":
        return shlex.quote(value)
    if any(ch in value for ch in '%!"') or any(ord(ch) < 32 for ch in value):
        from knowledgeos.host_setup import UnsupportedHost

        raise UnsupportedHost(
            "Unsupported shell path on Windows: generated hooks cannot safely use "
            "paths containing %, !, double quotes, or control characters. "
            "Choose a path without these characters."
        )
    # cmd expands % and sometimes ! even inside quotes. Reject those above; always
    # quote the rest so metacharacters stay literal, doubling a closing backslash
    # for the executable's Windows argument parser.
    escaped = re.sub(r"(\\+)$", r"\1\1", value)
    return '"' + escaped + '"'


def _hooks_config(
    source: Path, vault: Path | None = None, toolkit_root: Path | None = None
) -> str:
    """Cursor hook config with an absolute interpreter path.

    The shipped file says ``python .cursor/hooks/...``, which resolves through PATH —
    on Windows a ``python.exe`` sitting in the vault or an earlier PATH entry wins.
    Rewriting it to the interpreter that ran ``init`` removes that ambiguity (and it
    still works if the user later installs Python elsewhere, because the fallback
    stays a path that existed at setup time).

    ``-P`` is also added, and it matters more than the absolute path. CPython puts the
    *script's own directory* first on ``sys.path``, so a hook at
    ``.cursor/hooks/twin_session_start.py`` imports ``json``, ``re``, and ``pathlib`` from
    ``.cursor/hooks/`` — a folder inside the vault. Dropping a ``json.py`` there executed
    vault content on every chat, and ``init`` reported no conflict because it only
    compares the files it knows about. ``-P`` keeps that directory off ``sys.path``.

    In the frozen binary ``sys.executable`` is *this program*, not Python, so writing it
    as the interpreter produced ``twinaatma.exe -P -E -s hook.py`` — a command that does
    not run at all. The binary re-executes its own ``hook`` subcommand instead, which is
    the same code path with the same guards.

    The vault is named on the command line in both installs. The hook script derives its
    vault from ``__file__``, which is right only while the script sits in the vault; in
    the bundle it is the extraction directory. That produced a hook that ran
    successfully against the wrong vault, the quietest possible failure, since nothing
    errors.

    The command names the script by its **absolute path inside the installed toolkit**,
    never the copy in the vault. Writing to ``.cursor/hooks/`` used to be enough to
    change what ran on the next chat, and no digest check can be trusted to keep up with
    that, so ``init`` no longer puts executable hook code in the vault at all: a vault
    that an agent can write cannot hold the program its next session runs. In the
    developer's own checkout the toolkit root *is* the vault, so the same files are used
    — that is the one case where the vault is the trusted source.
    """
    try:
        config = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return source.read_text(encoding="utf-8")

    toolkit_root = toolkit_root or source.resolve().parent.parent
    frozen = bool(getattr(sys, "frozen", False))
    older_python = sys.version_info < (3, 11)
    console_hook = frozen or older_python
    if frozen:
        interpreter = sys.executable or "twinaatma"
        quoted = _quote_arg(interpreter)
    elif older_python:
        import subprocess

        from knowledgeos.host_setup import UnsupportedHost

        try:
            probe = subprocess.run(
                [sys.executable, "-I", "-c", "import knowledgeos; print(knowledgeos.__file__)"],
                capture_output=True, text=True, timeout=30,
            )
            installed_here = (
                probe.returncode == 0
                and Path(probe.stdout.strip()).resolve() == Path(__file__).with_name("__init__.py").resolve()
            )
        except (OSError, subprocess.SubprocessError):
            installed_here = False
        if not installed_here:
            raise UnsupportedHost(
                "Running hooks from a source checkout needs Python 3.11+. "
                "Install this package in the current interpreter or use the packaged binary."
            )
        interpreter = sys.executable
        quoted = _quote_arg(interpreter)
    else:
        interpreter = sys.executable or "python"
        quoted = _quote_arg(interpreter)
    for group in (config.get("hooks") or {}).values():
        for entry in group if isinstance(group, list) else []:
            if not isinstance(entry, dict):
                continue
            command = str(entry.get("command") or "")
            if not command.startswith("python "):
                continue
            script = command.split(None, 1)[1].strip()
            name = Path(script).stem
            tail = f" --vault {_quote_arg(str(vault))}" if vault is not None else ""
            if console_hook:
                prefix = quoted if frozen else f"{quoted} -I -m knowledgeos"
                entry["command"] = f"{prefix} hook {name}{tail}"
            else:
                # Absolute path under the installed toolkit, plus `-P` so the script's own
                # directory never lands on `sys.path`.
                script_path = str((toolkit_root / ".cursor" / "hooks" / f"{name}.py"))
                entry["command"] = (
                    f"{quoted} -P -E -s {_quote_arg(script_path)}{tail}"
                )
    return json.dumps(config, indent=2) + "\n"


def _hook_shadow_files(hooks_dir: Path, expected: set[str]) -> list[str]:
    """Files in the hooks directory that `init` did not put there.

    The hook directory is inside the vault, so anything in it is vault content. `init`
    used to compare only the files it ships, so an added ``json.py`` was neither a
    conflict nor reported anywhere.

    Every file counts, not just ``*.py``: a package directory (``json/__init__.py``), a
    ``.pth`` file, or a ``sitecustomize.py`` are all importable, and reporting only the
    one extension that was reported last time is how this class of bug survives a fix.
    Directories are listed with a trailing slash so a planted package is visible.
    """
    if not hooks_dir.is_dir():
        return []
    found = []
    for entry in sorted(hooks_dir.iterdir(), key=lambda p: p.name):
        if entry.is_dir():
            found.append(entry.name + "/")
        elif entry.name not in expected:
            found.append(entry.name)
    return found



def init_vault(
    target: Path,
    *,
    source_root: Path | None = None,
    owner_name: str = "Self",
    non_interactive: bool = True,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    from knowledgeos.resources import toolkit_root

    source_root = (source_root or toolkit_root()).resolve()
    target = Path(os.path.abspath(target))
    plain_vault_path(target, target)
    src_hooks_json = source_root / ".cursor" / "hooks.json"
    rendered_hooks = _hooks_config(src_hooks_json, target, source_root) if src_hooks_json.exists() else None

    home = Path.home().resolve()
    if target == home or target.parent == target or target == Path(target.anchor):
        raise ValueError(
            f"Refusing to initialize a vault at {target}: choose a dedicated directory."
        )

    if target.exists():
        try:
            remaining = [p for p in target.iterdir() if p.name not in {".git", ".DS_Store"}]
        except OSError as exc:
            raise FileExistsError(f"Cannot read target directory {target}: {exc}") from exc
        # Re-running `init` on an existing vault is a *refresh*: it fills in whatever a
        # newer version added and never overwrites. Demanding --force for that made the
        # one command a user is told to run after an upgrade fail on its own output.
        from knowledgeos.vault_resolve import is_vault_root

        refresh = is_vault_root(target)
        if remaining and not force and not refresh:
            raise FileExistsError(
                f"Target is not empty: {target}. Use --force to fill in missing files "
                "(existing files are never overwritten)."
            )
    elif not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        refresh = False

    today = datetime.date.today().isoformat()
    plan = _Plan(target, dry_run, source_root)

    for d in STARTER_DIRS:
        plain_vault_path(target, target / d)

    if not dry_run:
        try:
            for d in STARTER_DIRS:
                (target / d).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OSError(f"Could not create the vault folders under {target}: {exc}") from exc

    # Copy note templates only — vaults are data-only, no code is copied.
    src_templates = source_root / "Templates"
    if src_templates.exists():
        for item in sorted(src_templates.glob("*.md")):
            plan.copy(item, target / "Templates" / item.name)

    from knowledgeos import __version__ as _toolkit_version

    # Keep the existing id. Regenerating it on a re-run would silently orphan every
    # pending proposal: the ledger is keyed by this value, so a new one makes the
    # human's own proposals unverifiable for no visible reason.
    existing_id = ""
    try:
        existing = json.loads((target / ".knowledgeos-vault.json").read_text(encoding="utf-8"))
        candidate = str(existing.get("vault_id") or "").strip()
        if re.fullmatch(r"[0-9a-fA-F]{16,64}", candidate):
            existing_id = candidate.lower()
    except (OSError, ValueError):
        existing_id = ""

    marker = {
        "vault": "twinaatma",
        "schema": "knowledgeos-v0.3",
        "toolkit_min_version": _toolkit_version,
        "created": today,
        # Stable identity for this vault. The proposal ledger is keyed by it rather
        # than by the folder path, so moving or renaming the vault does not orphan
        # every pending proposal.
        "vault_id": existing_id or uuid.uuid4().hex,
    }
    plan.write(
        target / ".knowledgeos-vault.json",
        json.dumps(marker, indent=2) + "\n",
        replace_state=True,
    )

    example = source_root / "knowledgeos.config.example.json"
    if example.exists():
        try:
            cfg = json.loads(example.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {"schema": "knowledgeos-v0.3", "mcp": {"enabled": True}}
        plan.copy(example, target / "knowledgeos.config.example.json")
        plan.write(target / "knowledgeos.config.json", json.dumps(cfg, indent=2) + "\n")

    for name in ("LICENSE", "AGENTS.md"):
        src = source_root / name
        if src.exists():
            plan.copy(src, target / name)

    src_rules = source_root / ".cursor" / "rules"
    if src_rules.exists():
        for item in sorted(src_rules.glob("*.mdc")):
            plan.copy(item, target / ".cursor" / "rules" / item.name)
    # The hook *code* is deliberately not copied into the vault. It used to be, and then
    # a plain note write to `.cursor/hooks/twin_session_start.py` changed what executed on
    # the next chat — a vault that can be written by an agent cannot be allowed to hold
    # the program that agent's next session runs. `doctor` reports a copy left behind by
    # an older install so it can be removed.
    leftover = target / ".cursor" / "hooks"
    if leftover.is_dir():
        for name in _hook_shadow_files(leftover, set()):
            plan.conflicts.append(
                f".cursor/hooks/{name} (left over from an older install; the hook now runs "
                "from the installed toolkit, so this file is not used and can be deleted)"
            )
    if rendered_hooks is not None:
        plan.write(
            target / ".cursor" / "hooks.json",
            rendered_hooks,
        )

    # Indexes
    plan.write(target / "Inbox" / "_Index.md", _index_note("Inbox Index", "Raw captures awaiting triage.", today))
    plan.write(target / "Concepts" / "_Index.md", _index_note("Concepts Index", "Reusable ideas and mental models.", today))
    plan.write(target / "Projects" / "_Index.md", _index_note("Projects Index", "Active work with outcomes.", today))
    plan.write(target / "Experiments" / "_Index.md", _index_note("Experiments Index", "Hypotheses and results.", today))
    plan.write(target / "Research" / "_Index.md", _index_note("Research Index", "Investigations and sources.", today))
    plan.write(target / "Decisions" / "_Index.md", _index_note("Decisions Index", "First-class decision log.", today))
    plan.write(target / "People" / "_Index.md", _index_note("People Index", "People and relationships.", today))

    plan.write(
        target / "MOCs" / "_MOC_Master.md",
        _moc(
            "Master MOC",
            "Root navigation for this vault.",
            today,
            """Start here.

## Spine
- [Active Work](_MOC_Active.md)
- [How KnowledgeOS Works](_MOC_How_KnowledgeOS_Works.md)
- [Self](../People/Self.md)

## Folders
- [Inbox](../Inbox/_Index.md)
- [Projects](../Projects/_Index.md)
- [Decisions](../Decisions/_Index.md)
- [Concepts](../Concepts/_Index.md)
- [Research](../Research/_Index.md)
""",
        ),
    )
    plan.write(
        target / "MOCs" / "_MOC_Active.md",
        _moc(
            "Active Work MOC",
            "What matters right now.",
            today,
            """## Active Projects
- _(none yet)_

## Pending Decisions
- _(none yet)_

## This Week
- Capture into Inbox
- Review Self.md Active Bets
""",
        ),
    )
    plan.write(
        target / "MOCs" / "_MOC_How_KnowledgeOS_Works.md",
        _moc(
            "How KnowledgeOS Works",
            "Beginner operating guide for this vault.",
            today,
            """## One-line
Portable cognitive memory: markdown you own, agents can load, Self-model that compounds.

## User setup (once)
Run `twinaatma setup-host --host cursor --write` inside the vault. After that, just chat —
agents follow `AGENTS.md` and keep the twin current. You should not need to remember commands.

## Loop (agent-owned)
Capture → Clarify → Connect → Decide → Execute → Record Outcome → Review → Update Self

## Daily (optional for humans who like Obsidian)
1. Drop raw notes in `Inbox/` if you prefer typing yourself
2. Otherwise: talk to your agent — it will capture and propose Self updates

## Weekly (agent-initiated)
Agents call `memory_ops_status` / session rituals. You only answer yes/no when asked.
""",
        ),
    )

    plan.write(target / "People" / "Self.md", _self_note(owner_name, today))

    # Frontmatter, because this file is now a note. `PRODUCT_FILES` used to hide every
    # root `README.md` from the index, which also hid the user's own — and `validate`
    # then reported the file `init` had just written as a schema error.
    plan.write(
        target / "README.md",
        f"""---
type: index
title: TwinAatma
description: Start here: what this vault is and how the agent uses it.
schema: knowledgeos-v0.3
status: active
created: {today}
updated: {today}
tags: [index, start-here]
---

# TwinAatma

Personal cognitive twin vault for **{owner_name}**.

Technical toolkit: `knowledgeos` (CLI/package). Public brand: TwinAatma *(Twin-AAT-maa)*.

## Promise

Wire MCP once (`twinaatma setup-host --host cursor --write`), then just chat. Agents follow
[AGENTS.md](AGENTS.md) and keep your twin current — you should not need toolkit commands.

## Agent wiring (Cursor)

This vault was initialized with a project MCP config at `.cursor/mcp.json`. If you move the
vault, re-run `twinaatma setup-host --host cursor --write` from the new location.

## Identity

Edit [People/Self.md](People/Self.md) — or let the agent propose updates and say yes/no.

Created: {today}
""",
    )

    plan.write(
        target / ".gitignore",
        """knowledge_index.db
knowledge_index.db-*
knowledgeos.config.json
.knowledgeos/
__pycache__/
*.pyc
.DS_Store
exports/
Assets/papers/
*.pdf
""",
    )

    result: dict = {
        "vault": str(target),
        "owner": owner_name,
        "created": today,
        "data_only": True,
        "dry_run": dry_run,
        "created_files": plan.created,
        "conflicts": plan.conflicts,
        "next_steps": [
            f"cd {target}",
            "Wire MCP once: twinaatma setup-host --host cursor --write",
            "Open the vault in Cursor — hooks + AGENTS.md keep the twin autopilot alive",
            "Chat normally — agents call memory_session_start; you only answer soft yes/no when asked",
        ],
    }
    if dry_run:
        return result

    # Canonical project MCP config, plus the legacy single-file copy at the vault root.
    from knowledgeos.host_setup import build_config

    cursor_cfg = build_config("cursor", target)
    plan.write(target / ".cursor" / "mcp.json", json.dumps(cursor_cfg, indent=2) + "\n")
    plan.write(target / "mcp.cursor.json", json.dumps(cursor_cfg, indent=2) + "\n")

    # Build the index and validate in-process so the new vault works without scripts/.
    from knowledgeos.indexer import rebuild_index
    from knowledgeos.validator import validate_vault

    post: dict = {"rebuild": None, "validate": None}
    try:
        counts = rebuild_index(target)
        post["rebuild"] = {
            "ok": True,
            "notes": counts["notes"],
            "links": counts["links"],
            "index_state": counts.get("index_state"),
        }
    except Exception as e:
        post["rebuild"] = {"ok": False, "error": str(e)}
    try:
        report = validate_vault(target)
        post["validate"] = {"ok": report["summary"]["errors"] == 0, "summary": report["summary"]}
    except Exception as e:
        post["validate"] = {"ok": False, "error": str(e)}

    result["post_init"] = post
    result["ok"] = all(check.get("ok") is True for check in post.values())
    if not result["ok"]:
        result["next_steps"] = [
            "Setup is incomplete. Existing content was preserved; inspect post_init errors and retry init after resolving them."
        ]
    result["created_files"] = plan.created
    result["conflicts"] = plan.conflicts
    env_note = {
        "KNOWLEDGEOS_VAULT": str(target),
        **({"PYTHONPATH": os.environ["PYTHONPATH"]} if os.environ.get("PYTHONPATH") else {}),
    }
    result["env"] = env_note
    plan.write(
        target / ".knowledgeos-init.json",
        json.dumps(result, indent=2) + "\n",
        replace_state=True,
    )
    return result
