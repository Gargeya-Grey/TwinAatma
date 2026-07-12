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
    "MOCs",
    "Templates",
    "Assets",
    "Archive",
    "scripts",
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

    # Copy templates from toolkit
    src_templates = source_root / "Templates"
    dst_templates = target / "Templates"
    if src_templates.exists():
        for item in src_templates.glob("*.md"):
            shutil.copy2(item, dst_templates / item.name)

    # Copy core scripts (stdlib toolkit)
    src_scripts = source_root / "scripts"
    dst_scripts = target / "scripts"
    if src_scripts.exists():
        for item in src_scripts.glob("*.py"):
            shutil.copy2(item, dst_scripts / item.name)
        for item in src_scripts.glob("*.sh"):
            shutil.copy2(item, dst_scripts / item.name)

    # Copy knowledgeos package
    src_pkg = source_root / "knowledgeos"
    dst_pkg = target / "knowledgeos"
    if src_pkg.exists():
        if dst_pkg.exists():
            shutil.rmtree(dst_pkg)
        shutil.copytree(
            src_pkg,
            dst_pkg,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    # Config example
    example = source_root / "knowledgeos.config.example.json"
    if example.exists():
        shutil.copy2(example, target / "knowledgeos.config.example.json")

    license_src = source_root / "LICENSE"
    if license_src.exists():
        shutil.copy2(license_src, target / "LICENSE")

    # Agent autopilot contract (user wires MCP once; agents follow this)
    agents_src = source_root / "AGENTS.md"
    if agents_src.exists():
        shutil.copy2(agents_src, target / "AGENTS.md")
    mcp_ex = source_root / "mcp.cursor.example.json"
    if mcp_ex.exists():
        shutil.copy2(mcp_ex, target / "mcp.cursor.example.json")
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
- Run `python scripts/daily_capture_report.py`
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
Wire the KnowledgeOS MCP server (see `mcp.cursor.example.json`). After that, just chat —
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

Wire MCP once (`mcp.cursor.example.json`). Then just chat. Agents follow [AGENTS.md](AGENTS.md)
and keep your twin current — you should not need toolkit commands for normal use.

## One-time agent wiring (Cursor)

Copy from `mcp.cursor.example.json` into your MCP settings; set `KNOWLEDGEOS_VAULT` to this folder.

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
        "next_steps": [
            f"cd {target}",
            "Wire MCP once using mcp.cursor.example.json (set KNOWLEDGEOS_VAULT to this folder)",
            "Open the vault in Cursor — hooks + AGENTS.md keep the twin autopilot alive",
            "Chat normally — agents call memory_session_start; you only answer soft yes/no when asked",
            "Optional: python scripts/onboarding.py  # first Self interview",
        ],
    }

    # Best-effort post-init rebuild + validate
    import subprocess
    import sys

    post = {"rebuild": None, "validate": None}
    try:
        r1 = subprocess.run(
            [sys.executable, str(target / "scripts" / "rebuild_index.py")],
            cwd=str(target),
            capture_output=True,
            text=True,
            timeout=120,
        )
        post["rebuild"] = {"ok": r1.returncode == 0, "stdout": (r1.stdout or "")[-500:]}
    except Exception as e:
        post["rebuild"] = {"ok": False, "error": str(e)}
    try:
        r2 = subprocess.run(
            [sys.executable, str(target / "scripts" / "validate_schema.py")],
            cwd=str(target),
            capture_output=True,
            text=True,
            timeout=120,
        )
        post["validate"] = {"ok": r2.returncode == 0, "stdout": (r2.stdout or "")[-800:]}
    except Exception as e:
        post["validate"] = {"ok": False, "error": str(e)}

    result["post_init"] = post
    (target / ".knowledgeos-init.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
