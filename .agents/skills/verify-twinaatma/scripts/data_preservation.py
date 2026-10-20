"""Prove source export preservation in complete toolkit copies with synthetic data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[4]
PRODUCER = "verify-twinaatma.data-preservation/v1"
DEPENDENCY_POLICY = "Selected Markdown notes only; linked notes and attachments are not automatically included."
REMEMBERING_POLICY = "Excluded notes are omitted. Historical sources retain explicit attribution in this manifest."
SELECTION = ["Concepts/Launch.md", "Projects/Nova.md"]
NOTES = {
    "Concepts/Launch.md": b"---\ntype: concept\ntitle: Launch decision\ndescription: Synthetic launch evidence\nstatus: active\nschema: knowledgeos-v0.2\ncreated: 2026-10-19\nupdated: 2026-10-19\ntags: [synthetic, launch]\nproject: Nova\nid: kos:concept:launch\n---\n# Launch decision\nKeep [[Research/Context]] and [map](../Assets/map.bin) as dependencies.\n",
    "Projects/Nova.md": b"---\ntype: project\ntitle: Nova\ndescription: Synthetic project only\nstatus: draft\nschema: knowledgeos-v0.2\ncreated: 2026-10-19\nupdated: 2026-10-19\ntags: [synthetic]\nproject: Nova\nid: kos:project:nova\n---\n# Nova\n[Launch](../Concepts/Launch.md) stays relative.\r\n",
    "Research/Context.md": b"# Context\nUnselected related note.\n",
    "People/Self.md": b"# Self\nUnknown identity. Preserve these exact bytes.\r\n",
    "People/Self-Proposals/pending.md": b"---\nstatus: draft\n---\n# Unapproved synthetic proposal\n",
    "People/Self-Proposals/rejected.md": b"---\nstatus: rejected\n---\n# Rejected synthetic proposal\n",
    "Assets/map.bin": b"\x00synthetic-attachment\xff\n",
}
EXPECTED_ENTRIES = [
    {"path": "Concepts/Launch.md", "title": "Launch decision", "type": "concept", "status": "active",
     "description": "Synthetic launch evidence", "resource": "", "tags": ["synthetic", "launch"],
     "project": "Nova", "id": "kos:concept:launch", "memory_status": "current"},
    {"path": "Projects/Nova.md", "title": "Nova", "type": "project", "status": "draft",
     "description": "Synthetic project only", "resource": "", "tags": ["synthetic"],
     "project": "Nova", "id": "kos:project:nova", "memory_status": "current"},
]
CASES = (
    ("existing_directory", ["Concepts"], "unowned", "refuse"),
    ("existing_file", ["Concepts"], "unowned.bin", "refuse"),
    ("identity_directory", ["Concepts"], "People", "refuse"),
    ("equal_source", ["Concepts"], "Concepts", "refuse"),
    ("nested_output", ["Concepts"], "Concepts/fresh", "refuse"),
    ("outside_prefix_sibling", ["Concepts"], "../vault-sibling/bundle", "refuse"),
    ("linked_source_file", ["Concepts/linked.md"], "fresh", "refuse"),
    ("linked_source_directory", ["LinkedNotes"], "fresh", "refuse"),
    ("linked_output_file", ["Concepts"], "linked-output", "refuse"),
    ("linked_output_parent", ["Concepts"], "linked-outputs/fresh", "refuse"),
    ("hardlinked_source", ["Concepts/hard.md"], "fresh", "refuse"),
    ("hardlinked_output", ["Concepts"], "hard-output", "refuse"),
    ("fresh_bundle", SELECTION, "bundle-fresh", "bundle"),
    ("source_prefix_sibling", SELECTION, "Concepts-export", "bundle"),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(directory):
    """Inspect every lexical entry, including link targets, without following links."""
    result = {}
    def visit(path):
        for entry in sorted(os.scandir(path), key=lambda item: item.name):
            member = Path(entry.path)
            relative = member.relative_to(directory).as_posix()
            info = member.lstat()
            linked = stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
            if linked:
                result[relative] = {"kind": "link", "target": os.readlink(member)}
            elif stat.S_ISDIR(info.st_mode):
                result[relative] = {"kind": "directory"}
                visit(member)
            elif stat.S_ISREG(info.st_mode):
                result[relative] = {"kind": "file", "size": info.st_size, "sha256": sha(member), "links": info.st_nlink}
            else:
                result[relative] = {"kind": "other", "mode": info.st_mode}
    visit(Path(directory))
    return result


def source_files():
    files = []
    for relative in ("knowledgeos", "scripts", "Templates", ".cursor/hooks"):
        for path in (ROOT / relative).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo"):
                if path.is_symlink():
                    raise ValueError("Toolkit input is linked: " + str(path))
                files.append(path)
    files.extend(ROOT / name for name in ("AGENTS.md", "README.md", "pyproject.toml", "setup.py", "MANIFEST.in", "LICENSE", "knowledgeos.config.example.json", "mcp.cursor.example.json"))
    return sorted(set(files))


_POLICY_DIRECTORY = "vault/.knowledgeos"
_POLICY_GUARD = _POLICY_DIRECTORY + "/remembering-policy.lock.guard"
_CANONICAL_POLICY_GUARD = {
    "kind": "file", "size": 1, "links": 1,
    "sha256": "5feceb66ffc86f38d952786c6d696c79c2dbc239dd4e91b46729d73a27fb57e9",
}


def operational_metadata_creation(before, after):
    """Observe only first creation of the plain, single-link literal b'0' guard."""
    guard = after.get(_POLICY_GUARD)
    keys = before.keys() | after.keys()
    if (_POLICY_GUARD in before or guard != _CANONICAL_POLICY_GUARD
            or type(guard.get("size")) is not int or type(guard.get("links")) is not int
            or any(key.startswith(_POLICY_GUARD + "/") for key in keys)
            or after.get(_POLICY_DIRECTORY) != {"kind": "directory"}):
        return []
    if _POLICY_DIRECTORY in before:
        return [_POLICY_GUARD] if before[_POLICY_DIRECTORY] == {"kind": "directory"} else []
    prefix = _POLICY_DIRECTORY + "/"
    if (any(key.startswith(prefix) for key in before)
            or {key for key in after if key.startswith(prefix)} != {_POLICY_GUARD}):
        return []
    return [_POLICY_DIRECTORY, _POLICY_GUARD]


def preservation_observation(before, after, output=None):
    prefix = "vault/" + output.rstrip("/") if output else None
    remaining = {key: value for key, value in after.items()
                 if prefix is None or (key != prefix and not key.startswith(prefix + "/"))}
    changed = sorted(key for key in before.keys() | remaining.keys() if before.get(key) != remaining.get(key))
    operational = [key for key in operational_metadata_creation(before, after) if key in changed]
    changed = [key for key in changed if key not in operational]
    result = {"unchanged": not changed, "changed": changed}
    if operational:
        result["operational_metadata_created"] = operational
    return result


def bundle_observation(vault, output):
    bundle = vault / output
    observed = {"manifest_present": (bundle / "manifest.json").is_file()}
    try:
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        members = inventory(bundle)
        files = sorted(path for path, row in members.items() if row["kind"] == "file")
        observed.update(manifest=manifest, files=files,
                        selected_bytes_match=all((bundle / p).read_bytes() == NOTES[p] for p in SELECTION),
                        omissions_absent=not (bundle / "Research/Context.md").exists() and not (bundle / "Assets/map.bin").exists(),
                        paths_plain=all(row["kind"] in ("file", "directory") and row.get("links", 1) == 1 for row in members.values()))
        observed["valid"] = (files == sorted([*SELECTION, "manifest.json"]) and observed["selected_bytes_match"]
                             and observed["omissions_absent"] and observed["paths_plain"]
                             and isinstance(manifest, dict) and manifest.get("format") == "KnowledgeOS portable markdown bundle"
                             and manifest.get("schema") == "knowledgeos-v0.2" and manifest.get("source_vault") == str(vault)
                             and manifest.get("selector") == {"project": None, "paths": SELECTION}
                             and manifest.get("notes") == EXPECTED_ENTRIES
                             and manifest.get("remembering_policy") == REMEMBERING_POLICY
                             and type(manifest.get("excluded_count")) is int
                             and manifest["excluded_count"] == len(SELECTION) - sum(path != "manifest.json" for path in files)
                             and manifest.get("dependency_policy") == DEPENDENCY_POLICY
                             and isinstance(manifest.get("created_at"), str) and bool(manifest["created_at"]))
    except (OSError, ValueError, TypeError, KeyError) as error:
        observed.update(valid=False, error=str(error))
    return observed


def checked_output(output):
    requested = Path(output).absolute()
    for component in (requested, *requested.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError("Output may not traverse a linked/reparse component")
    base = requested.resolve(strict=False)
    generated = (ROOT / "work/gc-artifacts").resolve()
    if not base.is_relative_to(generated) or ".knowledgeos" not in base.relative_to(generated).parts:
        raise ValueError("Output must be below work/gc-artifacts and contain .knowledgeos")
    return base


class DataRun:
    def __init__(self, output):
        base = checked_output(output)
        self.directory = base / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        self.directory.mkdir(parents=True, exist_ok=False)
        self.cases, self.processes = [], []
        self.inputs = source_files()
        self.sources = {p.relative_to(ROOT).as_posix(): sha(p) for p in self.inputs}
        self.protected = [ROOT / "People/Self.md", ROOT / "knowledge_index.db", ROOT / ".knowledgeos/autopilot.json"]
        self.before = self.sentinels()
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
                        KNOWLEDGEOS_STATE_DIR=str(self.directory / "gate-state"))
        for key in ("PYTHONPATH", "PYTHONHOME", "KNOWLEDGEOS_VAULT", "VIRTUAL_ENV"):
            self.env.pop(key, None)

    def sentinels(self):
        return {str(p): sha(p) if p.is_file() else None for p in self.protected}

    def save(self, name, value):
        (self.directory / name).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")

    def command(self, label, command, cwd, vault=None, timeout=60):
        env = dict(self.env)
        if vault is not None:
            env["KNOWLEDGEOS_VAULT"] = str(vault)
        started = time.monotonic()
        process = subprocess.Popen(list(map(str, command)), cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        tracked = {"pid": process.pid, "role": label, "stopped": False}
        self.processes.append(tracked)
        error = None
        interruption = None
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            error = "Command exceeded the proof deadline"
        except BaseException as caught:
            process.kill()
            stdout, stderr = process.communicate()
            error = str(caught)
            interruption = caught
        finally:
            tracked.update(stopped=process.poll() is not None, exit_code=process.returncode)
        (self.directory / (label + ".stdout.txt")).write_text(stdout, encoding="utf-8")
        (self.directory / (label + ".stderr.txt")).write_text(stderr, encoding="utf-8")
        record = {"command": list(map(str, command)), "cwd": str(cwd), "shell": False,
                  "vault": str(vault) if vault is not None else None, "state_dir": env["KNOWLEDGEOS_STATE_DIR"],
                  "pid": process.pid, "exit_code": process.returncode, "seconds": time.monotonic() - started,
                  "stopped": tracked["stopped"], "error": error}
        self.save(label + ".command.json", record)
        if interruption is not None:
            raise interruption
        return record, stdout, stderr

    def fixture(self, label):
        scope = self.directory / "fixtures" / label
        vault = scope / "vault"
        vault.mkdir(parents=True)
        for source in self.inputs:
            destination = vault / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        for relative, content in NOTES.items():
            target = vault / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        outside = scope / "outside"
        outside.mkdir()
        (outside / "private.md").write_bytes(b"# Outside synthetic private note\n")
        (outside / "sentinel.bin").write_bytes(b"OUTSIDE SENTINEL\x00\xff\n")
        return scope, vault, outside

    def prepare_case(self, identifier, vault, outside):
        if identifier == "existing_directory":
            (vault / "unowned").mkdir()
            (vault / "unowned/edited.bin").write_bytes(b"USER OWNED\x00\xff")
        elif identifier == "existing_file":
            (vault / "unowned.bin").write_bytes(b"USER FILE\x00\xff")
        elif identifier == "linked_source_file":
            (vault / "Concepts/linked.md").symlink_to(outside / "private.md")
        elif identifier == "linked_source_directory":
            (vault / "LinkedNotes").symlink_to(outside, target_is_directory=True)
        elif identifier == "linked_output_file":
            (vault / "linked-output").symlink_to(outside / "sentinel.bin")
        elif identifier == "linked_output_parent":
            (vault / "linked-outputs").symlink_to(outside, target_is_directory=True)
        elif identifier == "hardlinked_source":
            os.link(outside / "private.md", vault / "Concepts/hard.md")
        elif identifier == "hardlinked_output":
            os.link(outside / "sentinel.bin", vault / "hard-output")

    def export(self, case):
        identifier, selected, output, mode = case
        scope, vault, outside = self.fixture(identifier)
        try:
            self.prepare_case(identifier, vault, outside)
        except OSError as error:
            self.cases.append({"id": "data.export." + identifier, "verdict": "NOT CHECKED", "expected": "Native links/hardlinks are exercised where supported",
                               "observed": {"error": str(error)}, "evidence": []})
            return
        before = inventory(scope)
        self.save(identifier + ".before.json", before)
        record, stdout, stderr = self.command(identifier, [sys.executable, "-B", str(vault / "scripts/export_bundle.py"),
                    "--paths", *selected, "--out", output], cwd=vault, vault=vault)
        after = inventory(scope)
        self.save(identifier + ".after.json", after)
        observation = preservation_observation(before, after, output if mode == "bundle" else None)
        copied = {relative: before.get("vault/" + relative, {}).get("sha256") for relative in self.sources}
        observation["copied_toolkit_matches_source"] = copied == self.sources
        protected = ["People/Self.md", "People/Self-Proposals/pending.md", "People/Self-Proposals/rejected.md"]
        observation["protected_bytes_unchanged"] = all((vault / p).read_bytes() == NOTES[p] for p in protected)
        observation["exit_code"] = record["exit_code"]
        if mode == "refuse":
            observation["output_absent_or_preexisting"] = not (vault / output).exists() or "vault/" + output in before
            passed = (record["exit_code"] != 0 and bool(stderr.strip()) and not record["error"] and observation["unchanged"]
                      and observation["protected_bytes_unchanged"] and observation["copied_toolkit_matches_source"]
                      and observation["output_absent_or_preexisting"])
            expected = "Nonzero refusal with diagnostics; complete source, unrelated output, links, external targets and identity evidence remain byte-identical"
        else:
            observation["bundle"] = bundle_observation(vault, output)
            passed = (record["exit_code"] == 0 and not record["error"] and observation["unchanged"]
                      and observation["protected_bytes_unchanged"] and observation["copied_toolkit_matches_source"]
                      and observation["bundle"]["valid"])
            expected = "Exact selected bytes and manifest entries only; dependency omissions declared; complete original inventory and protected identity evidence unchanged"
        self.cases.append({"id": "data.export." + identifier, "verdict": "PASS" if passed else "FAIL", "expected": expected,
                           "observed": observation, "evidence": [identifier + suffix for suffix in
                           (".before.json", ".after.json", ".command.json", ".stdout.txt", ".stderr.txt")]})

    def finish(self, error=None):
        after = self.sentinels()
        current = {p.relative_to(ROOT).as_posix(): sha(p) if p.is_file() else None for p in source_files()}
        stable = current == self.sources and sha(__file__) == self.producer_hash
        isolated = self.before == after
        stopped = bool(self.processes) and all(p["stopped"] for p in self.processes)
        complete = len(self.cases) == len(CASES) and all(c["verdict"] == "PASS" for c in self.cases)
        if error is not None:
            self.save("execution-error.json", {"error": str(error)})
        report = {"producer": PRODUCER, "producer_sha256": self.producer_hash, "source_root": str(ROOT),
                  "revision": getattr(self, "revision", None), "platform": platform.platform(), "python": sys.version,
                  "scope": "source-only export CLI in complete toolkit copies with wholly synthetic vault data",
                  "verdict": "PASS" if error is None and stable and isolated and stopped and complete else "FAIL",
                  "ideal_system_verdict": "NOT CHECKED", "fixed_outcome_candidate": "DATA.safe_export",
                  "acceptance_credit_awarded": False, "product_hashes": self.sources, "product_hashes_after": current,
                  "product_and_producer_unchanged": stable, "cases": self.cases, "processes": self.processes,
                  "all_started_processes_stopped": stopped,
                  "isolation": {"before": self.before, "after": after, "selected_sentinels_unchanged": isolated,
                                "limitation": "Selected real-vault sentinels only; this is not an exhaustive filesystem audit"},
                  "limitations": ["No installed-package or host claim", "No privacy policy, restore, human approval or generated-writer atomicity claim",
                                  "Native link setup failure remains NOT CHECKED and prevents an export PASS"],
                  "error": str(error) if error is not None else None}
        report["evidence_files"] = {p.name: sha(p) for p in sorted(self.directory.iterdir()) if p.is_file() and p.name != "report.json"}
        self.save("report.json", report)
        print(json.dumps({"report": str(self.directory / "report.json"), "verdict": report["verdict"],
                          "passed": sum(c["verdict"] == "PASS" for c in self.cases), "total": len(CASES)}))
        return 0 if report["verdict"] == "PASS" else 1

    def run(self):
        self.producer_hash = sha(__file__)
        error = None
        try:
            _, output, _ = self.command("revision", ["git", "rev-parse", "HEAD"], ROOT)
            self.revision = output.strip()
            for case in CASES:
                self.export(case)
        except BaseException as caught:
            error = caught
        return self.finish(error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise InterruptedError("Export proof interrupted by signal " + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    return DataRun(args.output).run()


if __name__ == "__main__":
    raise SystemExit(main())
