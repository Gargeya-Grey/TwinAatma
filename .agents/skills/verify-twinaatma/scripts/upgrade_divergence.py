"""Prove an in-place upgrade and two-device divergence with the exact installed artifacts.

Upgrade: the previous product revision is installed from its own wheel, a synthetic vault is
filled, then the same environment is upgraded to the current wheel and the current
executable opens the same vault. Divergence: two vault copies with separate state
directories are driven by the current installed wheel while a simulated sync tool copies
files both ways and leaves a conflict copy.

The approval command refuses without a console. Each approval is launched in a hidden real
console only to observe its refusal or its prompt. No answer is ever sent: the observer has
no code that writes input, and it stops that exact child process when the prompt appears.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import string
import subprocess
import sys
import time
import uuid

import artifact
import upgrade_divergence_adapter as grader

ROOT = Path(__file__).resolve().parents[4]
PRODUCER = grader.PRODUCER
CASE_IDS = (
    "upgrade.old_baseline",
    "upgrade.installed_current",
    "upgrade.notes_ids_links_preserved",
    "upgrade.self_unchanged",
    "upgrade.recall_works",
    "upgrade.index_rebuilds_automatically",
    "upgrade.pending_proposal_valid_same_device",
    "upgrade.doctor_passes",
    "upgrade.version_schema_reported",
    "upgrade.validate_clean",
    "upgrade.executable_opens_upgraded_vault",
    "divergence.devices_prepared",
    "divergence.sync_keeps_both_copies",
    "divergence.no_rewrite",
    "divergence.conflict_copies_searchable",
    "divergence.doctor_flags_conflict_copy",
    "divergence.foreign_proposal_refused",
    "divergence.refusal_hints_propose_again",
    "divergence.proposal_valid_on_origin",
    "divergence.foreign_ledger_fails_closed",
    "divergence.doctor_explains_foreign_ledger",
    "divergence.own_proposal_valid_on_b",
    "divergence.self_unchanged_everywhere",
)
assert CASE_IDS == grader.CASE_IDS, "Producer and grader case lists differ"

SYNC_IGNORED = ("knowledge_index.db", ".knowledgeos/")
ORCHARD = b"""---
type: concept
title: Orchard plan
description: Synthetic orchard planning note
status: active
schema: knowledgeos-v0.3
created: 2026-10-21
updated: 2026-10-21
tags: [synthetic, upgrade]
id: kos:concept:orchard-plan
---
# Orchard plan
The orchardquince rows get pruned before the harvest. See [Harvest](../Projects/Harvest.md) and [Self](../People/Self.md).
"""
HARVEST = (b"---\r\ntype: project\r\ntitle: Harvest\r\ndescription: Synthetic harvest project\r\nstatus: active\r\n"
           b"schema: knowledgeos-v0.3\r\ncreated: 2026-10-21\r\nupdated: 2026-10-21\r\ntags: [synthetic, upgrade]\r\n"
           b"id: kos:project:harvest\r\n---\r\n# Harvest\r\nThe harvest follows the [orchard plan](../Concepts/Orchard-Plan.md).\r\n")
SHARED = b"""---
type: project
title: Shared plan
description: Synthetic plan edited on two devices
status: active
schema: knowledgeos-v0.3
created: 2026-10-21
updated: 2026-10-21
tags: [synthetic, divergence]
id: kos:project:shared-plan
---
# Shared plan
The plan links to [Self](../People/Self.md).
"""
PROPOSAL_A = "* Prefer short notes before long ones"
PROPOSAL_B = "* Avoid planning on two devices at once"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def product_hashes():
    return artifact.product_hashes()


def alive(pid):
    """True while a process with this PID still runs (native Windows)."""
    import ctypes
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    code = ctypes.c_ulong()
    kernel.GetExitCodeProcess(handle, ctypes.byref(code))
    kernel.CloseHandle(handle)
    return code.value == 259


def load_artifact(path, kind, current):
    """Re-validate a retained artifact install report against the exact current product."""
    path = artifact.plain(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data.get("producer") != artifact.PRODUCER or data.get("producer_sha256") != sha(Path(artifact.__file__))
            or data.get("product_hashes") != current or data.get("verdict") != "PASS"
            or any(data.get(k) is not True for k in ("source_bound", "product_unchanged", "artifact_unchanged", "all_started_processes_stopped"))):
        raise ValueError("Installed artifact evidence is stale, failed or incomplete: " + str(path))
    for name, digest in data["transcript_files"].items():
        if Path(name).name != name or sha(path.parent / name) != digest:
            raise ValueError("Retained artifact transcript changed: " + name)
    item, installation = data["artifact"], data["installation"]
    if item["kind"] != kind:
        raise ValueError("Expected a " + kind + " artifact report: " + str(path))
    candidate = artifact.plain(item["path"])
    if sha(candidate) != item["sha256"]:
        raise ValueError("Retained artifact changed")
    executable = artifact.plain(installation["executable"])
    if kind == "wheel":
        artifact.wheel_binding(candidate, current)
        artifact.installed_origin(installation["import_origin"], path.parent / "venv", current)
        for filename, digest in installation["file_hashes"].items():
            if sha(artifact.plain(filename)) != digest:
                raise ValueError("Retained installed file changed: " + filename)
        version = grader.wheel_facts(candidate)["version"]
    else:
        artifact.binary_binding(candidate, path.parent / "build-manifest.json", current)
        version = None
    return {"report": str(path), "report_sha256": sha(path), "artifact_path": str(candidate), "artifact_sha256": item["sha256"],
            "executable": str(executable), "executable_sha256": sha(executable), "version": version,
            "_installation": installation, "_item": item, "_kind": kind}


def artifacts_unchanged(refs):
    try:
        for ref in refs.values():
            if sha(ref["artifact_path"]) != ref["artifact_sha256"] or sha(ref["executable"]) != ref["executable_sha256"]:
                return False
            if ref["_kind"] == "wheel":
                if any(sha(artifact.plain(p)) != h for p, h in ref["_installation"]["file_hashes"].items()):
                    return False
            elif artifact.distribution_files(Path(ref["_item"]["distribution_root"])) != ref["_item"]["distribution_files"]:
                return False
        return True
    except (OSError, ValueError, KeyError):
        return False


def clean_env(state):
    env = dict(os.environ, KNOWLEDGEOS_STATE_DIR=str(state), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "KNOWLEDGEOS_VAULT", "KNOWLEDGEOS_GATE_KEY"):
        env.pop(key, None)
    return env


class Run:
    def __init__(self, output, artifact_reports, old_wheel):
        base = Path(output).resolve()
        generated = (ROOT / "work/gc-artifacts").resolve()
        if not base.is_relative_to(generated) or ".knowledgeos" not in base.relative_to(generated).parts:
            raise ValueError("Output must be below work/gc-artifacts and contain .knowledgeos")
        self.current = product_hashes()
        self.protected = [ROOT / "People/Self.md", ROOT / "knowledge_index.db", ROOT / ".knowledgeos/autopilot.json", Path.home() / ".codex/config.toml"]
        self.before = self.sentinels()
        self.refs = {}
        for report in artifact_reports:
            data = json.loads(artifact.plain(report).read_text(encoding="utf-8"))
            kind = data.get("artifact", {}).get("kind")
            if kind not in ("wheel", "binary") or kind in self.refs:
                raise ValueError("Supply exactly one wheel and one binary artifact report")
            self.refs[kind] = load_artifact(report, kind, self.current)
        if set(self.refs) != {"wheel", "binary"}:
            raise ValueError("Supply exactly one wheel and one binary artifact report")
        self.old_wheel = artifact.plain(old_wheel)
        self.old = grader.wheel_facts(self.old_wheel)
        new_facts = grader.wheel_facts(self.refs["wheel"]["artifact_path"])
        if (grader.version_tuple(self.old["version"]) > grader.version_tuple(new_facts["version"])
                or self.old["version"] == new_facts["version"]):
            raise ValueError("The previous wheel must be older than the current wheel")
        self.directory = base / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
        self.directory.mkdir(parents=True)
        self.neutral = self.directory / "neutral"
        self.neutral.mkdir()
        self.calls = []
        self.processes = []
        self.seq = 0
        self.errors = []
        (self.directory / "case-plan.json").write_text(json.dumps(list(CASE_IDS), indent=2), encoding="utf-8")
        (self.directory / grader.OBSERVER_NAME).write_bytes(grader.OBSERVER_SOURCE.encode("utf-8"))
        self.cases = []

    def sentinels(self):
        return {str(p): sha(p) if p.is_file() else None for p in self.protected}

    def stem(self, label):
        if any(row["label"] == label for row in self.calls):
            raise ValueError("Duplicate label: " + label)
        self.seq += 1
        return "%03d-%s" % (self.seq, label)

    def write(self, name, value):
        (self.directory / name).write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")

    def snap(self, name, vault):
        self.write(name + ".json", grader.snapshot(vault))

    def call(self, label, command, env, *, role="product", timeout=300):
        stem = self.stem(label)
        command = [str(c) for c in command]
        started = time.monotonic()
        child = subprocess.Popen(command, cwd=self.neutral, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        record = {"pid": child.pid, "role": label, "stopped": False}
        self.processes.append(record)
        error = None
        try:
            stdout, stderr = child.communicate(timeout=timeout)
        except BaseException as exc:
            error = exc
            subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, timeout=30)
            stdout, stderr = child.communicate(timeout=30)
        finally:
            record.update(stopped=child.poll() is not None, exit_code=child.returncode)
        (self.directory / (stem + ".stdout.txt")).write_text(stdout, encoding="utf-8")
        (self.directory / (stem + ".stderr.txt")).write_text(stderr, encoding="utf-8")
        retained = {"command": command, "cwd": str(self.neutral), "pid": child.pid, "exit_code": child.returncode,
                    "state_dir": env.get("KNOWLEDGEOS_STATE_DIR"), "seconds": round(time.monotonic() - started, 3)}
        (self.directory / (stem + ".command.json")).write_text(json.dumps(retained, indent=2), encoding="utf-8")
        self.calls.append({"seq": self.seq, "label": label, "kind": "command", "role": role, "command": command, "pid": child.pid,
                           "exit_code": child.returncode, "stopped": record["stopped"], "stdout": stem + ".stdout.txt",
                           "stderr": stem + ".stderr.txt", "record": stem + ".command.json"})
        print(("ok   " if child.returncode == 0 else "exit%s " % child.returncode) + label, flush=True)
        if error:
            raise error
        return child.returncode, stdout, stderr

    def console(self, label, command, env, *, timeout=60):
        """Observe an approval command in a hidden real console. Never sends input."""
        stem = self.stem(label)
        command = [str(c) for c in command]
        spec = {"command": command, "cwd": str(self.neutral), "stdout": str(self.directory / (stem + ".stdout.txt")),
                "stderr": str(self.directory / (stem + ".stderr.txt")), "record": str(self.directory / (stem + ".record.json")),
                "marker": grader.PROMPT, "timeout": timeout}
        (self.directory / (stem + ".spec.json")).write_text(json.dumps(spec, indent=2), encoding="utf-8")
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0
        observer = subprocess.Popen([sys.executable, "-I", str(self.directory / grader.OBSERVER_NAME), str(self.directory / (stem + ".spec.json"))],
                                    creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=info, env=env)
        self.processes.append({"pid": observer.pid, "role": label, "stopped": False})
        try:
            observer.wait(timeout=timeout + 90)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(observer.pid), "/T", "/F"], capture_output=True, timeout=30)
            observer.wait(timeout=30)
        self.processes[-1]["stopped"] = observer.poll() is not None
        record = json.loads((self.directory / (stem + ".record.json")).read_text(encoding="utf-8"))
        child_pid = record["child_pid"]
        self.processes.append({"pid": child_pid, "role": label + "-child", "stopped": bool(record["stopped"]) and not alive(child_pid)})
        self.calls.append({"seq": self.seq, "label": label, "kind": "console", "role": "product", "command": command, "pid": observer.pid,
                           "child_pid": child_pid, "exit_code": record["exit_code"], "stopped": self.processes[-2]["stopped"],
                           "stdout": stem + ".stdout.txt", "stderr": stem + ".stderr.txt", "record": stem + ".record.json"})
        print("%-5s %s (%s)" % ("seen", label, record["reason"]), flush=True)
        return record

    def guarded(self, scenario):
        try:
            scenario()
        except BaseException as exc:
            self.errors.append({"scenario": scenario.__name__, "error": type(exc).__name__ + ": " + str(exc)[-1500:]})
            print("ERROR in %s: %s" % (scenario.__name__, exc), flush=True)

    def product(self, label, command, env):
        return self.call(label, command, env)

    def upgrade(self):
        root = self.directory / "upgrade"
        root.mkdir()
        venv, vault, state = root / "venv", root / "vault", root / "state"
        env = clean_env(state)
        python, exe = venv / "Scripts/python.exe", venv / "Scripts/twinaatma.exe"
        self.call("up-venv", [sys.executable, "-I", "-m", "venv", "--without-pip", venv], env, role="infrastructure")
        self.call("up-old-install", [sys.executable, "-I", "-m", "pip", "--python", python, "install", "--no-index", "--no-deps", self.old_wheel], env, role="infrastructure")
        self.product("up-old-version", [exe, "version"], env)
        self.product("up-old-init", [exe, "init", vault, "--name", "Upgrade fixture", "--non-interactive"], env)
        (vault / "Concepts/Orchard-Plan.md").write_bytes(ORCHARD)
        (vault / "Projects").mkdir(exist_ok=True)
        (vault / "Projects/Harvest.md").write_bytes(HARVEST)
        self.product("up-old-capture", [exe, "memory", "memory_capture", "--vault", vault, "--title", "Old capture", "--content",
                     "The old capture token %s stays recallable. See [Orchard](../Concepts/Orchard-Plan.md)." % grader.CAPTURE_TOKEN], env)
        _, proposed, _ = self.product("up-old-propose", [exe, "memory", "memory_propose_self_update", "--vault", vault, "--section", "heuristics",
                                      "--summary", "Prefer short notes", "--proposed-markdown", PROPOSAL_A, "--rationale", "upgrade fixture"], env)
        self.product("up-old-search", [exe, "memory", "memory_search", "--vault", vault, "--query", grader.ORCHARD_TOKEN], env)
        self.snap("up-pre", vault)
        proposal = Path(json.loads(proposed)["proposal_path"]).name
        self.call("up-new-install", [sys.executable, "-I", "-m", "pip", "--python", python, "install", "--no-index", "--no-deps", self.refs["wheel"]["artifact_path"]], env, role="infrastructure")
        package = venv / "Lib/site-packages/knowledgeos"
        self.write("up-installed.json", {"modules": {p.name: sha(p) for p in sorted(package.glob("*.py"))}, "package": str(package)})
        self.product("up-new-version", [exe, "version"], env)
        self.product("up-doctor-before", [exe, "doctor", "--vault", vault], env)
        self.product("up-search-orchard", [exe, "memory", "memory_search", "--vault", vault, "--query", grader.ORCHARD_TOKEN], env)
        self.product("up-search-capture", [exe, "memory", "memory_search", "--vault", vault, "--query", grader.CAPTURE_TOKEN], env)
        self.product("up-doctor-after", [exe, "doctor", "--vault", vault], env)
        self.product("up-validate", [exe, "validate", "--vault", vault], env)
        self.product("up-version-check", [python, "-I", "-c", grader.VERSION_PROBE, vault], env)
        self.product("up-pending", [exe, "self", "pending", "--vault", vault], env)
        self.product("up-list-proposals", [exe, "memory", "memory_list_self_proposals", "--vault", vault], env)
        self.console("up-approve", [exe, "self", "approve", proposal, "--vault", vault], env)
        self.snap("up-post", vault)
        binary = self.refs["binary"]["executable"]
        self.product("exe-version", [binary, "version"], env)
        self.product("exe-doctor", [binary, "doctor", "--vault", vault], env)
        self.product("exe-search", [binary, "memory", "memory_search", "--vault", vault, "--query", grader.ORCHARD_TOKEN], env)
        self.product("exe-pending", [binary, "self", "pending", "--vault", vault], env)
        self.snap("up-post-exe", vault)

    def files(self, vault):
        found = {}
        for path in sorted(Path(vault).rglob("*")):
            rel = path.relative_to(vault).as_posix()
            if path.is_file() and rel != "knowledge_index.db" and not rel.startswith(("knowledge_index.db", ".knowledgeos/")):
                found[rel] = path.read_bytes()
        return found

    def sync(self, a, b, name, only=None):
        """Copy files both ways; keep both versions of a note that differs as a conflict copy."""
        fa, fb = self.files(a), self.files(b)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        device = "".join(random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(7))
        operations = []

        def put(root, rel, data):
            target = Path(root) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        for rel in sorted(set(fa) | set(fb)):
            if only is not None and rel not in only:
                continue
            if rel in fa and rel not in fb:
                put(b, rel, fa[rel])
                operations.append({"op": "copy", "from": "a", "to": "b", "path": rel, "sha256": hashlib.sha256(fa[rel]).hexdigest()})
            elif rel in fb and rel not in fa:
                put(a, rel, fb[rel])
                operations.append({"op": "copy", "from": "b", "to": "a", "path": rel, "sha256": hashlib.sha256(fb[rel]).hexdigest()})
            elif fa[rel] != fb[rel]:
                stem, suffix = rel.rsplit(".", 1)
                conflict = "%s.sync-conflict-%s-%s.%s" % (stem, stamp, device, suffix)
                put(a, conflict, fb[rel])
                put(b, conflict, fb[rel])
                put(b, rel, fa[rel])
                operations.append({"op": "conflict", "winner": "a", "path": rel, "conflict_copy": conflict,
                                   "winner_sha256": hashlib.sha256(fa[rel]).hexdigest(), "loser_sha256": hashlib.sha256(fb[rel]).hexdigest()})
        self.write(name + ".json", {"ignored": list(SYNC_IGNORED), "operations": operations})
        return operations

    def divergence(self):
        wheel = self.refs["wheel"]["executable"]
        a_dir, b_dir = self.directory / "device-a", self.directory / "device-b"
        a_dir.mkdir()
        b_dir.mkdir()
        a_vault, b_vault, a_state, b_state = a_dir / "vault", b_dir / "vault", a_dir / "state", b_dir / "state"
        env_a, env_b = clean_env(a_state), clean_env(b_state)
        self.product("dv-a-init", [wheel, "init", a_vault, "--name", "Device fixture", "--non-interactive"], env_a)
        (a_vault / "Projects").mkdir(exist_ok=True)
        (a_vault / grader.SHARED_NOTE).write_bytes(SHARED)
        self.snap("dv-init-a", a_vault)
        shutil.copytree(a_vault, b_vault, ignore=shutil.ignore_patterns("knowledge_index.db*", ".knowledgeos"))
        copy_equal = self.files(a_vault) == self.files(b_vault)
        self.snap("dv-init-b", b_vault)
        self.product("dv-a-capture", [wheel, "memory", "memory_capture", "--vault", a_vault, "--title", "Device A capture", "--content", "Alpha device capture token amberfalcon."], env_a)
        self.product("dv-b-capture", [wheel, "memory", "memory_capture", "--vault", b_vault, "--title", "Device B capture", "--content", "Bravo device capture token bluepelican."], env_b)
        (a_vault / grader.SHARED_NOTE).write_bytes(SHARED + ("\nDecision A: use the %s route.\n" % grader.WINNER_TOKEN).encode())
        (b_vault / grader.SHARED_NOTE).write_bytes(SHARED + ("\nDecision B: use the %s route.\n" % grader.LOSER_TOKEN).encode())
        self.snap("dv-pre-sync-a", a_vault)
        self.snap("dv-pre-sync-b", b_vault)
        self.sync(a_vault, b_vault, "dv-sync")
        self.snap("dv-synced-a", a_vault)
        self.snap("dv-synced-b", b_vault)
        for device, vault, env in (("a", a_vault, env_a), ("b", b_vault, env_b)):
            self.product("dv-%s-search-winner" % device, [wheel, "memory", "memory_search", "--vault", vault, "--query", grader.WINNER_TOKEN], env)
            self.product("dv-%s-search-loser" % device, [wheel, "memory", "memory_search", "--vault", vault, "--query", grader.LOSER_TOKEN], env)
            self.product("dv-%s-doctor" % device, [wheel, "doctor", "--vault", vault], env)
            self.product("dv-%s-breathe" % device, [wheel, "breathe", "--vault", vault, "--task-hint", "device fixture"], env)
            self.product("dv-%s-validate" % device, [wheel, "validate", "--vault", vault], env)
        self.snap("dv-ops-a", a_vault)
        self.snap("dv-ops-b", b_vault)
        _, proposed, _ = self.product("dv-a-propose", [wheel, "memory", "memory_propose_self_update", "--vault", a_vault, "--section", "heuristics",
                                      "--mode", "append", "--summary", "Prefer short notes", "--proposed-markdown", PROPOSAL_A, "--rationale", "device A"], env_a)
        proposal_a = json.loads(proposed)["proposal_path"]
        self.sync(a_vault, b_vault, "dv-sync-proposal", only={proposal_a})
        self.product("dv-a-pending", [wheel, "self", "pending", "--vault", a_vault], env_a)
        self.product("dv-b-pending", [wheel, "self", "pending", "--vault", b_vault], env_b)
        self.console("dv-a-approve-pa", [wheel, "self", "approve", Path(proposal_a).name, "--vault", a_vault], env_a)
        self.console("dv-b-approve-pa", [wheel, "self", "approve", Path(proposal_a).name, "--vault", b_vault], env_b)
        ledgers = sorted(a_state.glob("vaults/*/*.jsonl"))
        copied = {"copied": False, "source": None, "target": None, "sha256": None}
        if len(ledgers) == 1:
            relative = ledgers[0].relative_to(a_state)
            target = b_state / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(ledgers[0].read_bytes())
            copied = {"copied": True, "source": relative.as_posix(), "target": relative.as_posix(), "sha256": sha(target)}
        self.write("dv-ledger-copy.json", copied)
        self.product("dv-b-pending-ledger", [wheel, "self", "pending", "--vault", b_vault], env_b)
        self.product("dv-b-list-ledger", [wheel, "memory", "memory_list_self_proposals", "--vault", b_vault], env_b)
        self.console("dv-b-approve-ledger", [wheel, "self", "approve", Path(proposal_a).name, "--vault", b_vault], env_b)
        self.product("dv-b-doctor-ledger", [wheel, "doctor", "--vault", b_vault], env_b)
        _, own, _ = self.product("dv-b-propose", [wheel, "memory", "memory_propose_self_update", "--vault", b_vault, "--section", "anti_goals",
                                  "--mode", "append", "--summary", "Avoid two-device planning", "--proposed-markdown", PROPOSAL_B, "--rationale", "device B"], env_b)
        self.product("dv-b-pending-own", [wheel, "self", "pending", "--vault", b_vault], env_b)
        self.console("dv-b-approve-own", [wheel, "self", "approve", Path(json.loads(own)["proposal_path"]).name, "--vault", b_vault], env_b)
        self.snap("dv-final-a", a_vault)
        self.snap("dv-final-b", b_vault)

        def key(state):
            path = state / "gate.key"
            return sha(path) if path.is_file() else None

        def marker(vault):
            try:
                return json.loads((vault / ".knowledgeos-vault.json").read_text(encoding="utf-8")).get("vault_id")
            except (OSError, ValueError):
                return None

        self.write("dv-prepared.json", {
            "device_a": {"vault": str(a_vault), "state": str(a_state), "vault_id": marker(a_vault), "key_sha256": key(a_state), "self": json.loads((self.directory / "dv-init-a.json").read_text())["self"]},
            "device_b": {"vault": str(b_vault), "state": str(b_state), "vault_id": marker(b_vault), "key_sha256": key(b_state), "self": json.loads((self.directory / "dv-init-b.json").read_text())["self"]},
            "copy_tree_equal": copy_equal, "executable": wheel})

    def finish(self):
        after = self.sentinels()
        trees = {}
        for name in grader.FINAL_TREES:
            target = self.directory / name
            trees[name] = grader.tree_hashes(target) if target.is_dir() else {}
        transcripts = {p.name: sha(p) for p in sorted(self.directory.iterdir()) if p.is_file() and p.name != "report.json"}
        data = {
            "producer": PRODUCER, "producer_sha256": sha(__file__), "support": {grader.SUPPORT_NAME: sha(grader.__file__)},
            "product_hashes": self.current, "scope": grader.SCOPE, "scope_description": grader.SCOPE_DESCRIPTION,
            "platform": platform.platform(), "python_version": sys.version,
            "artifacts": {kind: {k: v for k, v in ref.items() if not k.startswith("_")} for kind, ref in self.refs.items()},
            "old_wheel": {"path": str(self.old_wheel), "sha256": sha(self.old_wheel), "version": self.old["version"], "members": self.old["members"],
                          "revision": grader.OLD_REVISION},
            "expected_case_ids": list(CASE_IDS), "calls": self.calls, "processes": self.processes,
            "all_started_processes_stopped": all(p["stopped"] for p in self.processes),
            "execution_errors": self.errors, "isolation": {"before": self.before, "after": after, "unchanged": self.before == after},
            "artifacts_unchanged": artifacts_unchanged(self.refs), "product_unchanged": product_hashes() == self.current,
            "final_trees": trees, "transcript_files": transcripts,
        }
        evidence = grader.Evidence(self.directory, data)
        data["cases"] = [grader.case_row(evidence, case_id) for case_id in CASE_IDS]
        for row in data["cases"]:
            print("%s %s" % (row["verdict"], row["id"]), flush=True)
        stable = (not self.errors and data["all_started_processes_stopped"] and data["isolation"]["unchanged"]
                  and data["artifacts_unchanged"] and data["product_unchanged"])
        data["verdict"] = "PASS" if stable and all(row["verdict"] == "PASS" for row in data["cases"]) else "FAIL"
        (self.directory / "report.json").write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        print(self.directory, flush=True)
        return 0 if data["verdict"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-report", type=Path, action="append", required=True,
                        help="Retained artifact.py report; give the current wheel report and the current executable report")
    parser.add_argument("--old-wheel", type=Path, required=True, help="Wheel built from the previous product revision")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("The approval console observer needs native Windows")
    run = Run(args.output, args.artifact_report, args.old_wheel)
    for scenario in (run.upgrade, run.divergence):
        run.guarded(scenario)
    return run.finish()


if __name__ == "__main__":
    raise SystemExit(main())
