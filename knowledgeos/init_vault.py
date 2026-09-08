"""Create a clean starter KnowledgeOS vault from the toolkit templates."""
from __future__ import annotations

import datetime
import json
import shutil
from pathlib import Path

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


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.lstrip("\n") if content.startswith("\n") else content, encoding="utf-8")


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
* Prefer durability over cleverness — markdown remains source of truth.
* Write a decision note before major scope shifts.
* Close loops: Capture → Decide → Outcome → Lesson → Self update.

## Values Hierarchy
<!-- kos:section=values -->
1. **Clarity**
2. **Autonomy**
3. **Execution**

## Mental Models
<!-- kos:section=mental_models -->
* First Principles
* Inversion

## Anti-Goals
<!-- kos:section=anti_goals -->
* Building before validating
* Letting Inbox grow without triage

## Active Bets
<!-- kos:section=active_bets -->
* _(Add your current strategic bets)_

## Drift Log
<!-- kos:section=drift_log -->
| Topic | Shift Observed | Date Flagged | Evidence |
|---|---|---|---|
| — | Vault initialized | {today} | init |
"""


def init_vault(
    target: Path,
    *,
    source_root: Path,
    owner_name: str = "Self",
    non_interactive: bool = True,
    force: bool = False,
) -> dict:
    target = target.resolve()
    if target.exists():
        remaining = [p for p in target.iterdir() if p.name not in {".git", ".DS_Store"}]
        if remaining and not force:
            raise FileExistsError(
                f"Target is not empty: {target}. Use --force to proceed carefully, or choose a new path."
            )
    else:
        target.mkdir(parents=True, exist_ok=True)

    today = datetime.date.today().isoformat()

    for d in STARTER_DIRS:
        (target / d).mkdir(parents=True, exist_ok=True)

    # Copy note templates only — vaults are data-only, no code is copied.
    # The twinaatma binary (or python -m knowledgeos) operates on the vault
    # via --vault / KNOWLEDGEOS_VAULT / walk-up resolution.
    src_templates = source_root / "Templates"
    dst_templates = target / "Templates"
    if src_templates.exists():
        for item in src_templates.glob("*.md"):
            shutil.copy2(item, dst_templates / item.name)

    # Vault marker: identifies this dir as a TwinAatma vault for walk-up.
    from knowledgeos import __version__ as _toolkit_version

    marker = {
        "vault": "twinaatma",
        "schema": "knowledgeos-v0.3",
        "toolkit_min_version": _toolkit_version,
        "created": today,
    }
    (target / ".knowledgeos-vault.json").write_text(
        json.dumps(marker, indent=2), encoding="utf-8"
    )

    # Rendered config (not just the example) so hosts/tools work out of the box.
    example = source_root / "knowledgeos.config.example.json"
    if example.exists():
        try:
            cfg = json.loads(example.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {"schema": "knowledgeos-v0.3", "mcp": {"enabled": True}}
        shutil.copy2(example, target / "knowledgeos.config.example.json")
        if not (target / "knowledgeos.config.json").exists():
            (target / "knowledgeos.config.json").write_text(
                json.dumps(cfg, indent=2), encoding="utf-8"
            )

    license_src = source_root / "LICENSE"
    if license_src.exists():
        shutil.copy2(license_src, target / "LICENSE")

    # Agent autopilot contract (user wires MCP once; agents follow this)
    agents_src = source_root / "AGENTS.md"
    if agents_src.exists():
        shutil.copy2(agents_src, target / "AGENTS.md")
    # Generated host config with the real vault path (no hardcoded placeholders).
    from knowledgeos.host_setup import build_config

    (target / "mcp.cursor.json").write_text(
        json.dumps(build_config("cursor", target), indent=2), encoding="utf-8"
    )
    src_rules = source_root / ".cursor" / "rules"
    if src_rules.exists():
        dst_rules = target / ".cursor" / "rules"
        dst_rules.mkdir(parents=True, exist_ok=True)
        for item in src_rules.glob("*.mdc"):
            shutil.copy2(item, dst_rules / item.name)
    # Cursor hooks (session pre-warm / orphan detection)
    src_hooks_json = source_root / ".cursor" / "hooks.json"
    if src_hooks_json.exists():
        (target / ".cursor").mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_hooks_json, target / ".cursor" / "hooks.json")
    src_hooks = source_root / ".cursor" / "hooks"
    if src_hooks.exists():
        dst_hooks = target / ".cursor" / "hooks"
        dst_hooks.mkdir(parents=True, exist_ok=True)
        for item in src_hooks.glob("*.py"):
            shutil.copy2(item, dst_hooks / item.name)

    # Indexes
    _write(target / "Inbox" / "_Index.md", _index_note("Inbox Index", "Raw captures awaiting triage.", today))
    _write(target / "Concepts" / "_Index.md", _index_note("Concepts Index", "Reusable ideas and mental models.", today))
    _write(target / "Projects" / "_Index.md", _index_note("Projects Index", "Active work with outcomes.", today))
    _write(target / "Experiments" / "_Index.md", _index_note("Experiments Index", "Hypotheses and results.", today))
    _write(target / "Research" / "_Index.md", _index_note("Research Index", "Investigations and sources.", today))
    _write(target / "Decisions" / "_Index.md", _index_note("Decisions Index", "First-class decision log.", today))
    _write(target / "People" / "_Index.md", _index_note("People Index", "People and relationships.", today))

    _write(
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
    _write(
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
    _write(
        target / "MOCs" / "_MOC_How_KnowledgeOS_Works.md",
        _moc(
            "How KnowledgeOS Works",
            "Beginner operating guide for this vault.",
            today,
            """## One-line
Portable cognitive memory: markdown you own, agents can load, Self-model that compounds.

## User setup (once)
Run `twinaatma setup-host --host cursor --vault .` (or copy `mcp.cursor.json`
into your MCP settings). After that, just chat —
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

    _write(target / "People" / "Self.md", _self_note(owner_name, today))

    readme = f"""# TwinAatma

Personal cognitive twin vault for **{owner_name}**.

Technical toolkit: `knowledgeos` (CLI/package). Public brand: TwinAatma *(Twin-AAT-maa)*.

## Promise

Wire MCP once (`twinaatma setup-host --host cursor --vault .`, or copy
`mcp.cursor.json` into your MCP settings). Then just chat. Agents follow [AGENTS.md](AGENTS.md)
and keep your twin current — you should not need toolkit commands for normal use.

## One-time agent wiring (Cursor)

`mcp.cursor.json` was generated for this vault path. If you move the vault,
re-run `twinaatma setup-host --host cursor --vault .` and set `KNOWLEDGEOS_VAULT` to this folder.

## Identity

Edit [People/Self.md](People/Self.md) — or let the agent propose updates and say yes/no.

Created: {today}
"""
    _write(target / "README.md", readme)

    # Minimal gitignore
    _write(
        target / ".gitignore",
        """knowledge_index.db
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

    result = {
        "vault": str(target),
        "owner": owner_name,
        "created": today,
        "data_only": True,
        "next_steps": [
            f"cd {target}",
            "Wire MCP once: twinaatma setup-host --host cursor --vault .  (or python -m knowledgeos setup-host ...)",
            "Open the vault in Cursor — hooks + AGENTS.md keep the twin autopilot alive",
            "Chat normally — agents call memory_session_start; you only answer soft yes/no when asked",
        ],
    }

    # Best-effort post-init rebuild + validate (in-process, no subprocess,
    # no scripts/ inside the new vault — operate via vault path).
    post = {"rebuild": None, "validate": None}
    try:
        import runpy

        import os as _os

        _old = _os.environ.get("KNOWLEDGEOS_VAULT")
        _os.environ["KNOWLEDGEOS_VAULT"] = str(target)
        try:
            runpy.run_path(
                str(source_root / "scripts" / "rebuild_index.py"),
                run_name="__main__",
            )
            post["rebuild"] = {"ok": True}
        except SystemExit as e:
            post["rebuild"] = {"ok": e.code in (None, 0)}
        except Exception as e:
            post["rebuild"] = {"ok": False, "error": str(e)}
        try:
            runpy.run_path(
                str(source_root / "scripts" / "validate_schema.py"),
                run_name="__main__",
            )
            post["validate"] = {"ok": True}
        except SystemExit as e:
            post["validate"] = {"ok": e.code in (None, 0)}
        except Exception as e:
            post["validate"] = {"ok": False, "error": str(e)}
        finally:
            if _old is None:
                _os.environ.pop("KNOWLEDGEOS_VAULT", None)
            else:
                _os.environ["KNOWLEDGEOS_VAULT"] = _old
    except Exception as e:
        post["rebuild"] = {"ok": False, "error": str(e)}

    result["post_init"] = post
    (target / ".knowledgeos-init.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
