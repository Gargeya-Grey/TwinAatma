"""Read every shipped source surface and account for local mutation implementations."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import tomllib
from pathlib import Path

VERSION = "verify-twinaatma.writer-census/v1"
SURFACE_ROOTS = ("knowledgeos", "scripts", ".cursor/hooks")

FILE_GROUPS = {
    "router": "knowledgeos/__main__.py knowledgeos/binary_entry.py knowledgeos/mcp_server.py",
    "memory": "knowledgeos/memory.py",
    "sessions": "knowledgeos/autopilot.py .cursor/hooks/twin_session_start.py .cursor/hooks/twin_session_end.py",
    "proposal": "knowledgeos/gate.py knowledgeos/evolution.py scripts/propose_self_update.py",
    "outcome": "knowledgeos/outcomes.py",
    "policy": "knowledgeos/remembering.py",
    "index": "knowledgeos/indexer.py knowledgeos/database.py scripts/rebuild_index.py scripts/rebuild_index.sh scripts/capture.sh",
    "init": "knowledgeos/init_vault.py",
    "setup": "knowledgeos/host_setup.py",
    "ids": "knowledgeos/ids.py",
    "generated": "knowledgeos/intelligence.py scripts/draft_weekly_synthesis.py scripts/intelligence_brief.py scripts/learning_trajectory.py scripts/experiment_dashboard.py scripts/outcomes_dashboard.py scripts/update_mocs.py",
    "links": "scripts/refactor_links.py",
    "export": "scripts/export_bundle.py",
    "git-hooks": "scripts/setup_git_hooks.py",
    "implementation": "knowledgeos/data_ops.py knowledgeos/textio.py knowledgeos/locking.py knowledgeos/vaultstate.py",
    "retired": "scripts/onboarding.py",
    "database-reader": "knowledgeos/search.py scripts/check_alignment.py scripts/refinement_report.py scripts/smoke_test.py scripts/weekly_data.py",
    "read-only": "knowledgeos/__init__.py knowledgeos/codex_config.py knowledgeos/concepts.py knowledgeos/doctor.py knowledgeos/links.py knowledgeos/parser.py knowledgeos/py.typed knowledgeos/resources.py knowledgeos/safe_exec.py knowledgeos/schema.py knowledgeos/self_model.py knowledgeos/validator.py knowledgeos/vault.py knowledgeos/vault_resolve.py scripts/daily_capture_report.py scripts/doctor.py scripts/search.py scripts/search.sh scripts/semantic_drift.py scripts/validate_schema.py scripts/weekly_data.sh",
    "optional-external": "scripts/_notion_env.py scripts/notion_bridge.py scripts/notion_inspect.py scripts/notion_test.py scripts/publish_to_notion.py",
}
FILE_ROLES = {name: group for group, names in FILE_GROUPS.items() for name in names.split()}
FILE_EVIDENCE = {
    "router": ["focused:memory-tools", "focused:cli-routing"],
    "memory": ["focused:memory-tools", "focused:alias-matrix", "reused:core"],
    "sessions": ["focused:hooks", "focused:alias-matrix", "reused:recovery"],
    "proposal": ["focused:proposals", "focused:alias-matrix", "reused:core", "reused:recovery"],
    "outcome": ["focused:reviewed-outcome", "focused:alias-matrix"],
    "policy": ["focused:policy", "focused:alias-matrix"],
    "index": ["focused:source-index-wrappers", "focused:database-sidecars", "reused:recovery"],
    "init": ["focused:init-refresh", "focused:alias-matrix"],
    "setup": ["focused:setup", "focused:alias-matrix"],
    "ids": ["reused:maintenance"],
    "generated": ["focused:generated-script-wrappers", "reused:generated", "reused:census", "reused:maintenance"],
    "links": ["reused:maintenance"],
    "export": ["reused:export"],
    "git-hooks": ["reused:hooks"],
    "implementation": ["upstream-public-callers"],
    "retired": ["focused:retired-onboarding"],
    "database-reader": ["focused:read-script-wrappers", "focused:database-sidecars", "reused:recovery"],
    "read-only": ["static:no-local-source-write", "focused:memory-tools", "focused:read-script-wrappers", "focused:database-sidecars"],
    "optional-external": ["static:no-local-write", "outside-core-local-contract:no-network-execution"],
}
WRITE_NAMES = {
    "write_text", "write_bytes", "atomic_write", "atomic_write_bytes", "atomic_create_bytes",
    "write_preserving_endings", "write_generated", "_write_atomic", "_write_exact", "save_state",
    "_write_ledger", "mkdir", "unlink", "rename", "rmdir", "copy2", "copytree", "chmod",
    "fchmod", "symlink_to", "hardlink_to", "connect_database", "executescript", "truncate",
}
FILE_RECEIVERS = {"path", "db_path", "sidecar", "tmp", "source", "target", "destination", "old", "backup"}
SQL_WRITE = re.compile(r"\b(?:INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|BEGIN IMMEDIATE|journal_mode)\b", re.I)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return call_name(node.value) + "." + node.attr
    return ast.unparse(node)


def mutating_call(call):
    name = call_name(call.func)
    leaf = name.rsplit(".", 1)[-1]
    if leaf in WRITE_NAMES:
        return "filesystem-or-persistent-writer"
    if leaf == "replace" and (name.startswith("os.") or len(call.args) == 1 and name.split(".", 1)[0] in FILE_RECEIVERS):
        return "filesystem-replacement"
    if name in {"os.link", "os.symlink", "os.remove", "os.rename", "os.rmdir"}:
        return "filesystem-mutation"
    if leaf in {"open", "fdopen"}:
        mode = call.args[1] if len(call.args) > 1 else next((k.value for k in call.keywords if k.arg == "mode"), None)
        if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
            return "opened-for-write" if any(c in mode.value for c in "wax+") else None
        if mode is not None and any(flag in ast.unparse(mode) for flag in ("O_CREAT", "O_WRONLY", "O_RDWR", "O_TRUNC")):
            return "opened-for-write"
    if leaf == "execute" and call.args:
        argument = call.args[0]
        value = argument.value if isinstance(argument, ast.Constant) and isinstance(argument.value, str) else ast.unparse(argument)
        if SQL_WRITE.search(value) or value in {"_INSERT_NOTE_SQL", "_FTS_SQL"}:
            return "sqlite-mutation"
    if name == "sqlite3.connect":
        return "memory-sqlite" if call.args and isinstance(call.args[0], ast.Constant) and call.args[0].value == ":memory:" else "disk-sqlite"
    return None


def tool_specs(tree):
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "name" and isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value.startswith("memory_"):
                    found.append(value.value)
    return sorted(set(found))


def caller_map(tools, methods):
    callers = {
        "console:twinaatma": ["source CLI routing; installed entrypoint remains a separate scope"],
        "cli:init": ["writers.init-refresh", "writers.init-refresh fixture initialization", "source core init/configuration cases"],
        "cli:setup-host": ["writers.setup-cursor", "writers.setup-vscode", "writers.setup-codex", "writers.setup-out-existing-self", "writers.setup-out-new", "writers.hard-setup-*", "writers.setup-fault", "writers.setup-fault-retry"],
        "cli:ids assign": ["data.maintenance.ids_*"],
        "cli:memory": ["writers.cli-capture", "writers.legacy-outcome", "writers.capture-fault", "writers.outcome-fault", "writers.policy-fault"],
        "cli:breathe": ["writers.cli-breathe"],
        "cli:hook twin_session_start": ["writers.cli-hook-start"],
        "cli:hook twin_session_end": ["writers.cli-hook-end"],
        "cli:mcp": ["writers.normal-tools and every focused original MCP wire transcript"],
        "cli:doctor": ["source core initialization doctor"],
        "cli:validate": ["data.validation.*"],
        "cli:self summary/pending": ["static read-only identity access; shared gate-binding writes covered by memory list/proposal observations"],
        "cli:self approve": ["outside this alternative-writer unit; human-only canonical identity change remains NOT CHECKED"],
        "library:learning_trajectory_report": ["data.generated.trajectory-*"],
        "library:weekly_intelligence_report": ["data.generated.weekly-*"],
        "library:write_intelligence_views": ["data.generated.views-*"],
    }
    for tool in tools:
        callers["mcp:" + tool] = ["source core original MCP refusal"] if tool == "memory_accept_self_update" else ["writers.normal-reject"] if tool == "memory_reject_self_update" else ["writers.normal-tools"]
    for method in methods:
        tool = {"accept_self_update": "memory_accept_self_update", "reject_self_update": "memory_reject_self_update"}.get(method, "memory_" + method)
        if "mcp:" + tool not in callers:
            raise ValueError("Unmapped public MemoryAPI caller needs an actual exercise: " + method)
        callers["library:MemoryAPI." + method] = callers["mcp:" + tool]
    return callers


def read_census(root):
    root = Path(root)
    paths = sorted(p for base in SURFACE_ROOTS for p in (root / base).rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"})
    names = {p.relative_to(root).as_posix() for p in paths}
    missing, obsolete = names - FILE_ROLES.keys(), FILE_ROLES.keys() - names
    if missing or obsolete:
        raise ValueError("Unreviewed source-surface census drift: " + json.dumps({"unclassified": sorted(missing), "removed": sorted(obsolete)}))
    files, sinks, imports = {}, [], {}
    tools, methods = [], []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        group = FILE_ROLES[relative]
        row = {"sha256": sha(path), "classification": group, "evidence_families": FILE_EVIDENCE[group]}
        files[relative] = row
        if path.suffix != ".py":
            row["shell_commands"] = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                                     if line.strip() and not line.lstrip().startswith("#")] if path.suffix == ".sh" else []
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative)
        scopes = {}
        class Scope(ast.NodeVisitor):
            current = "<module>"
            def visit_FunctionDef(self, node):
                previous = self.current
                self.current = previous + "." + node.name if previous != "<module>" else node.name
                scopes[node.lineno] = self.current
                self.generic_visit(node)
                self.current = previous
            visit_AsyncFunctionDef = visit_FunctionDef
            def visit_Call(self, node):
                kind = mutating_call(node)
                if kind:
                    sinks.append({"file": relative, "line": node.lineno, "function": self.current,
                                  "call": ast.unparse(node), "kind": kind, "family": group,
                                  "evidence_families": FILE_EVIDENCE[group]})
                self.generic_visit(node)
        Scope().visit(tree)
        row["defined_callables"] = sorted(scopes.values())
        row["local_mutation_site_count"] = sum(s["file"] == relative and s["kind"] != "memory-sqlite" for s in sinks)
        imports[relative] = sorted({node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("knowledgeos")}
                                   | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names if alias.name.startswith("knowledgeos")})
        if relative == "knowledgeos/memory.py":
            tools = tool_specs(tree)
            api = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MemoryAPI")
            methods = sorted(n.name for n in api.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"))
    forbidden = [s for s in sinks if s["family"] in {"read-only", "optional-external", "retired"} and s["kind"] != "memory-sqlite"]
    if forbidden:
        raise ValueError("A classified nonwriter has a newly discovered mutation site: " + json.dumps(forbidden))
    main = ast.parse((root / "knowledgeos/__main__.py").read_text(encoding="utf-8-sig"))
    cli = set()
    for node in ast.walk(main):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "cmd":
            for comparator in node.comparators:
                values = comparator.elts if isinstance(comparator, (ast.Set, ast.Tuple, ast.List)) else [comparator]
                cli.update(v.value for v in values if isinstance(v, ast.Constant) and isinstance(v.value, str))
    require_cli = {"hook", "doctor", "validate", "ids", "self", "init", "memory", "breathe", "mcp", "setup-host", "version", "--version", "-V"}
    if cli != require_cli:
        raise ValueError("Unreviewed public CLI caller drift: " + repr(sorted(cli ^ require_cli)))
    entries = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8-sig")).get("project", {}).get("scripts", {})
    if entries != {"twinaatma": "knowledgeos.__main__:main"}:
        raise ValueError("Unreviewed advertised package console entrypoints: " + repr(entries))
    readme = (root / "README.md").read_text(encoding="utf-8")
    advertised = sorted(set(re.findall(r'(?:scripts|\.cursor/hooks|knowledgeos)/[A-Za-z0-9_./-]+\.(?:py|sh)', readme)))
    unknown_advertised = [p for p in advertised if p not in files]
    if unknown_advertised:
        raise ValueError("Advertised source entrypoint leaves the census: " + repr(unknown_advertised))
    return {"version": VERSION, "roots": list(SURFACE_ROOTS), "files": files, "mutation_sites": sinks,
            "knowledgeos_import_edges": imports, "cli_commands": sorted(cli), "memory_tools": tools,
            "memory_api_public_methods": methods, "advertised_source_entrypoints": advertised,
            "public_caller_evidence_map": caller_map(tools, methods),
            "package_console_entries": entries,
            "implementation_policy": "Generic filesystem helpers are implementations. Their public CLI, MCP, library and source-script callers need actual observations.",
            "optional_external_limit": "Notion has no local filesystem mutation sinks in this census. Network execution and external publication remain outside the core-local identity outcome."}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(read_census(args.root), indent=2))
